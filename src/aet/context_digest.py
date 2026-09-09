"""Current-rules digest and durable-insight selection for ``aet context`` (R-5).

The digest is generated on every invocation from ADR frontmatter
(``subject:``/``supersedes:``) — never hand-maintained, never committed.
Durable insights are the top-N most recent learnings, read directly from
``.agents/learnings.jsonl`` behind a ``Selector`` protocol so the
recurrence-threshold promotion mechanism plugs in later without call-site
changes.

Every reader fails open: missing directories, missing files, malformed
frontmatter, and malformed JSONL lines degrade to empty output, never errors.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from aet.plan_parser import parse_frontmatter

ADR_GLOB = "*.md"
DEFAULT_TOP_N = 5
_ADR_NUMBER_RE = re.compile(r"^(\d+)")


@dataclass
class AdrEntry:
    """One ADR's digest-relevant frontmatter."""

    stem: str
    number: int | None
    subject: str
    supersedes: list[int]
    relates: list[int] = field(default_factory=list)


@dataclass
class AdrCorpusReport:
    """Integrity and resolution audit of an ADR corpus."""

    duplicate_numbers: dict[int, list[str]]
    dangling_supersedes: dict[str, list[int]]
    dangling_relates: dict[str, list[int]]
    superseded_relates: dict[str, list[int]]


def _adr_number(stem: str) -> int | None:
    """Extract the leading ADR number from a file stem, or None."""
    match = _ADR_NUMBER_RE.match(stem)
    if match is None:
        return None
    return int(match.group(1))


def _coerce_supersedes(value: Any) -> list[int]:
    """Normalize a ``supersedes:`` or ``relates:`` frontmatter value to a list of ints."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    numbers: list[int] = []
    for item in items:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            numbers.append(item)
            continue
        text = str(item).strip().lstrip("#")
        text = re.sub(r"(?i)^adr-?", "", text)
        try:
            numbers.append(int(text))
        except ValueError:
            continue
    return numbers


def audit_adr_entries(entries: list[AdrEntry]) -> AdrCorpusReport:
    """Audit ADR entries for duplicate numbers, dangling references, and superseded targets."""
    by_number: dict[int, list[str]] = {}
    for entry in entries:
        if entry.number is not None:
            by_number.setdefault(entry.number, []).append(entry.stem)

    duplicate_numbers = {num: stems for num, stems in by_number.items() if len(stems) > 1}
    all_numbers = set(by_number.keys())

    # A number is superseded if any entry names it in supersedes
    superseded_numbers = {
        n for entry in entries for n in entry.supersedes if n in all_numbers
    }

    dangling_supersedes: dict[str, list[int]] = {}
    dangling_relates: dict[str, list[int]] = {}
    superseded_relates: dict[str, list[int]] = {}

    for entry in entries:
        for n in entry.supersedes:
            if n not in all_numbers:
                dangling_supersedes.setdefault(entry.stem, []).append(n)
        for n in entry.relates:
            if n not in all_numbers:
                dangling_relates.setdefault(entry.stem, []).append(n)
            elif n in superseded_numbers:
                superseded_relates.setdefault(entry.stem, []).append(n)

    return AdrCorpusReport(
        duplicate_numbers=duplicate_numbers,
        dangling_supersedes=dangling_supersedes,
        dangling_relates=dangling_relates,
        superseded_relates=superseded_relates,
    )


def read_adr_entries(adr_dir: Path) -> list[AdrEntry]:
    """Read digest entries from ``adr_dir``; ADRs without ``subject:`` are excluded."""
    if not adr_dir.is_dir():
        return []
    entries: list[AdrEntry] = []
    for path in sorted(adr_dir.glob(ADR_GLOB)):
        frontmatter = parse_frontmatter(path)
        subject = frontmatter.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            continue
        entries.append(
            AdrEntry(
                stem=path.stem,
                number=_adr_number(path.stem),
                subject=subject.strip(),
                supersedes=_coerce_supersedes(frontmatter.get("supersedes")),
                relates=_coerce_supersedes(frontmatter.get("relates")),
            )
        )
    return entries


def _live_rule(subject: str, live: AdrEntry, lineage: list[str]) -> dict[str, Any]:
    return {
        "subject": subject,
        "status": "live",
        "live": live.stem,
        "lineage": lineage,
        "conflict": None,
    }


def _conflict_rule(subject: str, reason: str) -> dict[str, Any]:
    return {
        "subject": subject,
        "status": "conflict",
        "live": None,
        "lineage": [],
        "conflict": reason,
    }


def resolve_rules(entries: list[AdrEntry]) -> list[dict[str, Any]]:
    """Resolve each subject's ``supersedes:`` chain to the single live ADR.

    Cycles, dangling ``supersedes:`` refs, and dual-live subjects render as an
    explicit CONFLICT marker — never a silent pick.  Rules are subject-sorted.
    """
    by_number = {e.number: e for e in entries if e.number is not None}
    groups: dict[str, list[AdrEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.subject, []).append(entry)

    rules: list[dict[str, Any]] = []
    for subject in sorted(groups):
        members = groups[subject]
        member_numbers = {m.number for m in members if m.number is not None}
        refs = [n for m in members for n in m.supersedes]

        dangling = sorted({n for n in refs if n not in by_number})
        if dangling:
            rendered = ", ".join(str(n) for n in dangling)
            rules.append(_conflict_rule(subject, f"dangling supersedes: {rendered}"))
            continue

        superseded = {n for n in refs if n in member_numbers}
        live = [m for m in members if m.number not in superseded]
        if not live:
            rules.append(_conflict_rule(subject, "cycle: no live ADR remains"))
            continue
        if len(live) > 1:
            stems = ", ".join(sorted(m.stem for m in live))
            rules.append(_conflict_rule(subject, f"dual-live: {stems}"))
            continue

        lineage = sorted(
            (by_number[n].stem for n in superseded if n in by_number),
            key=lambda stem: _adr_number(stem) or 0,
        )
        rules.append(_live_rule(subject, live[0], lineage))
    return rules


def build_rules_digest(adr_dir: Path) -> list[dict[str, Any]]:
    """Build the current-rules digest for ``adr_dir`` (subject-sorted)."""
    return resolve_rules(read_adr_entries(adr_dir))


def render_digest_section(rules: list[dict[str, Any]]) -> str:
    """Render the digest as a human-facing section for the context banner."""
    if not rules:
        return "Current rules: none"
    lines = ["Current rules:"]
    for rule in rules:
        if rule["status"] == "conflict":
            lines.append(f"- CONFLICT {rule['subject']}: {rule['conflict']}")
            continue
        line = f"- {rule['subject']}: {rule['live']}"
        if rule["lineage"]:
            line += f" (supersedes {', '.join(rule['lineage'])})"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Durable insights
# ---------------------------------------------------------------------------


def _parse_timestamp(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, including legacy ``date`` shapes."""
    value = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def read_learnings(path: Path) -> list[dict[str, Any]]:
    """Read learnings entries sorted by recency descending.

    Malformed lines and entries without a parseable ``timestamp`` (or legacy
    ``date``) are skipped; a missing file yields an empty list.
    """
    if not path.is_file():
        return []
    parsed: list[tuple[datetime, dict[str, Any]]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                raw_ts = entry.get("timestamp") or entry.get("date")
                if not isinstance(raw_ts, str):
                    continue
                dt = _parse_timestamp(raw_ts)
                if dt is None:
                    continue
                parsed.append((dt, entry))
    except OSError:
        return []
    parsed.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in parsed]


class Selector(Protocol):
    """Plug point for durable-insight selection strategies."""

    def select(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Choose which recency-sorted entries to surface."""
        ...


@dataclass
class TopNRecentSelector:
    """Shipped degrade path: the ``n`` most recent learnings."""

    n: int = DEFAULT_TOP_N

    def select(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return entries[: self.n]


def select_durable_insights(
    path: Path, selector: Selector | None = None
) -> list[dict[str, Any]]:
    """Return durable insights from ``path`` using ``selector`` (default top-5)."""
    if selector is None:
        selector = TopNRecentSelector()
    return selector.select(read_learnings(path))
