"""Declarative documentation governance rule engine for ``aet docs lint``.

Rules are data, parsed with ``yaml.safe_load``, and evaluated against the
checkout. The evaluator never executes rule content.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from aet.context_digest import AdrEntry, audit_adr_entries

VALID_RULE_TYPES = frozenset(
    {
        "must_contain",
        "must_not_contain",
        "path_exists",
        "path_absent",
        "unique_live_subject",
        "adr_corpus_integrity",
    }
)

_ESCAPE_CLOSED_RE = re.compile(r"<!-- aet-lint: off -->.*?<!-- aet-lint: on -->", re.DOTALL)
_ESCAPE_UNCLOSED_RE = re.compile(r"<!-- aet-lint: off -->.*", re.DOTALL)


def strip_lint_escapes(text: str) -> str:
    """Remove escaped spans between ``<!-- aet-lint: off -->`` and ``<!-- aet-lint: on -->``.

    Treats an unclosed ``<!-- aet-lint: off -->`` as running to the end of the document.
    A document without markers is returned byte-identical.
    """
    if "<!-- aet-lint: off -->" not in text:
        return text
    stripped = _ESCAPE_CLOSED_RE.sub("", text)
    if "<!-- aet-lint: off -->" in stripped:
        stripped = _ESCAPE_UNCLOSED_RE.sub("", stripped)
    return stripped


_strip_lint_escapes = strip_lint_escapes


class DocsLintError(Exception):
    """Raised for unrecoverable rule-file errors."""


class RuleError(DocsLintError):
    """Raised when a single rule is malformed."""

    def __init__(self, index: int, message: str) -> None:
        self.index = index
        super().__init__(f"rule {index}: {message}")


def _relative(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _load_rules(rules_file: Path) -> list[dict]:
    """Load and return the raw rule list from *rules_file*."""
    if not rules_file.exists():
        raise DocsLintError(f"rules file not found: {rules_file}")
    try:
        data = yaml.safe_load(rules_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DocsLintError(f"invalid YAML: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, dict):
        raise DocsLintError("top-level must be a mapping")
    rules = data.get("rules")
    if rules is None:
        return []
    if not isinstance(rules, list):
        raise DocsLintError("'rules' must be a list")
    return rules


def _normalize_values(value: object) -> list[str]:
    """Return *value* as a list of strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise DocsLintError("'value' must be a string or list of strings")


def _extract_section(text: str, section: str) -> str | None:
    """Return the body under the first ATX heading matching *section*.

    The body runs from the line after the heading until the next heading of
    equal or higher level (fewer ``#`` characters).
    """
    text = strip_lint_escapes(text)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        hashes = stripped.split()[0]
        if not hashes or not all(ch == "#" for ch in hashes):
            continue
        level = len(hashes)
        title = stripped[level:].strip()
        if title == section:
            body_lines: list[str] = []
            for j in range(i + 1, len(lines)):
                next_line = lines[j]
                next_stripped = next_line.lstrip()
                if next_stripped.startswith("#"):
                    next_hashes = next_stripped.split()[0]
                    if next_hashes and all(ch == "#" for ch in next_hashes):
                        next_level = len(next_hashes)
                        if next_level <= level:
                            break
                body_lines.append(next_line)
            return "\n".join(body_lines)
    return None


def _adr_id_from_path(path: Path) -> str:
    """Return an ``ADR-NNN`` style identifier from *path*'s filename stem."""
    stem = path.stem
    number_part = stem.split("-", 1)[0]
    if number_part.isdigit():
        return f"ADR-{int(number_part):03d}"
    return stem


def _load_adr_frontmatter(path: Path) -> tuple[dict | None, str | None]:
    """Load YAML frontmatter from an ADR markdown file.

    Returns ``(data, error)``. *data* is ``None`` when the file has no
    frontmatter block. *error* is a non-empty diagnostic string when the
    frontmatter block exists but cannot be parsed.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None, None
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return None, "missing closing frontmatter delimiter"
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        return None, f"malformed frontmatter: {exc}"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "frontmatter must be a mapping"
    return data, None


def _normalize_adr_id(value: object) -> str | None:
    """Return an ``ADR-NNN`` identifier from a *supersedes* value."""
    if isinstance(value, int):
        return f"ADR-{value:03d}"
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return f"ADR-{int(stripped):03d}"
        upper = stripped.upper()
        if upper.startswith("ADR-"):
            return upper
    return None


def _evaluate_unique_live_subject(
    target_path: Path, reason: str, repo_root: Path
) -> list[tuple[Path, str]]:
    """Evaluate the ``unique_live_subject`` rule against *target_path*."""
    violations: list[tuple[Path, str]] = []
    subjects: dict[str, list[tuple[str, Path]]] = {}
    superseded: set[str] = set()

    for md_path in sorted(target_path.glob("*.md")):
        if md_path.name in ("000-template.md", "README.md"):
            continue

        rel = _relative(md_path, repo_root)
        data, error = _load_adr_frontmatter(md_path)
        if error:
            violations.append((rel, f"{reason} ({error})"))
            continue
        if data is None:
            # ADRs without frontmatter have no subject and cannot participate
            # in subject uniqueness. The adr_corpus_integrity rule validates
            # frontmatter presence separately.
            continue

        adr_id = _adr_id_from_path(md_path)

        raw_subject = data.get("subject")
        if raw_subject is None:
            # Missing subject is validated by adr_corpus_integrity.
            continue
        if isinstance(raw_subject, str):
            subject_values = [raw_subject]
        elif isinstance(raw_subject, list) and all(isinstance(s, str) for s in raw_subject):
            subject_values = raw_subject
        else:
            violations.append((rel, f"{reason} ('subject' must be a string or list of strings)"))
            continue

        raw_supersedes = data.get("supersedes", [])
        if isinstance(raw_supersedes, (str, int)):
            raw_supersedes = [raw_supersedes]
        if not isinstance(raw_supersedes, list):
            violations.append((rel, f"{reason} ('supersedes' must be a list)"))
            continue

        for value in raw_supersedes:
            normalized = _normalize_adr_id(value)
            if normalized is None:
                violations.append((rel, f"{reason} (invalid 'supersedes' value: {value!r})"))
                continue
            superseded.add(normalized)

        for subject in subject_values:
            subjects.setdefault(subject, []).append((adr_id, rel))

    for subject, entries in sorted(subjects.items()):
        live = [(adr_id, rel) for adr_id, rel in entries if adr_id not in superseded]
        if len(live) > 1:
            ids = ", ".join(sorted(adr_id for adr_id, _ in live))
            first_path = live[0][1]
            violations.append((first_path, f"{reason} (subject '{subject}' has multiple live ADRs: {ids})"))

    return violations


def _normalize_adr_number(value: object) -> int | None:
    """Return an integer ADR number from a supersedes/relates reference."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip().lstrip("#")
        stripped = re.sub(r"(?i)^adr-?", "", stripped)
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _extract_adr_number(stem: str) -> int | None:
    """Extract leading integer from ADR filename stem."""
    number_part = stem.split("-", 1)[0]
    if number_part.isdigit():
        return int(number_part)
    return None


def _evaluate_adr_corpus_integrity(
    target_path: Path, reason: str, repo_root: Path
) -> list[tuple[Path, str]]:
    """Evaluate the ``adr_corpus_integrity`` rule against *target_path*."""
    violations: list[tuple[Path, str]] = []
    valid_entries: list[AdrEntry] = []
    entry_paths: dict[str, Path] = {}

    for md_path in sorted(target_path.glob("*.md")):
        if md_path.name in ("000-template.md", "README.md"):
            continue

        rel = _relative(md_path, repo_root)
        data, error = _load_adr_frontmatter(md_path)
        if error:
            violations.append((rel, f"{reason} ({error})"))
            continue
        if data is None:
            violations.append((rel, f"{reason} (missing 'subject')"))
            continue

        raw_subject = data.get("subject")
        if raw_subject is None:
            violations.append((rel, f"{reason} (missing 'subject')"))
            continue
        if isinstance(raw_subject, str):
            if not raw_subject.strip():
                violations.append((rel, f"{reason} (missing 'subject')"))
                continue
            subjects = [raw_subject.strip()]
        elif isinstance(raw_subject, list) and all(isinstance(s, str) for s in raw_subject):
            subjects = [s.strip() for s in raw_subject if s.strip()]
            if not subjects:
                violations.append((rel, f"{reason} (missing 'subject')"))
                continue
        else:
            violations.append((rel, f"{reason} ('subject' must be a string or list of strings)"))
            continue

        raw_supersedes = data.get("supersedes", [])
        if isinstance(raw_supersedes, (str, int)):
            raw_supersedes = [raw_supersedes]
        if not isinstance(raw_supersedes, list):
            violations.append((rel, f"{reason} ('supersedes' must be a list)"))
            continue

        supersedes_nums: list[int] = []
        has_supersedes_error = False
        for value in raw_supersedes:
            num = _normalize_adr_number(value)
            if num is None:
                violations.append((rel, f"{reason} (invalid 'supersedes' value: {value!r})"))
                has_supersedes_error = True
            else:
                supersedes_nums.append(num)

        raw_relates = data.get("relates", [])
        if isinstance(raw_relates, (str, int)):
            raw_relates = [raw_relates]
        if not isinstance(raw_relates, list):
            violations.append((rel, f"{reason} ('relates' must be a list)"))
            continue

        relates_nums: list[int] = []
        has_relates_error = False
        for value in raw_relates:
            num = _normalize_adr_number(value)
            if num is None:
                violations.append((rel, f"{reason} (invalid 'relates' value: {value!r})"))
                has_relates_error = True
            else:
                relates_nums.append(num)

        if not has_supersedes_error and not has_relates_error:
            entry_stem = md_path.stem
            entry_num = _extract_adr_number(entry_stem)
            valid_entries.append(
                AdrEntry(
                    stem=entry_stem,
                    number=entry_num,
                    subject=subjects[0],
                    supersedes=supersedes_nums,
                    relates=relates_nums,
                )
            )
            entry_paths[entry_stem] = rel

    report = audit_adr_entries(valid_entries)

    for num in sorted(report.duplicate_numbers):
        stems = report.duplicate_numbers[num]
        ids = ", ".join(stems)
        first_path = entry_paths[stems[0]]
        violations.append((first_path, f"{reason} (duplicate ADR number {num:03d}: {ids})"))

    for stem in sorted(report.dangling_supersedes):
        rel = entry_paths[stem]
        for num in report.dangling_supersedes[stem]:
            violations.append((rel, f"{reason} (dangling supersedes: ADR-{num:03d} does not exist)"))

    for stem in sorted(report.dangling_relates):
        rel = entry_paths[stem]
        for num in report.dangling_relates[stem]:
            violations.append((rel, f"{reason} (dangling relates: ADR-{num:03d} does not exist)"))

    for stem in sorted(report.superseded_relates):
        rel = entry_paths[stem]
        for num in report.superseded_relates[stem]:
            violations.append((rel, f"{reason} (relates to superseded ADR-{num:03d})"))

    return violations


def _validate_rule(raw: object, index: int) -> dict:
    """Validate and normalize a single rule mapping."""
    if not isinstance(raw, dict):
        raise RuleError(index, "must be a mapping")
    rule = dict(raw)
    missing = [k for k in ("type", "target", "reason") if k not in rule]
    if missing:
        raise RuleError(index, f"missing required fields: {', '.join(missing)}")
    rtype = rule["type"]
    if rtype not in VALID_RULE_TYPES:
        raise RuleError(index, f"unknown type '{rtype}'")
    if rtype in ("must_contain", "must_not_contain"):
        if "value" not in rule:
            raise RuleError(index, f"'value' is required for {rtype}")
        rule["value"] = _normalize_values(rule["value"])
    if rtype in ("unique_live_subject", "adr_corpus_integrity") and "value" in rule:
        raise RuleError(index, f"'value' is not allowed for {rtype}")
    severity = rule.get("severity", "error")
    if severity not in ("error", "warning"):
        raise RuleError(index, f"invalid severity '{severity}', must be 'error' or 'warning'")
    rule["severity"] = severity
    return rule


def _check_text(path: Path, text: str, rule: dict, reason: str) -> str | None:
    """Evaluate a ``must_contain`` or ``must_not_contain`` rule against *text*."""
    text = strip_lint_escapes(text)
    section = rule.get("section")
    haystack = text
    section_note = ""
    if section:
        section_body = _extract_section(text, section)
        if section_body is None:
            return f"{reason} (section not found: {section})"
        haystack = section_body
        section_note = f" in section '{section}'"

    values = rule["value"]
    rtype = rule["type"]
    if rtype == "must_contain":
        missing = [v for v in values if v not in haystack]
        if missing:
            return f"{reason} (expected {missing!r}{section_note})"
    elif rtype == "must_not_contain":
        present = [v for v in values if v in haystack]
        if present:
            plural = "" if len(present) == 1 else "s"
            return f"{reason} (found forbidden substring{plural} {present!r}{section_note})"
    return None


def lint_docs(
    rules_file: Path, repo_root: Path, min_severity: str = "error"
) -> list[tuple[Path, str]]:
    """Evaluate the documentation rules file against the checkout.

    Returns a list of ``(relative_path, message)`` violations. An empty list
    means every rule passed.
    """
    rel_rules = _relative(rules_file, repo_root)
    try:
        raw_rules = _load_rules(rules_file)
    except DocsLintError as exc:
        return [(rel_rules, f"cannot load rules: {exc}")]

    rules: list[tuple[int, dict]] = []
    for idx, raw in enumerate(raw_rules, start=1):
        try:
            rule = _validate_rule(raw, idx)
        except DocsLintError as exc:
            return [(rel_rules, str(exc))]
        rules.append((idx, rule))

    violations: list[tuple[Path, str]] = []
    for _idx, rule in rules:
        rule_severity = rule.get("severity", "error")
        if min_severity == "error" and rule_severity == "warning":
            continue

        target = Path(rule["target"])
        if target.is_absolute():
            target_path = target
            rel_target = _relative(target_path, repo_root)
        else:
            target_path = repo_root / target
            rel_target = target

        rtype = rule["type"]
        reason = rule["reason"]

        if rtype in ("path_exists", "path_absent"):
            exists = target_path.exists()
            if rtype == "path_exists" and not exists:
                violations.append((rel_target, f"{reason} (expected path to exist: {target})"))
            elif rtype == "path_absent" and exists:
                violations.append((rel_target, f"{reason} (expected path to be absent: {target})"))
            continue

        if rtype == "unique_live_subject":
            if not target_path.exists():
                violations.append((rel_target, f"{reason} (target directory missing: {target})"))
            elif not target_path.is_dir():
                violations.append((rel_target, f"{reason} (target must be a directory: {target})"))
            else:
                violations.extend(_evaluate_unique_live_subject(target_path, reason, repo_root))
            continue

        if rtype == "adr_corpus_integrity":
            if not target_path.exists():
                violations.append((rel_target, f"{reason} (target directory missing: {target})"))
            elif not target_path.is_dir():
                violations.append((rel_target, f"{reason} (target must be a directory: {target})"))
            else:
                violations.extend(_evaluate_adr_corpus_integrity(target_path, reason, repo_root))
            continue

        if target_path.is_dir() and rtype in ("must_contain", "must_not_contain"):
            found_any = False
            for md_path in sorted(target_path.rglob("*.md")):
                found_any = True
                rel_md = _relative(md_path, repo_root)
                try:
                    text = md_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    violations.append((rel_md, f"{reason} (cannot read file: {exc})"))
                    continue
                message = _check_text(md_path, text, rule, reason)
                if message:
                    violations.append((rel_md, message))
            if not found_any:
                violations.append((rel_target, f"{reason} (no markdown files found in directory: {target})"))
            continue

        if not target_path.exists():
            violations.append((rel_target, f"{reason} (target file missing: {target})"))
            continue
        try:
            text = target_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append((rel_target, f"{reason} (cannot read file: {exc})"))
            continue

        message = _check_text(target_path, text, rule, reason)
        if message:
            violations.append((rel_target, message))

    return violations
