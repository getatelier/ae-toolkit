"""Shared plan-file parsing utilities for aet-work commands."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from aet.queue import append_history  # noqa: E402

# Characters that make a plain YAML scalar invalid or ambiguous.  Values
# containing these must be quoted before PyYAML can parse them as strings.
_SCALAR_SPECIAL_RE = re.compile(r"[:>#`|%@!&*{}[\],]")

# PRD reference pattern used by plan validation and by R-17 branch derivation.
_PRD_REF_RE = re.compile(r"\b(docs/prds/[\w./\-]+\.md)\b")


def _frontmatter_body_from_text(content: str) -> str | None:
    """Return the raw text between the leading ``---`` fences of *content*, or None.

    Returns None when the text has no frontmatter or the fence is unclosed.
    """
    if not content.startswith("---"):
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[1]


def _frontmatter_body(path: Path) -> str | None:
    """Return the raw text between the leading ``---`` fences, or None.

    Returns None when the file has no frontmatter or the fence is unclosed.
    """
    return _frontmatter_body_from_text(path.read_text(errors="ignore"))


def _yaml_scalar_needs_quoting(value: str) -> bool:
    """Return True if ``value`` must be quoted to be a YAML string scalar."""
    value = value.strip()
    if not value or value == "[]":
        return False
    # Already quoted.
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return False
    # Inline flow collections are parsed by PyYAML directly.
    if (value.startswith("[") and value.endswith("]")) or (value.startswith("{") and value.endswith("}")):
        return False
    # Plain scalars cannot contain or start with these characters.
    if _SCALAR_SPECIAL_RE.search(value):
        return True
    if value[0] in "|>%":
        return True
    return False


def _normalize_frontmatter_scalar(value: str) -> str:
    """Return a YAML-safe representation of a scalar frontmatter value.

    Quotes the value when PyYAML would otherwise misinterpret it as structure.
    Unquoted values keep their original spacing so ``key: value`` remains valid.
    """
    stripped = value.strip()
    if not stripped or stripped == "[]":
        return value
    if _yaml_scalar_needs_quoting(stripped):
        escaped = stripped.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _normalize_frontmatter_body(body: str) -> str:
    """Make a hand-rolled frontmatter body valid YAML for PyYAML.

    Quotes scalar values that contain characters which would otherwise be
    misinterpreted as YAML structure.  This preserves the existing plan
    corpus (which uses Markdown backticks and unquoted colons in prose
    fields) without re-implementing a YAML parser.
    """
    lines: list[str] = []
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(raw_line)
            continue
        if stripped.startswith("- "):
            indent = raw_line[: len(raw_line) - len(raw_line.lstrip())]
            item = stripped[2:]
            lines.append(f"{indent}- {_normalize_frontmatter_scalar(item)}")
            continue
        if ":" not in stripped:
            lines.append(raw_line)
            continue
        key_part, sep, value_part = raw_line.partition(":")
        normalized = _normalize_frontmatter_scalar(value_part)
        if normalized != value_part:
            # Ensure a single space separates the colon from the quoted value.
            lines.append(f"{key_part}{sep} {normalized.lstrip()}")
        else:
            lines.append(f"{key_part}{sep}{normalized}")
    return "\n".join(lines)


def parse_frontmatter_text(content: str) -> dict[str, Any]:
    """Parse the YAML frontmatter of plan *content* using PyYAML.

    Returns an empty dict when the text has no frontmatter, the fence is
    unclosed, the YAML is malformed, or the top-level value is not a mapping.

    The ``blocked_by`` key is defaulted to an empty list when absent so the
    rest of the intake contract can rely on its presence.
    """
    body = _frontmatter_body_from_text(content)
    if body is None:
        return {}

    normalized = _normalize_frontmatter_body(body)
    try:
        data = yaml.safe_load(normalized)
    except yaml.YAMLError:
        return {}

    if not isinstance(data, dict):
        return {}

    # The hand-rolled parser treated ``blocked_by:`` (empty scalar) as an
    # empty list.  PyYAML returns None for an empty scalar, so normalize it
    # back to the contract default (covers missing key too).
    if data.get("blocked_by") is None:
        data["blocked_by"] = []

    return data


def parse_frontmatter(path: Path) -> dict[str, Any]:
    """Parse the YAML frontmatter of a plan file using PyYAML."""
    return parse_frontmatter_text(path.read_text(errors="ignore"))


def title_from_plan(path: Path) -> str:
    """Extract a plan's title from YAML frontmatter or the first H1."""
    content = path.read_text(errors="ignore")
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 2:
            match = re.search(r"^title:\s*(.+)$", parts[1], re.M)
            if match:
                return match.group(1).strip()
    match = re.search(r"^#\s+(.+)$", content, re.M)
    if match:
        return match.group(1).strip()
    return path.stem


def build_ticket_map(plan_files: list[Path]) -> dict[str, str]:
    """Build a ticket-number -> task-id map from plan titles."""
    ticket_map: dict[str, str] = {}
    for pf in plan_files:
        title = title_from_plan(pf)
        for pattern in (r"(?i)ticket\s+(\d+)", r"(?i)#\s*(\d+)"):
            match = re.search(pattern, title)
            if match:
                key = match.group(1).lstrip("0") or "0"
                ticket_map[key] = pf.stem
    return ticket_map


def stage_from_plan(path: Path) -> str | None:
    """Extract the *Stage:* footer value from a plan file.

    Body text may mention other stages (e.g. "set fods-06 footer to
    _Stage: superseded_"), so we take the last match rather than the first.
    A missing file fails open and returns ``None``.
    """
    if not path.exists():
        return None
    content = path.read_text(errors="ignore")
    matches = re.findall(r"[*_]Stage:\s*([\w-]+)[*_]", content)
    if matches:
        return matches[-1]
    return None


# Plan lifecycle terminal states. Plans that carry these in their footer or
# frontmatter ``status`` are settled and must be ignored by live-work tooling.
_TERMINAL_PLAN_STAGES = {"merged", "abandoned"}


def is_settled_plan(path: Path) -> bool:
    """Return True when a plan file represents a settled task.

    Settled-ness is read from the durable signals that survive after a plan
    file has been left in the scanned directory: a terminal ``status``
    frontmatter value or a terminal footer stage (``merged``/``abandoned``).
    """
    data = parse_frontmatter(path)
    status = data.get("status")
    if isinstance(status, str) and status in _TERMINAL_PLAN_STAGES:
        return True
    stage = stage_from_plan(path)
    if stage in _TERMINAL_PLAN_STAGES:
        return True
    return False


def references_other_plans(path: Path) -> bool:
    """Return True if the plan links to other plan files."""
    content = path.read_text(errors="ignore")
    for match in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", content):
        target = match.group(2)
        if target.startswith("docs/plans/") or target.startswith("../plans/"):
            return True
        if "/plans/" in target and target.endswith(".md"):
            return True
    return False


def has_multiple_phase_sections(path: Path) -> bool:
    """Return True if the plan contains more than one Phase heading."""
    content = path.read_text(errors="ignore")
    return len(re.findall(r"(?m)^#{1,3}\s+Phase", content)) > 1


def has_legacy_dependency_section(path: Path) -> bool:
    """Return True if the plan body contains a legacy dependency heading."""
    content = path.read_text(errors="ignore")
    return bool(re.search(r"(?mi)^##\s+(Blocked by|Dependencies)\b", content))


def has_explicit_frontmatter_blocked_by(path: Path) -> bool:
    """Return True when the frontmatter explicitly declares a blocked_by key."""
    body = _frontmatter_body(path)
    if body is None:
        return False
    return bool(re.search(r"^blocked_by\s*:", body, re.M))


def validate_size(path: Path) -> tuple[bool, str | None, bool]:
    """Check whether a plan carries the ATOMIC OVERSIZED assertion.

    Returns (ok, reason, has_oversized_warning).

    Plan size is measured after implementation, not gated at intake, so this
    function no longer rejects on task-list length.  The warning signal is
    preserved for downstream skills (e.g. ``aet-implement``) that refuse to
    start on plans marked atomic-oversized without explicit approval.
    """
    has_warning = "\u26a0\ufe0f ATOMIC OVERSIZED" in path.read_text(errors="ignore")
    return True, None, has_warning


def most_recent_prd(prds_dir: Path) -> Path | None:
    """Return the most recently modified PRD file, or None."""
    if not prds_dir.exists():
        return None
    prds = sorted(prds_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return prds[0] if prds else None


def most_recent_plan(plans_dir: Path) -> Path | None:
    """Return the most recently modified plan file, or None."""
    if not plans_dir.exists():
        return None
    plans = sorted(plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return plans[0] if plans else None


def prd_path_from_text(text: str, repo_root: str | Path | None = None) -> Path | None:
    """Return the PRD file referenced in *text*, or None.

    The reference is matched by ``docs/prds/<name>.md``.  When *repo_root* is
    supplied the returned path is absolute; otherwise it is relative to the
    current working directory.
    """
    match = _PRD_REF_RE.search(text)
    if not match:
        return None
    path = Path(match.group(1))
    if repo_root is not None:
        if not path.is_absolute():
            path = Path(repo_root) / path
    return path


def prd_path_for_plan(plan_path: Path, repo_root: str | Path | None = None) -> Path | None:
    """Return the PRD file referenced from a plan file's context, or None.

    Returns ``None`` when the plan file is missing so callers that already
    have a portable task spec (R-19) are not blocked by the absence of the
    rendered plan file.
    """
    path = Path(plan_path)
    if repo_root is not None and not path.is_absolute():
        path = Path(repo_root) / path
    try:
        text = path.read_text(errors="ignore")
    except FileNotFoundError:
        return None
    return prd_path_from_text(text, repo_root=repo_root)


# Frontmatter keys that travel with the task record so the plan file is not
# required at run time (R-19).  Any key not in this set stays in the rendered
# plan body and is not duplicated in the record.
_CARRIED_FM_KEYS = (
    "id",
    "size",
    "pipeline",
    "security_review",
    "docs_sync",
    "workflow",
    "blocked_by",
    "work_class",
)


def _extract_body_and_title_from_text(content: str, stem: str) -> tuple[str, str]:
    """Return ``(body, title)`` from plan *content*.

    The body is everything between the closing frontmatter fence and the final
    stage/footer separator (if any).  The title is taken from the first H1, and
    falls back to *stem* when the plan has no heading.
    """
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2]

    title = stem
    title_match = re.search(r"^#\s+(.+)$", content, re.M)
    if title_match:
        title = title_match.group(1).strip()

    # Drop the footer separator and any stage footer that follows it.
    body = re.split(r"\n---\s*\n", content, maxsplit=1)[0]
    # Also drop the title line itself from the body; render re-adds it.
    body = re.sub(r"^#\s+.+\n?", "", body, count=1, flags=re.M)
    return body.strip(), title


def _extract_body_and_title(path: Path) -> tuple[str | None, str]:
    """Return ``(body, title)`` from a plan file, or ``(None, stem)`` on error."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None, path.stem
    return _extract_body_and_title_from_text(content, path.stem)


def _extract_task_items(body: str) -> list[str]:
    """Return the task list items from a plan body.

    Matches a ``## Task List`` section and returns every list item line until
    the next ``## `` heading.  Returns an empty list when no task list section
    exists.
    """
    match = re.search(r"(?m)^##\s+Task List\s*\n(.*?)(?=\n##\s+|\Z)", body, re.DOTALL)
    if not match:
        return []
    items: list[str] = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ", "1. ", "2. ", "3. ", "4. ", "5. ", "6. ", "7. ", "8. ", "9. ", "0. ")):
            items.append(stripped)
    return items


def extract_plan_spec_from_text(content: str, stem: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the portable spec for a task record from plan *content*.

    The spec carries the frontmatter keys required for routing, the plan title,
    the task list, and the rest of the body so the working plan can be rendered
    in a worktree that never had the original file (R-19).

    This is the text-level entry point: the backfill migration recovers plans
    from git blobs, which never touch the filesystem.
    """
    if data is None:
        data = parse_frontmatter_text(content)

    body, title = _extract_body_and_title_from_text(content, stem)

    frontmatter = {k: data[k] for k in _CARRIED_FM_KEYS if k in data}
    spec: dict[str, Any] = {
        "frontmatter": frontmatter,
        "title": title,
        "body": body,
        "tasks": _extract_task_items(body),
    }
    return spec


def extract_plan_spec(path: Path, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Build the portable spec for a task record from a plan file.

    Returns ``None`` when the file cannot be read.
    """
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    return extract_plan_spec_from_text(content, path.stem, data)


def render_plan(path: Path, task: dict[str, Any]) -> bool:
    """Write a working plan file in ``path`` from the task's spec.

    Returns ``True`` when a spec was present and the file was written.  The
    caller is responsible for ensuring the parent directory exists.
    """
    spec = task.get("spec")
    if not isinstance(spec, dict):
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = spec.get("frontmatter", {})
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.extend(["---", "", f"# {spec.get('title', task.get('id', path.stem))}"])

    body = spec.get("body", "").strip()
    if body:
        lines.extend(["", body])

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def task_routing_data(task: dict[str, Any], repo_root: str | Path | None = None) -> dict[str, Any]:
    """Return the frontmatter used for routing from a task record.

    Prefers the portable spec; falls back to parsing the plan file on disk for
    records created before R-19.
    """
    spec = task.get("spec")
    if isinstance(spec, dict):
        return spec.get("frontmatter", {})

    plan_file = task.get("plan_file")
    if plan_file:
        path = Path(plan_file)
        if not path.is_absolute() and repo_root is not None:
            path = Path(repo_root) / path
        if path.exists():
            return parse_frontmatter(path)
    return {}


def task_plan_path(task: dict[str, Any], repo_root: str | Path | None = None) -> Path | None:
    """Return the canonical plan path for a task, or None when no id is set."""
    task_id = task.get("id")
    if not task_id:
        return None
    root = Path(repo_root) if repo_root else Path.cwd()
    return root / "docs" / "plans" / f"{task_id}.md"


def new_task_from_plan(
    path: Path,
    live_tasks: list[dict[str, Any]] | None = None,
    settled_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Create a fresh queue task dict from a plan file using the frontmatter contract.

    ``live_tasks`` is the current open-work board and ``settled_ids`` the tasks
    that have left it by assertion (ADR-059 tombstones).

    A blocker counts as satisfied only on positive evidence: it is on the board
    in a terminal state, or it carries a tombstone. A blocker that is simply
    absent is *not* evidence of completion — it is most often a blocker that
    has not been added to the sprint yet, and treating absence as done is what
    let a task dispatch in parallel with its own blocker. Absence therefore
    fails closed (ADR-011 decision 4): unknown means pending.
    """
    data = parse_frontmatter(path)
    blocked_by = data.get("blocked_by", [])
    if not isinstance(blocked_by, list):
        blocked_by = []
    blocked_by = [b for b in blocked_by if isinstance(b, str)]

    live_by_id = {t["id"]: t for t in (live_tasks or []) if t.get("id")}
    settled = settled_ids or set()
    terminal = {"merged", "abandoned"}

    def _is_satisfied(blocker: str) -> bool:
        if blocker in settled:
            return True
        if blocker in live_by_id:
            return live_by_id[blocker].get("state") in terminal
        return False  # absent: no evidence either way, so it stays pending

    pending = [b for b in blocked_by if not _is_satisfied(b)]

    state = "ready" if not pending else "blocked"
    work_class = data.get("work_class")
    if isinstance(work_class, str) and work_class.lower() in {"trivial", "normal", "critical"}:
        work_class = work_class.lower()
    else:
        work_class = "unclassified"

    task: dict[str, Any] = {
        "id": data.get("id", path.stem),
        "title": title_from_plan(path),
        "plan_file": str(path),
        "blocked_by": blocked_by,
        "blocks": [],
        "state": state,
        "pending_blockers": len(pending),
        "merge_commit": None,
        "integration_branch": None,
        "completed_at": None,
        "merged_at": None,
        "worktree": None,
        "branch": None,
        "work_class": work_class,
        "spec": extract_plan_spec(path, data),
    }
    append_history(task, None, state, "sync")
    return task


INERT_STATES = {"planned", "ready", "blocked"}


def is_task_inert(task: dict[str, Any]) -> tuple[bool, str | None]:
    """Check if a task record is inert (pre-run, terminal-free, no execution state).

    A task is inert when it has not yet run: its state is one of ``planned``,
    ``ready``, or ``blocked``, and it has no ``branch``, ``worktree``,
    ``merge_commit``, or ``integration_branch`` assigned.

    Returns ``(True, None)`` when inert, or ``(False, blocking_field)`` naming
    the field that prevents re-ingestion (R-3, R-7).
    """
    state = task.get("state")
    if state not in INERT_STATES:
        return False, "state"
    if task.get("branch") is not None:
        return False, "branch"
    if task.get("worktree") is not None:
        return False, "worktree"
    if task.get("merge_commit") is not None:
        return False, "merge_commit"
    if task.get("integration_branch") is not None:
        return False, "integration_branch"
    return True, None



is_inert = is_task_inert


# Frontmatter keys that route gated pipeline stages at plan time. Each key is
# optional (a missing key defaults to ``required`` at run time); when present
# it must be ``required`` or ``skipped``, and ``skipped`` must carry a
# non-empty ``<key>_reason`` recording the plan-time judgment.
ROUTING_GATE_KEYS = ("security_review", "docs_sync", "verify")

# Map from verdict kind to the plan-frontmatter routing key that controls it.
VERDICT_GATE_KEYS: dict[str, str] = {
    "cso": "security_review",
    "sync-docs": "docs_sync",
    "verify": "verify",
}


def required_verdict_kinds(plan_data: dict[str, Any]) -> list[str]:
    """Return the required verdict kinds for a task from its parsed frontmatter.

    ``qa`` and ``review`` are always required. A gated kind is required unless
    its routing key is explicitly set to ``skipped``, or its gate defaults to
    critical-only (e.g. verify) and the work class is not critical.
    A missing routing key defaults to required — the standing fail-safe.
    """
    required = ["qa", "review"]
    for kind, key in VERDICT_GATE_KEYS.items():
        if key == "verify":
            if plan_data.get(key) == "required" or (
                key not in plan_data and plan_data.get("work_class") == "critical"
            ):
                required.append(kind)
        else:
            if plan_data.get(key) != "skipped":
                required.append(kind)
    return required


def _routing_key_error(data: dict[str, Any]) -> str | None:
    """Validate the gate-routing keys of one plan's frontmatter.

    Returns an error reason, or None when the keys satisfy the contract.
    """
    for key in ROUTING_GATE_KEYS:
        value = data.get(key)
        if value is None:
            continue
        if value not in ("required", "skipped"):
            return f"invalid {key}: {value} (must be required or skipped)"
        if value == "skipped":
            reason = data.get(f"{key}_reason")
            if not isinstance(reason, str) or not reason.strip():
                return f"{key}_reason is required when {key} is skipped"
    return None


def intake_validation_errors(
    plan_files: list[Path],
    limit_to: set[Path] | None = None,
    extra_known_ids: set[str] | None = None,
) -> list[tuple[Path, str]]:
    """Validate plan files for intake and return a list of fatal errors.

    Checks the frontmatter contract (id, size, blocked_by, work_class,
    gate-routing keys), cross-plan blocker references, multi-unit plan markers,
    atomic-complexity limits, and legacy dependency sections that would silently
    drop blockers.

    By default every file is validated. When ``limit_to`` is provided, only files
    in that set produce validation errors, but every file is still parsed so that
    cross-plan blocker references and duplicate-id detection remain accurate.

    ``extra_known_ids`` allows callers (e.g. ``aet-work add``) to include
    already-settled task ids that are valid blocker references even though the
    plan file may no longer be present.
    """
    parsed: dict[Path, dict[str, Any]] = {}
    ids: list[str] = []
    for pf in plan_files:
        data = parse_frontmatter(pf)
        parsed[pf] = data
        task_id = data.get("id")
        if task_id:
            ids.append(task_id)

    duplicate_ids = {task_id for task_id in ids if ids.count(task_id) > 1}
    known_ids = set(ids) | (extra_known_ids or set())

    errors: list[tuple[Path, str]] = []
    for pf in plan_files:
        data = parsed[pf]
        task_id = data.get("id")

        if limit_to is not None and pf not in limit_to:
            continue

        if not task_id:
            errors.append((pf, "missing id"))
            continue
        if task_id in duplicate_ids:
            errors.append((pf, f"duplicate id: {task_id}"))
            continue
        if task_id != pf.stem:
            errors.append((pf, f"id mismatch: {task_id} != {pf.stem}"))
            continue

        size = data.get("size")
        if size not in {"S", "M", "L"}:
            errors.append((pf, f"invalid size: {size}"))
            continue

        work_class = data.get("work_class")
        if work_class is not None and (
            not isinstance(work_class, str) or work_class.lower() not in {"trivial", "normal", "critical"}
        ):
            errors.append((pf, f"work_class must be one of trivial|normal|critical (got '{work_class}')"))
            continue

        routing_error = _routing_key_error(data)
        if routing_error:
            errors.append((pf, routing_error))
            continue

        blocked_by = data.get("blocked_by", [])
        if not isinstance(blocked_by, list) or not all(isinstance(b, str) for b in blocked_by):
            errors.append((pf, "blocked_by must be a list of ids"))
            continue

        unknown = [b for b in blocked_by if b not in known_ids]
        if unknown:
            errors.append((pf, f"unknown blockers: {', '.join(unknown)}"))
            continue

        if has_legacy_dependency_section(pf) and not has_explicit_frontmatter_blocked_by(pf):
            errors.append((pf, "legacy dependency section found; move blocked_by to frontmatter"))
            continue

        if references_other_plans(pf):
            errors.append((pf, "references other plan files"))
            continue

        if has_multiple_phase_sections(pf):
            errors.append((pf, "contains multiple Phase sections"))
            continue

        ok, reason, has_warning = validate_size(pf)
        if not ok and not has_warning:
            errors.append((pf, f"exceeds complexity limit ({reason})"))
            continue

    return errors


def resolve_plan_arg(plan: str, plans_dir: Path = Path("docs/plans")) -> str:
    """Resolve a plan argument that may be a path or a bare task id.

    A value ending in ``.md`` is treated as a plan path and returned as-is.
    Anything else is treated as a task id and resolved to
    ``<plans_dir>/active/<id>.md`` or ``<plans_dir>/<id>.md``. Raises
    ``ValueError`` when the id does not resolve, so the error names both
    interpretations.
    """
    if plan.lower().endswith(".md"):
        return plan
    candidate_active = plans_dir / "active" / f"{plan}.md"
    if candidate_active.is_file():
        return str(candidate_active)
    candidate_root = plans_dir / f"{plan}.md"
    if candidate_root.is_file():
        return str(candidate_root)
    raise ValueError(
        f"Plan not found: '{plan}' is not a .md path and {candidate_active} "
        f"(or legacy {candidate_root}) does not exist. Pass the full plan path."
    )
