"""Roll up stage telemetry per PRD for one project.

Reads the local telemetry archive that ``aet panel`` serves, attributes each
plan to the PRD that owns its slice prefix, and reports stage sessions,
duration, tokens and cost per PRD.

The rollup emits one payload in two forms. The JSON carries the whole data set
including the per-stage rows, for charting. The markdown renders from that same
payload, so the two cannot disagree.

A project with no PRD directory groups by slice prefix instead. The measures
are the same; only the grouping key changes.
"""

from __future__ import annotations

import collections
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# A slice id is a three- or four-letter prefix and a two-digit number, the
# identifier convention plan files and PRDs share (docs/CONVENTIONS.md).
SLICE = re.compile(r"\b([a-z]{3,4})-([0-9]{2})\b")

UNATTRIBUTED = "(no PRD)"
DEFAULT_PRD_DIR = Path("docs") / "prds"

GROUP_BY_PRD = "prd"
GROUP_BY_PREFIX = "prefix"


class NoTelemetryError(RuntimeError):
    """The archive holds no stage records for the requested project."""


@dataclass
class Stage:
    """One stage session as the archive recorded it."""

    run_id: str
    worktree: str
    task_id: str
    stage: str
    result: str | None
    failure_class: str | None
    start: str
    end: str
    duration_s: float
    tokens: int | None
    cost: float | None
    attempt: int

    @property
    def prefix(self) -> str:
        """The slice prefix that attributes this stage to a PRD."""
        return self.task_id.split("-")[0]


@dataclass
class Rollup:
    """Accumulated measures over a set of stage sessions."""

    plans: set[str] = field(default_factory=set)
    stages: int = 0
    duration_s: float = 0.0
    tokens: int = 0
    cost: float = 0.0
    stages_without_cost: int = 0
    stages_without_tokens: int = 0
    failed_stages: int = 0

    def add(self, s: Stage) -> None:
        self.plans.add(s.task_id)
        self.stages += 1
        self.duration_s += s.duration_s
        # None means the agent CLI reported no usage, which is not the same as
        # a measured zero. The total counts only what was measured and the
        # coverage counters carry the gap.
        if s.cost is None:
            self.stages_without_cost += 1
        else:
            self.cost += s.cost
        if s.tokens is None:
            self.stages_without_tokens += 1
        else:
            self.tokens += s.tokens
        if s.result and s.result != "success":
            self.failed_stages += 1


def project_dir_name(slug: str) -> str:
    """The archive directory for a project slug.

    ``derive_project_slug`` returns ``<repo>/<worktree-label>``. The archive
    nests worktrees under one repository directory, so a project-wide report
    reads the first segment and covers every worktree.
    """
    return slug.split("/", 1)[0]


def read_stages(
    archive: Path,
    project: str,
    worktree: str | None = None,
    since: str | None = None,
) -> list[Stage]:
    """Every stage record for one project, across worktrees unless narrowed."""
    base = archive / project
    if worktree:
        base = base / worktree
    if not base.is_dir():
        raise NoTelemetryError(f"no telemetry directory for {project!r} under {archive}")

    out: list[Stage] = []
    for path in sorted(base.rglob("*.jsonl")):
        if path.name == "work-history.jsonl":
            continue
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "stage" or not rec.get("task_id"):
                continue
            start = rec.get("start_time") or ""
            if since and start < since:
                continue
            out.append(
                Stage(
                    run_id=rec.get("run_id") or "",
                    worktree=_worktree_of(path, archive / project),
                    task_id=rec["task_id"],
                    stage=rec.get("stage") or "?",
                    result=rec.get("result"),
                    failure_class=rec.get("failure_class"),
                    start=start,
                    end=rec.get("end_time") or "",
                    duration_s=rec.get("duration_seconds") or 0.0,
                    tokens=rec.get("token_count"),
                    cost=rec.get("cost_estimate"),
                    attempt=rec.get("attempt") or 1,
                )
            )
    if not out:
        window = f" at or after {since}" if since else ""
        raise NoTelemetryError(f"no stage records under {base}{window}")
    return out


def _worktree_of(path: Path, project_base: Path) -> str:
    """The worktree label a record file sits under."""
    try:
        return path.relative_to(project_base).parts[0]
    except (ValueError, IndexError):
        return "?"


def derive_ownership(prd_dir: Path) -> tuple[dict[str, str], dict[str, dict[str, int]]]:
    """Map a slice prefix to the PRD that cites the most slices of that prefix.

    A PRD cites slices it merely depends on, so a plain "prefix appears in PRD"
    join over-attributes. The majority rule resolves that from the PRDs
    themselves rather than from a hand-kept table. A tie breaks on the PRD name
    so the report is reproducible.
    """
    if not prd_dir.is_dir():
        return {}, {}
    cites: dict[str, dict[str, set[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(set)
    )
    for prd in sorted(prd_dir.glob("*.md")):
        try:
            text = prd.read_text()
        except OSError:
            continue
        for prefix, num in SLICE.findall(text):
            cites[prefix][prd.name].add(num)
    owner: dict[str, str] = {}
    evidence: dict[str, dict[str, int]] = {}
    for prefix, by_prd in cites.items():
        counts = {name: len(nums) for name, nums in by_prd.items()}
        evidence[prefix] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
        owner[prefix] = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return owner, evidence


def hours(seconds: float) -> str:
    """Format a duration as hours and minutes."""
    h, m = divmod(round(seconds / 60), 60)
    return f"{h}h {m:02d}m"


def measures(r: Rollup, total_cost: float) -> dict[str, Any]:
    """The measure block every group in the payload carries."""
    return {
        "plans": len(r.plans),
        "stages": r.stages,
        "duration_seconds": round(r.duration_s, 3),
        "duration_human": hours(r.duration_s),
        "tokens": r.tokens,
        "cost_usd": round(r.cost, 6),
        "cost_share_pct": round(r.cost / total_cost * 100, 2) if total_cost else 0.0,
        "stages_without_cost": r.stages_without_cost,
        "stages_without_tokens": r.stages_without_tokens,
        "failed_stages": r.failed_stages,
    }


def build_payload(
    stages: list[Stage],
    project: str,
    archive: Path,
    prd_dir: Path,
    worktree: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Assemble the full report payload from stage records and PRD ownership."""
    owner, evidence = derive_ownership(prd_dir)
    group_by = GROUP_BY_PRD if owner else GROUP_BY_PREFIX

    by_group: dict[str, Rollup] = collections.defaultdict(Rollup)
    by_plan: dict[str, Rollup] = collections.defaultdict(Rollup)
    plan_group: dict[str, str] = {}
    total = Rollup()

    for s in stages:
        if group_by == GROUP_BY_PRD:
            group = owner.get(s.prefix, UNATTRIBUTED)
        else:
            group = f"{s.prefix}-"
        plan_group[s.task_id] = group
        by_group[group].add(s)
        by_plan[s.task_id].add(s)
        total.add(s)

    group_order = sorted(by_group, key=lambda n: (-by_group[n].cost, n))
    plan_order = sorted(by_plan, key=lambda p: (-by_plan[p].cost, p))

    failed = [s for s in stages if s.result and s.result != "success"]
    by_class = collections.Counter(s.failure_class or "(none)" for s in failed)
    costless_by_class = collections.Counter(
        s.failure_class or "(none)" for s in failed if s.cost is None
    )
    failures_by_plan = collections.Counter(s.task_id for s in failed)

    observed_prefixes = {s.prefix for s in stages}
    unattributed_prefixes = sorted(
        p for p in observed_prefixes if owner.get(p) is None
    )

    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "project": project,
            "worktree": worktree,
            "worktrees_seen": sorted({s.worktree for s in stages}),
            "telemetry_root": str(archive),
            "prd_dir": str(prd_dir),
            "since": since,
            "window": {
                "first_stage_start": min(s.start for s in stages),
                "last_stage_start": max(s.start for s in stages),
            },
        },
        "totals": measures(total, total.cost),
        "attribution": {
            "group_by": group_by,
            "method": (
                "A plan is attributed by its slice prefix. Each prefix belongs "
                "to the PRD that cites the most slices of that prefix."
                if group_by == GROUP_BY_PRD
                else "No PRD was found, so plans group by their slice prefix."
            ),
            "unattributed_label": UNATTRIBUTED,
            "unattributed_prefixes": unattributed_prefixes,
            "prefixes": [
                {
                    "prefix": p,
                    "owner": owner[p],
                    "slices_cited_by_prd": evidence[p],
                }
                for p in sorted(evidence)
                if p in observed_prefixes
            ],
        },
        "failure_classes": [
            {"failure_class": cls, "stages": n, "costless_stages": costless_by_class[cls]}
            for cls, n in by_class.most_common()
        ],
        "worst_failing_plan": (
            {"plan": failures_by_plan.most_common(1)[0][0],
             "failed_stages": failures_by_plan.most_common(1)[0][1]}
            if failures_by_plan
            else None
        ),
        "groups": [
            {
                "group": name,
                **measures(by_group[name], total.cost),
                "plan_ids": [p for p in plan_order if plan_group[p] == name],
            }
            for name in group_order
        ],
        "plans": [
            {"plan": p, "group": plan_group[p], **measures(by_plan[p], total.cost)}
            for p in plan_order
        ],
        "stages": [
            {
                "run_id": s.run_id,
                "worktree": s.worktree,
                "plan": s.task_id,
                "group": plan_group[s.task_id],
                "stage": s.stage,
                "attempt": s.attempt,
                "result": s.result,
                "failure_class": s.failure_class,
                "start_time": s.start,
                "end_time": s.end,
                "duration_seconds": round(s.duration_s, 3),
                "tokens": s.tokens,
                "cost_usd": round(s.cost, 6) if s.cost is not None else None,
            }
            for s in sorted(stages, key=lambda s: (s.start, s.task_id, s.stage))
        ],
    }


def render_markdown(d: dict[str, Any]) -> str:
    """Render the payload as a standalone markdown report."""
    meta, tot = d["meta"], d["totals"]
    attribution = d["attribution"]
    by_prd = attribution["group_by"] == GROUP_BY_PRD
    group_label = "PRD" if by_prd else "Slice prefix"
    group_heading = "Per PRD" if by_prd else "Per slice prefix"
    lines: list[str] = []
    add = lines.append

    add(f"# AET performance report — {meta['project']}")
    add("")
    scope = meta["worktree"] or ", ".join(meta["worktrees_seen"])
    add(f"Generated {meta['generated_at']} from "
        f"`{meta['telemetry_root']}/{meta['project']}` (worktree: {scope}).")
    add(f"Grouping reads `{meta['prd_dir']}`. Regenerate with `aet performance-report`.")
    add("")

    add("## Totals")
    add("")
    add("| Measure | Value |")
    add("|---|---|")
    add(f"| Plans | {tot['plans']} |")
    add(f"| Stage sessions | {tot['stages']} |")
    add(f"| Stage time | {tot['duration_human']} |")
    add(f"| Tokens, cache reads included | {tot['tokens']:,} |")
    add(f"| Cost | ${tot['cost_usd']:,.2f} |")
    add(f"| Telemetry window | {meta['window']['first_stage_start'][:10]} to "
        f"{meta['window']['last_stage_start'][:10]} |")
    add("")

    add(f"## {group_heading}")
    add("")
    add(f"| {group_label} | Plans | Stages | Stage time | Tokens | Cost | Share |")
    add("|---|--:|--:|--:|--:|--:|--:|")
    for r in d["groups"]:
        add(f"| {r['group']} | {r['plans']} | {r['stages']} | {r['duration_human']} "
            f"| {r['tokens']:,} | ${r['cost_usd']:,.2f} | {r['cost_share_pct']:.0f}% |")
    add(f"| **Total** | **{tot['plans']}** | **{tot['stages']}** "
        f"| **{tot['duration_human']}** | **{tot['tokens']:,}** "
        f"| **${tot['cost_usd']:,.2f}** | 100% |")
    add("")

    add("## Per plan")
    add("")
    plans = {p["plan"]: p for p in d["plans"]}
    for r in d["groups"]:
        add(f"### {r['group']}")
        add("")
        add("| Plan | Stages | Stage time | Tokens | Cost |")
        add("|---|--:|--:|--:|--:|")
        for pid in r["plan_ids"]:
            p = plans[pid]
            add(f"| {pid} | {p['stages']} | {p['duration_human']} | {p['tokens']:,} "
                f"| ${p['cost_usd']:,.2f} |")
        add("")

    add("## Attribution")
    add("")
    add(attribution["method"])
    if by_prd:
        add("A PRD also cites slices it only depends on, so a plain text match")
        add("over-attributes cross-cutting work.")
        add("")
        if attribution["unattributed_prefixes"]:
            cited = ", ".join(f"`{p}-`" for p in attribution["unattributed_prefixes"])
            add(f"No PRD cites {cited}, so those plans land in "
                f"{attribution['unattributed_label']}.")
            add("")
        add("| Prefix | Owning PRD | Slices cited, by PRD |")
        add("|---|---|---|")
        for e in attribution["prefixes"]:
            cited = ", ".join(f"{n}: {c}" for n, c in e["slices_cited_by_prd"].items())
            add(f"| `{e['prefix']}-` | {e['owner']} | {cited} |")
        add("")

    add("## Data quality")
    add("")
    costless_failed = sum(f["costless_stages"] for f in d["failure_classes"])
    add(f"- Cost is absent from {tot['stages_without_cost']} of {tot['stages']} stage "
        f"sessions, and {costless_failed} of those are failed stages. A stage that "
        "fails before it reports usage contributes time but no cost, so every cost "
        "figure here is a floor.")
    gaps = [f"{r['group']} {r['stages_without_cost']}"
            for r in d["groups"] if r["stages_without_cost"]]
    if gaps:
        add("- Stages without cost, by group: " + "; ".join(gaps) + ".")
    add(f"- The archive starts {meta['window']['first_stage_start'][:10]}. Work before "
        "that date is not recorded, so anything built earlier is understated by its "
        "whole early period.")
    add("- Interactive sessions are absent. The archive holds orchestrated `aet` "
        "stage sessions only.")
    add("- Tokens include cache reads, so the count is not billable input volume. "
        "Cost is the reliable figure.")
    add(f"- Stage results: {tot['stages'] - tot['failed_stages']} success, "
        f"{tot['failed_stages']} failure.")
    add("- A retried stage appears once per attempt.")
    worst = d["worst_failing_plan"]
    if worst and worst["failed_stages"] > 1:
        add(f"- `{worst['plan']}` carries the most failures, {worst['failed_stages']} "
            "of them.")
    add("")

    if d["failure_classes"]:
        add("| Failure class | Stages | Of which costless |")
        add("|---|--:|--:|")
        for f in d["failure_classes"]:
            add(f"| {f['failure_class']} | {f['stages']} | {f['costless_stages']} |")
        add("")

    add("*AI-assisted work product — requires human review before business use.*")
    return "\n".join(lines) + "\n"
