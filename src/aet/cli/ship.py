#!/usr/bin/env python3
"""aet-ship — Pre-merge gate, PR creation, and post-merge closure for AE Toolkit tasks.

Usage:
  aet ship <task_id>                  Run the gate, then open a PR.
  aet ship gate <task_id>             Run the pre-merge gate (steps 1-9).
  aet ship open <task_id>             Run the gate and open a PR.
  aet ship open-epic [<branch>]       Run the gate and open a PR for an epic branch.
  aet ship merge <task_id> [--branch <target>]
                                      Run the gate, detect conflicts against the target branch,
                                      merge directly into it, and record closure. Target defaults to
                                      the resolved trunk branch.
  aet ship split <task_id> --message <msg> --paths <path>...
                                      Split the PR range into logical commits.
  aet ship close <task_id>            Record post-merge closure (task id from queue task).
  aet ship close <task_id> [queue_file]
                                      Record post-merge closure (explicit queue).
  aet ship record-merge <task_id> [queue_file]
                                      Hidden alias for ``close``.

``gate``, ``open``, ``merge``, ``split``, and the default command resolve the task id to a
live task record (or a sealed merged record) in the work queue. Plan file paths are no longer
accepted; use ``aet sprint add`` to intake a plan.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, NamedTuple, Optional

import typer
from typer.core import TyperGroup

_SCRIPT_DIR = Path(__file__).resolve().parent
from aet import gate, plan_parser  # noqa: E402
from aet.backends.factory import resolve_config  # noqa: E402
from aet.branch_ref import resolve_trunk_branch  # noqa: E402
from aet.closure import archive_plan_file  # noqa: E402
from aet.ledger import Ledger, resolve_ledger_path  # noqa: E402

# Load aet-state as a module so we can reuse its merge-resolution and
# queue-mutation logic rather than duplicating it.
_AET_STATE_PY = Path(__file__).resolve().parent / "aet_state.py"
_spec = importlib.util.spec_from_loader(
    "aet_state",
    importlib.machinery.SourceFileLoader("aet_state", str(_AET_STATE_PY)),
)
aet_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aet_state)

# Named exit codes for the merge-verification surface (t2r-02).
EXIT_VERIFY_NO_MATCH = 10
EXIT_VERIFY_AMBIGUOUS = 11
EXIT_DELETE_BEFORE_RECORD = 12


class StackInfo(NamedTuple):
    """Resolved stack position for a branch.

    ``trunk_ref`` is the remote trunk ref (e.g. ``origin/main``).
    ``base_ref`` is the PR base: the parent branch for stacked PRs, or the trunk
    ref for independent branches.
    ``parent`` is the local parent branch name when stacked, otherwise ``None``.
    ``position`` is a human-readable stack position (e.g. "PR 2 of 2").
    """

    trunk_ref: str
    base_ref: str
    parent: Optional[str]
    position: Optional[str]


class GateResult:
    """Structured result of the pre-merge gate for reuse by ``ship open``."""

    def __init__(
        self,
        ok: bool,
        pr_base: str,
        rebased: bool,
        scope_audit: list[str],
        dry_run: bool,
        message: str = "",
        stack: Optional[StackInfo] = None,
    ):
        self.ok = ok
        self.pr_base = pr_base
        self.rebased = rebased
        self.scope_audit = scope_audit
        self.dry_run = dry_run
        self.message = message
        self.stack = stack


def _resolve_feature_branch(task_id: str, queue: str = ".agents/aet-queue") -> Optional[str]:
    """Resolve a task's feature branch by name.

    The orchestrator names each task's branch after its task id (it sets
    ``qt["branch"] = task_id`` when recording a task in-progress), so the merge
    source is the ``task_id`` ref — never whatever branch happens to be checked
    out. Prefer the local branch; fall back to the remote-tracking ref. Return
    ``None`` when neither exists so callers fail closed instead of merging a
    branch into itself and recording a merge that never happened.
    """
    candidates: list[str] = []
    task_branch = _resolve_task_branch(task_id, queue)
    if task_branch:
        candidates.extend([task_branch, f"origin/{task_branch}"])
    candidates.extend([task_id, f"origin/{task_id}"])

    seen: set[str] = set()
    for ref in candidates:
        if ref in seen:
            continue
        seen.add(ref)
        if _run_git("rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0:
            return ref
    return None


def _normalize_close_args(
    task_id: str,
    plan: Optional[str],
    queue: str,
) -> tuple[str, Optional[str], str]:
    """Resolve ``aet ship close`` argument forms to (task_id, plan, queue).

    ``close`` accepts a task id only; plan file paths are no longer supported
    (R-3). The optional second and third positionals are retained for parser
    compatibility but any ``.md`` path or unexpected extra positional is
    rejected with a message naming ``aet sprint add`` as the intake entry point.
    """

    def _is_plan_path(value: str) -> bool:
        return value.lower().endswith(".md")

    if _is_plan_path(task_id) or (plan is not None and _is_plan_path(plan)):
        raise ValueError(
            "Plan file paths are no longer accepted by `aet ship`. "
            "Use `aet sprint add <task-id>` to put the task on the board, "
            "then pass the task id."
        )

    if plan:
        raise ValueError(
            "Unexpected second positional argument. `aet ship close` accepts "
            "a task id only; plan paths are no longer supported. Use "
            "`aet sprint add` to intake the plan, then pass the task id."
        )

    return task_id, None, queue


def _normalize_verify_args(
    task_id: str,
    plan: Optional[str],
    queue: str,
) -> tuple[str, Optional[str], str]:
    """Resolve flexible ``aet ship verify`` argument forms.

    Supported forms:
      - ``verify <plan_file>`` — derive task id from plan frontmatter.
      - ``verify <plan_file> <queue_file>`` — derive task id; explicit queue.
      - ``verify <task_id>`` — plan is read from the queue task's ``plan_file``.
      - ``verify <task_id> <queue_file>`` — explicit task id and queue.
    """

    def _is_plan_path(value: str) -> bool:
        return value.lower().endswith(".md")

    if _is_plan_path(task_id):
        resolved_plan = task_id
        resolved_task_id = plan_parser.parse_frontmatter(Path(resolved_plan)).get("id") or Path(resolved_plan).stem
        resolved_queue = plan if plan else queue
        return resolved_task_id, resolved_plan, resolved_queue

    return task_id, plan, queue


def _resolve_ship_task(args: argparse.Namespace) -> int | None:
    """Resolve a ship command's ``plan`` argument to a live task record.

    Rejects ``.md`` paths, reports settled tasks, and fails closed when no
    record or no spec exists. On success, sets ``args.task_id`` and
    ``args.spec`` and returns ``None``. Otherwise returns the exit code the
    caller should use.
    """
    plan_arg = args.plan
    if plan_arg.lower().endswith(".md"):
        return _fail(
            "Plan file paths are no longer accepted by `aet ship`. "
            "Use `aet sprint add <task-id>` to put the task on the board, "
            "then pass the task id."
        )

    queue = getattr(args, "queue", ".agents/aet-queue")
    task, sealed = aet_state.resolve_task_record(plan_arg, queue)
    if sealed:
        print(f"Recorded merge for {plan_arg}: {sealed.get('merge_commit')} ({sealed.get('merge_strategy')})")
        return 0
    if task is None:
        return _fail(f"Task not found: {plan_arg}")

    spec = task.get("spec")
    if not isinstance(spec, dict):
        return _fail(f"Task {plan_arg} has no spec. Run `aet sprint add` to intake the plan.")

    args.task_id = task.get("id", plan_arg)
    args.spec = spec
    return None


def _load_task_record(task_id: str, queue: str) -> Optional[dict]:
    """Return the task record for *task_id* in *queue*, or None."""
    try:
        backend = aet_state.make_backend(queue)
        backend.fetch()
        data = backend.load()
        return aet_state.find_task(data["queue"], task_id)
    except Exception:
        return None


def _resolve_task_branch(task_id: str, queue: str) -> Optional[str]:
    """Return the branch recorded for *task_id* in *queue*, or None."""
    task = _load_task_record(task_id, queue)
    return task.get("branch") if task else None


def _resolve_task_record(task_id: str, queue: str) -> Optional[dict]:
    """Return the queued task record for *task_id*, or None."""
    try:
        backend = aet_state.make_backend(queue)
        backend.fetch()
        data = backend.load()
        return aet_state.find_task(data["queue"], task_id)
    except Exception:
        return None


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify that a branch has merged without mutating queue or ledger state.

    Runs the resolution ladder (ancestry, GitHub CLI, optional diff fallback)
    and prints the resolved merge commit, strategy, and match kind. Exits with
    a named code when the merge cannot be determined or is ambiguous.
    """
    try:
        task_id, plan, queue = _normalize_verify_args(
            args.task_id,
            getattr(args, "plan_or_queue", None),
            getattr(args, "queue", ".agents/aet-queue"),
        )
    except ValueError as exc:
        return _fail(str(exc))

    task_record = _load_task_record(task_id, queue)
    branch = getattr(args, "branch", None)
    if not branch:
        branch = task_record.get("branch") if task_record else None
    if not branch:
        return _fail(f"Cannot verify {task_id}: no branch recorded and none provided.")

    target_branch = getattr(args, "target_branch", None)
    trunk_branch = aet_state._resolve_trunk(queue)
    if target_branch:
        integration_branch = target_branch
    else:
        task = _resolve_task_record(task_id, queue)
        if task is not None:
            integration_branch = aet_state._resolve_integration_for_task(queue, task).ref
        else:
            integration_branch = aet_state._resolve_integration(queue)

    merge_commit, merge_strategy, match_kind = aet_state.resolve_merge_commit(
        branch,
        cwd=".",
        trunk_branch=trunk_branch,
        target_branch=integration_branch,
        use_diff_fallback=args.squash_fallback,
        base_commit=task_record.get("base_commit") if task_record else None,
    )

    if not merge_commit:
        if match_kind == "ambiguous":
            print(
                f"Merge verification failed for {task_id}: ambiguous result.",
                file=sys.stderr,
            )
            return EXIT_VERIFY_AMBIGUOUS
        print(
            f"Merge verification failed for {task_id}: no match found on origin/{integration_branch}.",
            file=sys.stderr,
        )
        return EXIT_VERIFY_NO_MATCH

    kind_display = f" ({match_kind})" if match_kind else ""
    print(f"{merge_commit} {merge_strategy}{kind_display}")
    return 0


def cmd_ship(args):
    """Run the post-merge closure for a task or epic."""
    try:
        task_id, plan, queue = _normalize_close_args(
            args.task_id,
            getattr(args, "plan", None),
            getattr(args, "queue", ".agents/aet-queue"),
        )
    except ValueError as exc:
        return _fail(str(exc))

    target_branch = getattr(args, "target_branch", None)
    branch = getattr(args, "branch", None)
    delete_branch = getattr(args, "delete_branch", False)

    # No-self-merge guard: closing a branch against itself is never valid.
    if target_branch and branch and target_branch == branch:
        return _fail(f"Self-merge refused: branch '{branch}' cannot be closed against target '{target_branch}'.")

    # Capture the branch to delete before the closure transaction, because the
    # queue entry (and its branch field) may be sealed/removed on success.
    branch_to_delete = None
    if delete_branch:
        branch_to_delete = branch or _resolve_task_branch(task_id, queue)
        if not branch_to_delete:
            return _fail(f"Cannot delete branch for {task_id}: no branch recorded and none provided.")

    ns = aet_state.argparse.Namespace(
        command="record-merge",
        task_id=task_id,
        queue=queue,
        dry_run=args.dry_run,
        plan=plan,
        branch=branch,
        merge_commit=getattr(args, "merge_commit", None),
        target_branch=target_branch,
    )
    rc = aet_state.cmd_record_merge(ns)
    if rc != 0:
        return EXIT_DELETE_BEFORE_RECORD if delete_branch else rc

    if not args.dry_run:
        archive_plan_file(task_id)

    if delete_branch:
        if args.dry_run:
            print(f"[dry-run] Would delete remote branch origin/{branch_to_delete}")
            print(f"[dry-run] Would delete local branch {branch_to_delete}")
        else:
            _run_git("push", "origin", "--delete", branch_to_delete, check=False)
            _run_git("branch", "-D", branch_to_delete, check=False)

    return 0


def cmd_default(args: argparse.Namespace) -> int:
    """Run the gate and, if it passes, open a PR for a task."""
    rc = _resolve_ship_task(args)
    if rc is not None:
        return rc

    print(f"Running aet ship for {args.task_id}")
    gate_rc = cmd_gate(args)
    if gate_rc != 0:
        return gate_rc
    return cmd_open(args)


def _fail(message: str) -> int:
    print(f"⛔ {message}", file=sys.stderr)
    return 1


def _run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command and return the completed process."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def _has_origin() -> bool:
    """Return True when an ``origin`` remote is configured."""
    result = _run_git("remote", check=False)
    return result.returncode == 0 and "origin" in result.stdout.split()


def _fetch_origin() -> None:
    """Fetch ``origin``, skipping when no such remote exists.

    ``_run_git`` raises on a non-zero exit, and ``git fetch origin`` fails in a
    repository with no remote, so an unguarded call took the whole ``ship``
    family down on a local-only project: every subcommand runs the pre-merge
    gate, and the gate fetches first. The guard mirrors the backend's, which
    made the same read best-effort for the same reason
    (``GitRefsBackend.fetch``). ``check=False`` is deliberately not the fix: it
    would also swallow a real fetch failure on a project that does have a
    remote.
    """
    if not _has_origin():
        return
    _run_git("fetch", "origin")


def _resolve_trunk_ref() -> str:
    """Resolve the remote trunk ref (e.g. ``origin/main``).

    Uses the same precedence as ``aet-state``: config ``trunk_branch`` →
    ``git symbolic-ref refs/remotes/origin/HEAD`` → ``main`` fallback.
    """
    repo_root = _run_git("rev-parse", "--show-toplevel").stdout.strip()
    config = resolve_config(".agents/aet-config.json", repo_root=repo_root)
    trunk = resolve_trunk_branch(repo_root, config)
    return f"origin/{trunk.ref}"


def _determine_pr_base(feature_branch: Optional[str] = None) -> StackInfo:
    """Resolve the PR base ref and stack position.

    Returns a :class:`StackInfo` where ``base_ref`` is the trunk for independent
    branches or the nearest named ancestor for stacked branches.
    """
    trunk_ref = _resolve_trunk_ref()
    target_ref = feature_branch or "HEAD"
    base_res = _run_git("merge-base", target_ref, trunk_ref, check=False)
    if base_res.returncode != 0:
        return StackInfo(trunk_ref=trunk_ref, base_ref=trunk_ref, parent=None, position=None)
    merge_base = base_res.stdout.strip()
    trunk_sha = _run_git("rev-parse", trunk_ref).stdout.strip()
    if merge_base == trunk_sha:
        return StackInfo(trunk_ref=trunk_ref, base_ref=trunk_ref, parent=None, position=None)

    log = _run_git(
        "log", "--oneline", "--decorate", "--ancestry-path", f"{merge_base}..{target_ref}", check=False
    ).stdout
    parent: Optional[str] = None
    ancestor_count = 0
    local_target = target_ref.removeprefix("origin/")
    for line in log.splitlines():
        match = re.match(r"^[0-9a-f]+ \((.*?)\) ", line)
        if not match:
            continue
        refs = [r.strip() for r in match.group(1).split(",")]
        local_refs: list[str] = []
        for r in refs:
            if r.startswith("HEAD -> "):
                continue  # current branch — the one being shipped, never its own parent
            r = r.strip()
            if r in ("HEAD",) or r.startswith("origin/") or r.startswith("tag:"):
                continue
            if r == local_target or r == target_ref:
                continue
            local_refs.append(r)
        if local_refs:
            ancestor_count += 1
            if parent is None:
                parent = local_refs[0]

    if parent is None:
        return StackInfo(trunk_ref=trunk_ref, base_ref=trunk_ref, parent=None, position=None)

    position = f"PR {ancestor_count + 1} of {ancestor_count + 1} (parent: {parent})"
    return StackInfo(trunk_ref=trunk_ref, base_ref=parent, parent=parent, position=position)


def _rebase_independent_branch(
    stack: StackInfo,
    dry_run: bool,
    feature_branch: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> tuple[bool, str, bool]:
    """Rebase independent branches onto the trunk; return (ok, message, rebased)."""
    if stack.base_ref != stack.trunk_ref:
        return True, "Stacked branch; keeping parent base.", False
    target_ref = feature_branch or "HEAD"
    git_args = ["-C", str(workspace)] if workspace else []
    merge_base_res = _run_git(*git_args, "merge-base", target_ref, stack.trunk_ref, check=False)
    if merge_base_res.returncode != 0:
        return False, f"⛔ Could not determine merge base between {target_ref} and {stack.trunk_ref}.", False
    merge_base = merge_base_res.stdout.strip()
    trunk_sha = _run_git(*git_args, "rev-parse", stack.trunk_ref).stdout.strip()
    if merge_base == trunk_sha:
        return True, f"Already based on {stack.trunk_ref}.", False
    branch = feature_branch or _run_git(*git_args, "branch", "--show-current").stdout.strip()
    if dry_run:
        return (
            True,
            f"Would rebase --onto {stack.trunk_ref} {merge_base} {branch}",
            False,
        )
    result = _run_git(*git_args, "rebase", "--onto", stack.trunk_ref, merge_base, branch, check=False)
    if result.returncode != 0:
        return (
            False,
            (
                f"⛔ Rebase onto {stack.trunk_ref} produced conflicts.\n"
                "   Resolve them manually, then run aet-ship again."
            ),
            False,
        )
    return True, f"Rebased onto {stack.trunk_ref}.", True


def _is_working_tree_clean(workspace: Optional[Path] = None) -> bool:
    git_args = ["-C", str(workspace)] if workspace else []
    result = _run_git(*git_args, "status", "--short", check=False)
    return result.returncode == 0 and not result.stdout.strip()


def _create_gate_worktree(branch: str) -> Path:
    """Create a temporary worktree for *branch* and return its path."""
    repo_root = Path(_run_git("rev-parse", "--show-toplevel").stdout.strip())
    sanitized = branch.replace("/", "-")
    worktree_dir = repo_root / ".worktrees" / f".gate-{sanitized}-{os.getpid()}"
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    result = _run_git(
        "worktree",
        "add",
        "--checkout",
        str(worktree_dir),
        branch,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not create worktree for {branch}: {result.stderr.strip()}")
    return worktree_dir


def _run_gate(args: argparse.Namespace) -> GateResult:
    """Execute gate checks and return a structured result for reuse."""
    spec = getattr(args, "spec", None) or {}
    task_id = getattr(args, "task_id", getattr(args, "plan", None))
    feature_branch = _resolve_feature_branch(task_id) if task_id else None

    if not feature_branch:
        return GateResult(
            ok=False,
            pr_base=getattr(args, "base", "") or "",
            rebased=False,
            scope_audit=[],
            dry_run=args.dry_run,
            message=(
                f"Cannot resolve a feature branch for task {task_id!r}: "
                f"neither {task_id!r} nor origin/{task_id} exists."
                if task_id
                else "Cannot resolve a feature branch for gate validation."
            ),
            stack=None,
        )

    workspace = _find_target_worktree(feature_branch)
    created_temp_worktree = False
    if workspace is None:
        try:
            workspace = _create_gate_worktree(feature_branch)
            created_temp_worktree = True
        except RuntimeError as exc:
            return GateResult(
                ok=False,
                pr_base=getattr(args, "base", "") or "",
                rebased=False,
                scope_audit=[],
                dry_run=args.dry_run,
                message=f"Cannot resolve a workspace for branch {feature_branch!r}: {exc}",
                stack=None,
            )

    try:
        _fetch_origin()
        trunk_ref = _resolve_trunk_ref()
        if args.base:
            stack = StackInfo(trunk_ref=trunk_ref, base_ref=args.base, parent=None, position=None)
            pr_base = args.base
        else:
            stack = _determine_pr_base(feature_branch=feature_branch)
            pr_base = stack.base_ref

        ok, message, rebased = _rebase_independent_branch(
            stack, args.dry_run, feature_branch=feature_branch, workspace=workspace
        )
        if not ok:
            return GateResult(
                ok=False,
                pr_base=pr_base,
                rebased=False,
                scope_audit=[],
                dry_run=args.dry_run,
                message=message,
                stack=stack,
            )

        if not _is_working_tree_clean(workspace=workspace):
            return GateResult(
                ok=False,
                pr_base=pr_base,
                rebased=rebased,
                scope_audit=[],
                dry_run=args.dry_run,
                message="Working tree is dirty. Stash, commit, or abort before shipping.",
                stack=stack,
            )

        test_cmd = os.environ.get("AET_SHIP_TEST_CMD", "make validate")
        test_result = subprocess.run(shlex.split(test_cmd), cwd=str(workspace), capture_output=True, text=True)
        if test_result.returncode != 0:
            return GateResult(
                ok=False,
                pr_base=pr_base,
                rebased=rebased,
                scope_audit=[],
                dry_run=args.dry_run,
                message=f"Test suite failed:\n{test_result.stdout}\n{test_result.stderr}",
                stack=stack,
            )

        coverage_cmd = os.environ.get("AET_SHIP_COVERAGE_CMD")
        if coverage_cmd:
            subprocess.run(shlex.split(coverage_cmd), cwd=str(workspace), capture_output=True, text=True)

        repo_root = _run_git("rev-parse", "--show-toplevel").stdout.strip()
        plan_fm = spec.get("frontmatter", {}) if isinstance(spec, dict) else {}
        # The verdict is the evidence (ADR-070). The previous check read a
        # working-tree markdown file that no producer wrote, so this gate could only
        # be satisfied out of band
        # (docs/bugs/20260828-verify-evidence-has-three-contracts.md).
        #
        # Only `verify` is checked here. The other kinds are enforced in-run by
        # their own stage gates, at the moment they are written; re-checking them at
        # ship would make merging depend on a per-machine reports archive that is
        # not part of the repository. `verify` is checked because a critical task can
        # reach `awaiting_merge` without having walked the stage that produces it,
        # and this is the last gate before trunk.
        req_evidence = gate.required_evidence(repo_root, plan_fm)
        verify_stages = [stage_name for stage_name, evidence_kind in req_evidence if evidence_kind == "verify"]
        if verify_stages:
            passed, detail = gate.verdict_status(args.task_id, "verify", repo_root)
            if not passed:
                return GateResult(
                    ok=False,
                    pr_base=pr_base,
                    rebased=rebased,
                    scope_audit=[],
                    dry_run=args.dry_run,
                    message=(
                        "⛔ Pipeline paused at aet-ship.\n"
                        f"Workflow stage '{verify_stages[0]}' requires a passing "
                        f"verify verdict — {detail}.\n"
                        "aet-verify writes it: `aet gate submit --stage verify "
                        "--verdict pass --summary <one-line>`."
                    ),
                    stack=stack,
                )

        flagged = _scope_audit(spec, pr_base, feature_branch=feature_branch, workspace=workspace)
        return GateResult(
            ok=True,
            pr_base=pr_base,
            rebased=rebased,
            scope_audit=flagged,
            dry_run=args.dry_run,
            message=f"Pre-merge gate passed for {feature_branch}.",
            stack=stack,
        )
    finally:
        if created_temp_worktree and workspace:
            _remove_worktree(workspace)


def cmd_gate(args: argparse.Namespace) -> int:
    """Run the pre-merge gate for a task."""
    rc = _resolve_ship_task(args)
    if rc is not None:
        return rc

    print(f"Running pre-merge gate for {args.task_id}")
    result = _run_gate(args)
    if result.ok:
        print(f"✅ {result.message}")
        return 0
    return _fail(result.message)


def _work_class_from_spec(spec: dict[str, Any]) -> str:
    """Return the work class from the task record, defaulting to normal."""
    work_class = spec.get("frontmatter", {}).get("work_class")
    if work_class:
        return str(work_class).strip().lower()
    return "normal"


def _scope_audit(
    spec: dict[str, Any],
    pr_base: str,
    feature_branch: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> list[str]:
    """Return a list of out-of-scope files changed against pr_base."""
    target_ref = feature_branch or "HEAD"
    git_args = ["-C", str(workspace)] if workspace else []
    result = _run_git(*git_args, "diff", f"{pr_base}..{target_ref}", "--name-only", check=False)
    if result.returncode != 0:
        return []
    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    associated_prd = _extract_prd_link(spec)
    flagged: list[str] = []
    for path in changed:
        if path.startswith("docs/prds/") and path.endswith(".md"):
            if associated_prd and path != associated_prd:
                flagged.append(path)
    return flagged


def _unchecked_tasks(spec: dict[str, Any]) -> list[str]:
    """Return the text of unchecked tasks from the task record."""
    unchecked: list[str] = []
    for item in spec.get("tasks", []):
        stripped = item.strip()
        if stripped.startswith("- [ ]") or stripped.startswith("* [ ]"):
            unchecked.append(stripped[5:].strip())
    return unchecked


def _print_stage_skips(stage: str) -> None:
    """Print stage-aware skip messages for review and CSO skills."""
    skip_both = {"synced", "secure"}
    if stage in skip_both:
        print(f"   ⏭️ Skipping aet-review: plan stage is already {stage}.")
        print(f"   ⏭️ Skipping aet-cso: plan stage is already {stage}.")
        return
    if stage == "reviewed":
        print("   ⏭️ Skipping aet-review: plan stage is already reviewed.")
        return
    # qa-complete or earlier: run review, then conditional CSO.


def _plan_task_count(spec: dict[str, Any]) -> int:
    """Count checked/unchecked tasks from the task record."""
    count = 0
    for item in spec.get("tasks", []):
        stripped = item.strip()
        if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
            count += 1
    return count


def _commit_count(
    pr_base: str,
    feature_branch: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> int:
    """Return the number of commits between pr_base and feature_branch."""
    target_ref = feature_branch or "HEAD"
    git_args = ["-C", str(workspace)] if workspace else []
    result = _run_git(*git_args, "rev-list", "--count", f"{pr_base}..{target_ref}", check=False)
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _commit_subjects(
    pr_base: str,
    feature_branch: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> list[str]:
    """Return commit subjects in the pr_base..feature_branch range."""
    target_ref = feature_branch or "HEAD"
    git_args = ["-C", str(workspace)] if workspace else []
    result = _run_git(*git_args, "log", f"{pr_base}..{target_ref}", "--pretty=format:%s", check=False)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_monolithic_commit(
    pr_base: str,
    spec: dict[str, Any],
    feature_branch: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> bool:
    """True when one commit covers the whole range while the plan has >1 task."""
    count = _commit_count(pr_base, feature_branch=feature_branch, workspace=workspace)
    return count == 1 and _plan_task_count(spec) > 1


def _extract_prd_link(spec: dict[str, Any]) -> str | None:
    """Return the PRD path referenced in the task record's Source line, if any."""
    body = spec.get("body", "")
    for match in re.finditer(r"Source:\s*`?([^`\n]+?)`?", body):
        candidate = match.group(1).strip()
        if candidate.startswith("docs/prds/") and candidate.endswith(".md"):
            return candidate
    return None


def _generate_changelog_entry(subjects: list[str], spec: dict[str, Any]) -> str:
    """Build a PR/commit-trail changelog entry; never writes CHANGELOG.md."""
    plan_id = spec.get("frontmatter", {}).get("id")
    title = spec.get("title", plan_id or "unknown")
    lines = ["## CHANGELOG entry", ""]
    lines.append(f"**{plan_id}**: {title}.")
    lines.append("")
    if subjects:
        lines.append("Commits in this PR:")
        for subject in subjects:
            lines.append(f"- {subject}")
    else:
        lines.append("(no commits in the PR range)")
    lines.append("")
    return "\n".join(lines)


def _build_pr_body(
    spec: dict[str, Any],
    stack: StackInfo,
    scope_audit: list[str],
    changelog_entry: str,
) -> str:
    """Assemble the PR body with links, scope audit, and stacked-PR warnings."""
    parts: list[str] = []
    prd = _extract_prd_link(spec)
    if prd:
        parts.append(f"PRD: [{prd}]({prd})")
    parts.append("")
    parts.append(changelog_entry)

    if scope_audit:
        parts.append("## Scope audit")
        parts.append("")
        parts.append("Files changed outside this task's expected scope:")
        for path in scope_audit:
            parts.append(f"- {path}")
        parts.append("")

    if stack.parent is not None:
        trunk_name = stack.trunk_ref.removeprefix("origin/")
        parts.append("## Stack")
        parts.append("")
        parts.append(f"- Position: {stack.position}")
        parts.append(f"- Parent: `{stack.parent}`")
        parts.append(f"- Trunk: `{stack.trunk_ref}`")
        parts.append("")
        parts.append(f"⚠️ STACKED PR — base is `{stack.base_ref}`, not `{trunk_name}`.")
        parts.append("")
        parts.append(f"After `{stack.base_ref}` merges to `{trunk_name}`, run:")
        parts.append(f"  git rebase {trunk_name} && git push --force-with-lease && gh pr edit --base {trunk_name}")
        parts.append("before merging this PR.")
        parts.append("")

    return "\n".join(parts)


def _push_branch(
    rebased: bool,
    dry_run: bool,
    feature_branch: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> tuple[bool, str]:
    """Push the current branch to a same-named remote branch.

    Worktree branches are often tracked against ``origin/main``, so a bare
    ``git push`` is rejected. Always push ``HEAD:<branch>`` explicitly.
    """
    git_args = ["-C", str(workspace)] if workspace else []
    if feature_branch:
        branch = feature_branch.removeprefix("origin/")
    else:
        branch_result = _run_git(*git_args, "branch", "--show-current", check=False)
        branch = branch_result.stdout.strip()
    if not branch:
        return False, "Cannot push: HEAD is detached."

    push_spec = f"HEAD:{branch}" if workspace else f"{branch}:{branch}"
    if rebased:
        cmd = ["git", *git_args, "push", "--force-with-lease", "origin", push_spec]
    else:
        cmd = ["git", *git_args, "push", "-u", "origin", push_spec]
    if dry_run:
        return True, f"Would run: {' '.join(cmd)}"
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stdout + result.stderr


def _create_pr(pr_base: str, title: str, body: str, dry_run: bool) -> tuple[bool, str]:
    """Create a GitHub PR using ``gh pr create``."""
    # ``gh`` expects a branch name, not a remote tracking ref.
    gh_base = pr_base.removeprefix("origin/")
    if dry_run:
        return True, f"Would create PR against `{gh_base}` with title: {title}"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as body_file:
        body_file.write(body)
        body_path = body_file.name
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--base",
                gh_base,
                "--title",
                title,
                "--body-file",
                body_path,
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0, result.stdout + result.stderr
    finally:
        os.unlink(body_path)


def _check_release_guard(
    pr_base: str,
    feature_branch: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> str | None:
    """Block ``chore(release)`` commits and VERSION changes on feature branches."""
    for subject in _commit_subjects(pr_base, feature_branch=feature_branch, workspace=workspace):
        if re.match(r"^chore\(release\)", subject):
            return f"Release guard: commit '{subject}' is a chore(release) on a feature branch."
    target_ref = feature_branch or "HEAD"
    git_args = ["-C", str(workspace)] if workspace else []
    diff = _run_git(*git_args, "diff", f"{pr_base}..{target_ref}", "--name-only", check=False)
    if diff.returncode == 0:
        for line in diff.stdout.splitlines():
            if line.strip() == "VERSION":
                return "Release guard: VERSION file changed on a feature branch."
    return None


def cmd_open(args: argparse.Namespace) -> int:
    """Run the gate and open a PR for a task."""
    rc = _resolve_ship_task(args)
    if rc is not None:
        return rc

    spec = args.spec
    task_id = args.task_id
    feature_branch = _resolve_feature_branch(task_id)
    print(f"Running aet ship open for {task_id}")

    result = _run_gate(args)
    if not result.ok:
        return _fail(f"Gate failed: {result.message}")
    print(f"   {result.message}")

    guard_error = _check_release_guard(result.pr_base, feature_branch=feature_branch)
    if guard_error:
        return _fail(guard_error)

    if _is_monolithic_commit(result.pr_base, spec, feature_branch=feature_branch):
        return _fail(
            "Monolithic commit detected: one commit spans the entire PR range "
            "while the plan lists multiple tasks.\n"
            "Run `aet ship split` to split it into logical pieces before opening the PR."
        )

    changelog_entry = _generate_changelog_entry(_commit_subjects(result.pr_base, feature_branch=feature_branch), spec)

    print("Pushing branch...")
    ok, output = _push_branch(result.rebased, args.dry_run, feature_branch=feature_branch)
    if not ok:
        return _fail(f"Push failed:\n{output}")
    if output.strip():
        print(f"   {output.strip()}")

    plan_id = spec.get("frontmatter", {}).get("id", args.task_id)
    title = f"{plan_id}: {spec.get('title', plan_id)}"
    stack = result.stack or StackInfo(
        trunk_ref=_resolve_trunk_ref(),
        base_ref=result.pr_base,
        parent=None,
        position=None,
    )
    body = _build_pr_body(spec, stack, result.scope_audit, changelog_entry)

    print("Creating PR...")
    ok, output = _create_pr(result.pr_base, title, body, args.dry_run)
    if not ok:
        return _fail(f"PR creation failed:\n{output}")
    if output.strip():
        print(f"   {output.strip()}")

    pr_url = output.strip().splitlines()[0].strip() if output.strip() else ""

    if result.stack and result.stack.parent is not None:
        trunk_name = result.stack.trunk_ref.removeprefix("origin/")
        print(
            f"⚠️  STACKED PR: this PR targets {result.stack.base_ref}, not {trunk_name}.\n"
            f"     After {result.stack.base_ref} merges, rebase onto {trunk_name} "
            "and update the base before merging."
        )
        if pr_url:
            Ledger(resolve_ledger_path()).write_event(
                source="aet-ship",
                task=plan_id,
                kind="cut",
                ref=pr_url,
                ref_kind="pr",
                payload={
                    "pr_base": result.stack.base_ref,
                    "stacked": True,
                    "parent": result.stack.parent,
                },
            )

    print("✅ aet ship open complete.")
    return 0


def _find_existing_pr(branch: str) -> Optional[str]:
    """Look up an existing PR for the branch using ``gh pr list --head <branch>``."""
    try:
        res = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--json", "url"],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and res.stdout.strip():
            out = res.stdout.strip()
            try:
                data = json.loads(out)
                if isinstance(data, list) and len(data) > 0:
                    if isinstance(data[0], dict) and "url" in data[0]:
                        return data[0]["url"]
                    if isinstance(data[0], str) and data[0].startswith("http"):
                        return data[0]
            except json.JSONDecodeError:
                pass
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("http://") or line.startswith("https://"):
                    return line
    except Exception:
        pass
    return None


def cmd_open_epic(args: argparse.Namespace) -> int:
    """Run the gate and open a PR for an epic branch."""
    queue = getattr(args, "queue", ".agents/aet-queue")
    branch_arg = getattr(args, "branch", None)

    epic = None
    try:
        backend = aet_state.make_backend(queue)
        backend.fetch()
        epic = backend.read_epic()
    except Exception:
        pass

    branch = branch_arg or (epic.get("branch") if epic else None)
    if not branch:
        return _fail(
            "No active epic declaration found and no branch specified. "
            "Use `aet epic set <branch>` to declare one, or pass a branch name."
        )

    print(f"Running aet ship open-epic for {branch}")

    gate_args = argparse.Namespace(
        plan=branch,
        task_id=branch,
        base=getattr(args, "base", None),
        dry_run=args.dry_run,
        spec={},
        queue=queue,
    )
    result = _run_gate(gate_args)
    if not result.ok:
        return _fail(f"Gate failed: {result.message}")
    print(f"   {result.message}")

    guard_error = _check_release_guard(result.pr_base, feature_branch=branch)
    if guard_error:
        return _fail(guard_error)

    print("Pushing branch...")
    ok, output = _push_branch(result.rebased, args.dry_run, feature_branch=branch)
    if not ok:
        return _fail(f"Push failed:\n{output}")
    if output.strip():
        print(f"   {output.strip()}")

    existing_pr = _find_existing_pr(branch)
    if existing_pr:
        print(existing_pr)
        return 0

    declared_title = None
    declared_body_file = None
    if epic and epic.get("branch") == branch:
        declared_title = epic.get("title")
        declared_body_file = epic.get("body_file")

    title = declared_title if declared_title else branch

    if declared_body_file:
        repo_root = _run_git("rev-parse", "--show-toplevel").stdout.strip()
        bf_path = Path(declared_body_file)
        if not bf_path.is_absolute():
            bf_path = Path(repo_root) / bf_path
        if bf_path.is_file():
            body = bf_path.read_text(encoding="utf-8")
        else:
            body = f"## {title}\n"
    else:
        subjects = _commit_subjects(result.pr_base, feature_branch=branch)
        spec = {"frontmatter": {"id": branch}, "title": title}
        body = _generate_changelog_entry(subjects, spec)

    print("Creating PR...")
    ok, output = _create_pr(result.pr_base, title, body, args.dry_run)
    if not ok:
        return _fail(f"PR creation failed:\n{output}")
    if output.strip():
        print(f"   {output.strip()}")

    pr_url = output.strip().splitlines()[0].strip() if output.strip() else ""

    if pr_url and not args.dry_run:
        try:
            Ledger(resolve_ledger_path()).write_event(
                source="aet-ship",
                task=branch,
                kind="cut",
                ref=pr_url,
                ref_kind="pr",
                payload={
                    "pr_base": result.pr_base,
                    "branch": branch,
                    "epic": True,
                },
            )
        except Exception:
            pass

    print("✅ aet ship open-epic complete.")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    """Split the PR range into caller-supplied commit groups.

    Refuses on a dirty tree or empty range, prints the original HEAD SHA for
    recovery, runs ``git reset --soft <pr_base>``, then commits each
    ``--message``/``--paths`` group in order. The fail-closed post-condition
    requires that the resulting tree matches the original HEAD tree.
    """
    rc = _resolve_ship_task(args)
    if rc is not None:
        return rc

    messages = args.message or []
    path_groups = args.paths or []
    if len(messages) != len(path_groups):
        return _fail(
            f"Mismatched --message/--paths groups: {len(messages)} message(s) and {len(path_groups)} path group(s)."
        )
    if not messages:
        return _fail("At least one --message/--paths group is required.")

    if not _is_working_tree_clean():
        return _fail("Working tree is dirty. Stash, commit, or abort before splitting.")

    if args.base:
        pr_base = args.base
    else:
        stack = _determine_pr_base()
        pr_base = stack.base_ref

    # `split` is the last _commit_count caller reading ambient HEAD. It cannot
    # simply be handed the resolved branch: the reset below rewrites the checkout
    # it runs in, so the range counted and the branch rewritten have to be the
    # same one. Resolve the branch, refuse when the checkout is not on it, and
    # count against it.
    feature_branch = _resolve_feature_branch(args.task_id)
    if feature_branch:
        checked_out = _run_git("rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
        if checked_out != feature_branch.removeprefix("origin/"):
            return _fail(
                f"`aet ship split` rewrites history in the current checkout, which is on "
                f"'{checked_out}', not task {args.task_id}'s branch "
                f"'{feature_branch.removeprefix('origin/')}'. Check that branch out, or run "
                f"from its worktree, and retry."
            )

    commit_count = _commit_count(pr_base, feature_branch=feature_branch)
    if commit_count == 0:
        return _fail(f"No commits between {pr_base} and {feature_branch or 'HEAD'}.")

    original_head = _run_git("rev-parse", "HEAD").stdout.strip()
    print(f"Original HEAD: {original_head}")
    print(f"Recovery command: git reset --soft {original_head}")

    if args.dry_run:
        print(f"[dry-run] Would reset --soft {pr_base}")
        for message, paths in zip(messages, path_groups):
            print(f"[dry-run] Would add {paths} and commit with message: {message}")
        return 0

    _run_git("reset", "--soft", pr_base)

    for message, paths in zip(messages, path_groups):
        # Unstage everything so each group is committed independently.
        _run_git("reset")
        _run_git("add", *paths)
        _run_git("commit", "-m", message)

    diff = _run_git("diff", f"{original_head}..HEAD", check=False)
    if diff.returncode != 0 or diff.stdout.strip():
        print(
            "⛔ Split post-condition failed: the resulting tree does not match the original HEAD tree.",
            file=sys.stderr,
        )
        status = _run_git("status", check=False)
        print(status.stdout, file=sys.stderr)
        print(status.stderr, file=sys.stderr)
        print(f"Recover with: git reset --soft {original_head}", file=sys.stderr)
        return 1

    print("✅ aet ship split complete.")
    return 0


def _has_merge_conflicts(
    target_branch: str,
    feature_branch: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> tuple[bool, str]:
    """Return (has_conflicts, message) for merging feature_branch into origin/<target_branch>."""
    target_ref = f"origin/{target_branch}"
    source_ref = feature_branch or "HEAD"
    git_args = ["-C", str(workspace)] if workspace else []
    base_result = _run_git(*git_args, "merge-base", source_ref, target_ref, check=False)
    if base_result.returncode != 0:
        return True, f"Could not find merge base between {source_ref} and {target_ref}."
    merge_base = base_result.stdout.strip()
    tree_result = _run_git(*git_args, "merge-tree", merge_base, source_ref, target_ref, check=False)
    if tree_result.returncode != 0:
        return True, f"Merge-tree failed for {target_ref}: {tree_result.stderr}"
    if any(line.startswith("<<<<<<< ") for line in tree_result.stdout.splitlines()):
        return (
            True,
            f"Merging {source_ref} into {target_ref} would produce conflicts. "
            "Rebase onto the target branch or resolve the conflicts first.",
        )
    return False, ""


def _find_target_worktree(branch: str) -> Optional[Path]:
    """Return the path of an existing worktree for *branch*, or None."""
    result = _run_git("worktree", "list", "--porcelain", check=False)
    if result.returncode != 0:
        return None
    current_path: Optional[Path] = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line[len("worktree ") :])
        elif line.startswith("branch ") and current_path is not None:
            ref = line[len("branch ") :]
            if ref == f"refs/heads/{branch}":
                return current_path
    return None


def _create_temp_worktree(target_branch: str) -> Path:
    """Create a temporary worktree for origin/<target_branch> and return its path."""
    repo_root = Path(_run_git("rev-parse", "--show-toplevel").stdout.strip())
    worktree_dir = repo_root / ".worktrees" / f".merge-{target_branch}-{os.getpid()}"
    result = _run_git(
        "worktree",
        "add",
        "--checkout",
        str(worktree_dir),
        f"origin/{target_branch}",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not create worktree for {target_branch}: {result.stderr}")
    return worktree_dir


def _remove_worktree(path: Path) -> None:
    """Remove a temporary worktree, ignoring errors."""
    _run_git("worktree", "remove", "--force", str(path), check=False)


def _merge_into_target(target_branch: str, feature_branch: str, dry_run: bool) -> tuple[bool, str, Optional[str]]:
    """Merge *feature_branch* into *target_branch* and push.

    Returns (ok, message, merge_commit). *merge_commit* is None on failure or
    dry-run. Existing worktrees for the target branch are reused; otherwise a
    temporary worktree is created and removed.
    """
    target_ref = f"origin/{target_branch}"
    worktree = _find_target_worktree(target_branch)
    created = False
    if worktree is None:
        if dry_run:
            return (
                True,
                f"Would create a worktree for {target_ref}, merge {feature_branch} into "
                f"{target_branch}, and push {target_branch}.",
                None,
            )
        try:
            worktree = _create_temp_worktree(target_branch)
            created = True
        except RuntimeError as exc:
            return False, str(exc), None

    try:
        if dry_run:
            return (
                True,
                f"Would merge {feature_branch} into {target_branch} and push {target_branch}.",
                None,
            )

        checkout_result = _run_git("-C", str(worktree), "checkout", target_branch, check=False)
        if checkout_result.returncode != 0:
            return False, f"Could not checkout {target_branch}: {checkout_result.stderr}", None

        pull_result = _run_git("-C", str(worktree), "pull", "origin", target_branch, check=False)
        if pull_result.returncode != 0:
            return False, f"Could not pull {target_ref}: {pull_result.stderr}", None

        merge_message = f"Merge {feature_branch} into {target_branch}"
        merge_result = _run_git(
            "-C",
            str(worktree),
            "merge",
            "--no-ff",
            "-m",
            merge_message,
            feature_branch,
            check=False,
        )
        if merge_result.returncode != 0:
            _run_git("-C", str(worktree), "merge", "--abort", check=False)
            return (
                False,
                f"Merge into {target_branch} failed:\n{merge_result.stdout}\n{merge_result.stderr}",
                None,
            )

        sha_result = _run_git("-C", str(worktree), "rev-parse", "HEAD", check=False)
        if sha_result.returncode != 0:
            return False, f"Could not read merge commit SHA: {sha_result.stderr}", None
        merge_commit = sha_result.stdout.strip()

        push_result = _run_git("-C", str(worktree), "push", "origin", target_branch, check=False)
        if push_result.returncode != 0:
            return (
                False,
                f"Push of {target_branch} failed:\n{push_result.stdout}\n{push_result.stderr}",
                None,
            )

        # Fail-closed post-condition: the feature branch must be an ancestor of the
        # target after the merge. Catches silent no-op merges (e.g. an already-merged
        # or misresolved source) that would otherwise report success while leaving the
        # branch's commits behind.
        ancestry = _run_git(
            "-C",
            str(worktree),
            "merge-base",
            "--is-ancestor",
            feature_branch,
            target_branch,
            check=False,
        )
        if ancestry.returncode != 0:
            return (
                False,
                f"Post-merge verification failed: {feature_branch} is not an ancestor "
                f"of {target_branch} after the merge. The branch was not incorporated; "
                "refusing to report success.",
                None,
            )

        return (
            True,
            f"Merged {feature_branch} into {target_branch} ({merge_commit}).",
            merge_commit,
        )
    finally:
        if created:
            _remove_worktree(worktree)


def cmd_merge(args: argparse.Namespace) -> int:
    """Run the gate, detect conflicts, merge directly into a target branch, and close."""
    rc = _resolve_ship_task(args)
    if rc is not None:
        return rc

    spec = args.spec
    trunk_ref = _resolve_trunk_ref()
    target_branch = args.branch or trunk_ref.removeprefix("origin/")
    task_id = args.task_id
    feature_branch = _resolve_feature_branch(task_id)
    if not feature_branch:
        return _fail(
            f"Cannot resolve a feature branch for task {task_id!r}: neither "
            f"{task_id!r} nor origin/{task_id} exists. Refusing to record a merge "
            "that did not happen."
        )
    if feature_branch == target_branch:
        return _fail(
            f"Refusing to merge {feature_branch!r} into itself: the resolved feature "
            f"branch equals the target branch ({target_branch!r})."
        )

    print(f"Running aet ship merge for {task_id} into {target_branch}")

    # The gate should treat the target branch as the merge base so tests and
    # checks run against the same integration point we will merge into.
    explicit_base = bool(getattr(args, "base", None))
    args.base = f"origin/{target_branch}"
    result = _run_gate(args)
    if not result.ok:
        return _fail(f"Gate failed: {result.message}")
    print(f"   {result.message}")

    # Stacked merge guard: if detection found a parent that is not the trunk and
    # the user asked to merge into the trunk without explicitly overriding the
    # base, refuse rather than silently merge a stacked branch into trunk.
    if (
        not explicit_base
        and result.stack
        and result.stack.parent is not None
        and result.stack.base_ref != trunk_ref
        and f"origin/{target_branch}" == trunk_ref
    ):
        return _fail(
            f"Stacked branch detected: merge into `{result.stack.base_ref}` or rebase onto `{trunk_ref}` first."
        )

    guard_error = _check_release_guard(result.pr_base, feature_branch=feature_branch)
    if guard_error:
        return _fail(guard_error)

    if _is_monolithic_commit(result.pr_base, spec, feature_branch=feature_branch):
        return _fail(
            "Monolithic commit detected: one commit spans the entire merge range "
            "while the plan lists multiple tasks.\n"
            "Run `aet ship split` to split it into logical pieces before merging."
        )

    print(f"Checking for merge conflicts against origin/{target_branch}...")
    has_conflicts, conflict_msg = _has_merge_conflicts(target_branch, feature_branch=feature_branch)
    if has_conflicts:
        return _fail(conflict_msg)
    print("   No conflicts detected.")

    print(f"Merging {feature_branch} into {target_branch}...")
    ok, msg, merge_commit = _merge_into_target(target_branch, feature_branch, args.dry_run)
    if not ok:
        return _fail(msg)
    print(f"   {msg}")

    if args.dry_run:
        print("✅ aet ship merge complete (dry-run).")
        return 0

    rc = aet_state.cmd_record_merge(
        argparse.Namespace(
            command="record-merge",
            task_id=task_id,
            queue=".agents/aet-queue",
            plan=None,
            dry_run=False,
            branch=task_id,
            merge_commit=merge_commit,
            target_branch=target_branch,
        )
    )
    if rc != 0:
        return _fail("Merge succeeded, but recording closure failed. Run `aet ship close` manually to finish.")

    archive_plan_file(task_id)

    print("✅ aet ship merge complete.")
    return 0


def _add_close_args(parser: argparse.ArgumentParser) -> None:
    """Add the post-merge closure arguments to *parser*."""
    parser.add_argument(
        "task_id",
        help="Task ID to close (use `aet sprint add` to intake a plan).",
    )
    parser.add_argument(
        "plan",
        nargs="?",
        default=None,
        help="Deprecated and ignored: plan paths are no longer accepted (R-3).",
    )
    parser.add_argument(
        "queue",
        nargs="?",
        default=".agents/aet-queue",
        help="Path to the queue anchor.",
    )
    parser.add_argument(
        "--branch",
        help="Branch name to use for merge verification. Overrides the task's branch field.",
    )
    parser.add_argument(
        "--merge-commit",
        help="Merge commit SHA to record directly. Must be an ancestor of the resolved trunk branch.",
    )
    parser.add_argument(
        "--target-branch",
        help="Target branch the source branch merged into (default: configured integration branch). "
        "Use 'main' when closing an epic whose integration branch merged to trunk.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )
    parser.add_argument(
        "--delete-branch",
        action="store_true",
        help="After successful closure, delete the remote and local feature branch.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aet ship",
        description="Pre-merge gate, PR creation, and post-merge closure for AE Toolkit tasks.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gate_parser = sub.add_parser(
        "gate",
        help="Run the pre-merge validation gate.",
    )
    gate_parser.add_argument(
        "plan",
        help="Task id of the plan to ship (use `aet sprint add` to intake a plan).",
    )
    gate_parser.add_argument(
        "--base",
        help="Override the PR base branch/ref (default: resolved trunk or stacked parent).",
    )
    gate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )

    open_parser = sub.add_parser(
        "open",
        help="Run the gate and open a PR for the plan.",
    )
    open_parser.add_argument(
        "plan",
        help="Task id of the plan to ship (use `aet sprint add` to intake a plan).",
    )
    open_parser.add_argument(
        "--base",
        help="Override the PR base branch/ref (default: resolved trunk or stacked parent).",
    )
    open_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )

    open_epic_parser = sub.add_parser(
        "open-epic",
        help="Run the pre-merge gate and open a PR for an epic branch.",
    )
    open_epic_parser.add_argument(
        "branch",
        nargs="?",
        default=None,
        help="Integration branch to open PR for (default: active epic declaration).",
    )
    open_epic_parser.add_argument(
        "--base",
        help="Override the PR base branch/ref (default: resolved trunk).",
    )
    open_epic_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )

    merge_parser = sub.add_parser(
        "merge",
        help="Run the gate, detect conflicts, merge directly into a target branch, and close.",
    )
    merge_parser.add_argument(
        "plan",
        help="Task id of the plan to ship (use `aet sprint add` to intake a plan).",
    )
    merge_parser.add_argument(
        "--branch",
        default=None,
        help="Target branch to merge into (default: resolved trunk branch).",
    )
    merge_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )

    split_parser = sub.add_parser(
        "split",
        help="Split the PR range into caller-supplied commit groups.",
    )
    split_parser.add_argument(
        "plan",
        help="Task id of the plan to ship (use `aet sprint add` to intake a plan).",
    )
    split_parser.add_argument(
        "--base",
        help="Override the PR base branch/ref (default: resolved trunk or stacked parent).",
    )
    split_parser.add_argument(
        "--message",
        "-m",
        action="append",
        help="Commit message for one group. Repeat for each group.",
    )
    split_parser.add_argument(
        "--paths",
        action="append",
        nargs="+",
        help="Paths for one group. Repeat for each group, after its --message.",
    )
    split_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )

    verify_parser = sub.add_parser(
        "verify",
        help="Verify a branch has merged without mutating state.",
    )
    verify_parser.add_argument(
        "task_id",
        help="Task ID to verify.",
    )
    verify_parser.add_argument(
        "plan_or_queue",
        nargs="?",
        default=None,
        help="Plan path (when first arg is a task ID) or queue path (when first arg is a plan).",
    )
    verify_parser.add_argument(
        "queue",
        nargs="?",
        default=".agents/aet-queue",
        help="Path to the queue anchor.",
    )
    verify_parser.add_argument(
        "--squash-fallback",
        action="store_true",
        help="Enable diff-based squash-merge fallback when ancestry and gh fail.",
    )
    verify_parser.add_argument(
        "--branch",
        help="Branch name to verify. Overrides the task's branch field.",
    )
    verify_parser.add_argument(
        "--target-branch",
        help="Target branch to verify the merge against (default: configured integration branch).",
    )

    close_parser = sub.add_parser(
        "close",
        help="Record post-merge closure for a task.",
    )
    _add_close_args(close_parser)

    # Hidden alias kept for backward compatibility during the transition.
    record_merge_parser = sub.add_parser(
        "record-merge",
        help=argparse.SUPPRESS,
    )
    _add_close_args(record_merge_parser)

    # Default behavior when the first positional argument is a plan file.
    default_parser = sub.add_parser(
        "default",
        help=argparse.SUPPRESS,
    )
    default_parser.add_argument(
        "plan",
        help="Task id of the plan to ship (use `aet sprint add` to intake a plan).",
    )
    default_parser.add_argument(
        "--base",
        help="Override the PR base branch/ref (default: resolved trunk or stacked parent).",
    )
    default_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )

    return parser


_KNOWN_SUBCOMMANDS = {"gate", "open", "open-epic", "merge", "split", "verify", "close", "record-merge"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments.

    A bare ``aet ship <task_id>`` is treated as the default subcommand, which
    runs the gate and then opens a PR. Explicit subcommands are dispatched
    unchanged.
    """
    argv = list(argv or sys.argv[1:])
    if not argv:
        parser = build_parser()
        parser.print_help(sys.stderr)
        parser.exit(2)
    if argv[0] not in _KNOWN_SUBCOMMANDS and argv[0] not in ("--help", "-h"):
        argv.insert(0, "default")
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    if args.command == "gate":
        return cmd_gate(args)
    if args.command == "open":
        return cmd_open(args)
    if args.command == "open-epic":
        return cmd_open_epic(args)
    if args.command == "merge":
        return cmd_merge(args)
    if args.command == "split":
        return cmd_split(args)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command in ("close", "record-merge"):
        return cmd_ship(args)
    if args.command == "default":
        return cmd_default(args)
    return _fail(f"Unknown command: {args.command}")


class _ShipGroup(TyperGroup):
    """Click group that routes bare ``ship <plan>`` to a hidden default command.

    A callback with a positional ``plan`` argument cannot coexist with
    subcommands because Click consumes the first token for the callback before
    checking for a subcommand name. Inserting a hidden ``default`` command when
    the first positional is not a known subcommand preserves the legacy argparse
    routing exactly.
    """

    default_command_name = "default"

    def resolve_command(self, ctx, args):
        if args and not args[0].startswith("-"):
            if args[0] not in self.commands:
                args = [self.default_command_name, *args]
        return super().resolve_command(ctx, args)


app = typer.Typer(
    name="ship",
    help="Pre-merge gate, PR creation, and post-merge closure for AE Toolkit tasks.",
    cls=_ShipGroup,
)


@app.command(name="default", hidden=True)
def ship_default(
    plan: str = typer.Argument(
        ...,
        help="Task id of the plan to ship (use `aet sprint add` to intake a plan).",
    ),
    base: Optional[str] = typer.Option(
        None,
        "--base",
        help="Override the PR base branch/ref (default: resolved trunk or stacked parent).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without making changes.",
    ),
) -> None:
    """Run the gate and, if it passes, open a PR (default behavior)."""
    rc = cmd_default(argparse.Namespace(plan=plan, base=base, dry_run=dry_run))
    raise typer.Exit(rc)


@app.command(name="gate")
def ship_gate(
    plan: str = typer.Argument(
        ...,
        help="Task id of the plan to ship (use `aet sprint add` to intake a plan).",
    ),
    base: Optional[str] = typer.Option(
        None,
        "--base",
        help="Override the PR base branch/ref (default: resolved trunk or stacked parent).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without making changes.",
    ),
) -> None:
    """Run the pre-merge validation gate."""
    rc = cmd_gate(argparse.Namespace(plan=plan, base=base, dry_run=dry_run))
    raise typer.Exit(rc)


@app.command(name="open")
def ship_open(
    plan: str = typer.Argument(
        ...,
        help="Task id of the plan to ship (use `aet sprint add` to intake a plan).",
    ),
    base: Optional[str] = typer.Option(
        None,
        "--base",
        help="Override the PR base branch/ref (default: resolved trunk or stacked parent).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without making changes.",
    ),
) -> None:
    """Run the gate and open a PR for the plan."""
    rc = cmd_open(argparse.Namespace(plan=plan, base=base, dry_run=dry_run))
    raise typer.Exit(rc)


@app.command(name="open-epic")
def ship_open_epic(
    branch: Optional[str] = typer.Argument(
        None,
        help="Integration branch to open PR for (default: active epic declaration).",
    ),
    base: Optional[str] = typer.Option(
        None,
        "--base",
        help="Override the PR base branch/ref (default: resolved trunk).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without making changes.",
    ),
) -> None:
    """Run the gate and open a PR for an epic branch."""
    rc = cmd_open_epic(argparse.Namespace(branch=branch, base=base, dry_run=dry_run))
    raise typer.Exit(rc)


@app.command(name="merge")
def ship_merge(
    plan: str = typer.Argument(
        ...,
        help="Task id of the plan to ship (use `aet sprint add` to intake a plan).",
    ),
    branch: Optional[str] = typer.Option(
        None,
        "--branch",
        help="Target branch to merge into (default: resolved trunk branch).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without making changes.",
    ),
) -> None:
    """Run the gate, detect conflicts, merge directly into a target branch, and close."""
    rc = cmd_merge(argparse.Namespace(plan=plan, branch=branch, dry_run=dry_run))
    raise typer.Exit(rc)


@app.command(name="split")
def ship_split(
    plan: str = typer.Argument(
        ...,
        help="Task id of the plan to ship (use `aet sprint add` to intake a plan).",
    ),
    base: Optional[str] = typer.Option(
        None,
        "--base",
        help="Override the PR base branch/ref (default: resolved trunk or stacked parent).",
    ),
    message: Optional[list[str]] = typer.Option(
        None,
        "--message",
        "-m",
        help="Commit message for one group. Repeat for each group.",
    ),
    paths: Optional[list[str]] = typer.Option(
        None,
        "--paths",
        help="Comma-separated paths for one group. Repeat for each group, after its --message.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without making changes.",
    ),
) -> None:
    """Split the PR range into caller-supplied commit groups."""
    path_groups = [p.split(",") for p in paths] if paths else None
    rc = cmd_split(
        argparse.Namespace(
            plan=plan,
            base=base,
            message=message,
            paths=path_groups,
            dry_run=dry_run,
        )
    )
    raise typer.Exit(rc)


def _run_ship_close(
    task_id: str,
    plan: Optional[str],
    queue: str,
    branch: Optional[str],
    merge_commit: Optional[str],
    target_branch: Optional[str],
    dry_run: bool,
    delete_branch: bool = False,
) -> int:
    return cmd_ship(
        argparse.Namespace(
            command="record-merge",
            task_id=task_id,
            plan=plan,
            queue=queue,
            dry_run=dry_run,
            branch=branch,
            merge_commit=merge_commit,
            target_branch=target_branch,
            delete_branch=delete_branch,
        )
    )


@app.command(name="verify")
def ship_verify(
    task_id: str = typer.Argument(
        ...,
        help="Task ID to verify.",
    ),
    plan_or_queue: Optional[str] = typer.Argument(
        None,
        help="Plan path (when first arg is a task ID) or queue path (when first arg is a plan).",
    ),
    queue: str = typer.Argument(
        ".agents/aet-queue",
        help="Path to the queue anchor.",
    ),
    squash_fallback: bool = typer.Option(
        False,
        "--squash-fallback",
        help="Enable diff-based squash-merge fallback when ancestry and gh fail.",
    ),
    branch: Optional[str] = typer.Option(
        None,
        "--branch",
        help="Branch name to verify. Overrides the task's branch field.",
    ),
    target_branch: Optional[str] = typer.Option(
        None,
        "--target-branch",
        help="Target branch to verify the merge against (default: configured integration branch).",
    ),
) -> None:
    """Verify a branch has merged without mutating state."""
    rc = cmd_verify(
        argparse.Namespace(
            command="verify",
            task_id=task_id,
            plan=plan_or_queue,
            queue=queue,
            squash_fallback=squash_fallback,
            branch=branch,
            target_branch=target_branch,
        )
    )
    raise typer.Exit(rc)


@app.command(name="close")
def ship_close(
    task_id: str = typer.Argument(
        ...,
        help="Task ID to close (use `aet sprint add` to intake a plan).",
    ),
    plan: Optional[str] = typer.Argument(
        None,
        help="Deprecated and ignored: plan paths are no longer accepted (R-3).",
    ),
    queue: str = typer.Argument(
        ".agents/aet-queue",
        help="Path to the queue anchor.",
    ),
    branch: Optional[str] = typer.Option(
        None,
        "--branch",
        help="Branch name to use for merge verification. Overrides the task's branch field.",
    ),
    merge_commit: Optional[str] = typer.Option(
        None,
        "--merge-commit",
        help="Merge commit SHA to record directly. Must be an ancestor of the resolved trunk branch.",
    ),
    target_branch: Optional[str] = typer.Option(
        None,
        "--target-branch",
        help="Target branch the source branch merged into (default: configured integration branch). "
        "Use 'main' when closing an epic whose integration branch merged to trunk.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without making changes.",
    ),
    delete_branch: bool = typer.Option(
        False,
        "--delete-branch",
        help="After successful closure, delete the remote and local feature branch.",
    ),
) -> None:
    """Record post-merge closure for a task."""
    try:
        resolved_task_id, resolved_plan, resolved_queue = _normalize_close_args(task_id, plan, queue)
    except ValueError as exc:
        raise typer.Exit(_fail(str(exc)))
    raise typer.Exit(
        _run_ship_close(
            resolved_task_id,
            resolved_plan,
            resolved_queue,
            branch,
            merge_commit,
            target_branch,
            dry_run,
            delete_branch,
        )
    )


@app.command(name="record-merge")
def ship_record_merge(
    task_id: str = typer.Argument(
        ...,
        help="Task ID to close (use `aet sprint add` to intake a plan).",
    ),
    plan: Optional[str] = typer.Argument(
        None,
        help="Deprecated and ignored: plan paths are no longer accepted (R-3).",
    ),
    queue: str = typer.Argument(
        ".agents/aet-queue",
        help="Path to the queue anchor.",
    ),
    branch: Optional[str] = typer.Option(
        None,
        "--branch",
        help="Branch name to use for merge verification. Overrides the task's branch field.",
    ),
    merge_commit: Optional[str] = typer.Option(
        None,
        "--merge-commit",
        help="Merge commit SHA to record directly. Must be an ancestor of the resolved trunk branch.",
    ),
    target_branch: Optional[str] = typer.Option(
        None,
        "--target-branch",
        help="Target branch the source branch merged into (default: configured integration branch). "
        "Use 'main' when closing an epic whose integration branch merged to trunk.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without making changes.",
    ),
    delete_branch: bool = typer.Option(
        False,
        "--delete-branch",
        help="After successful closure, delete the remote and local feature branch.",
    ),
) -> None:
    """Hidden alias for close."""
    try:
        resolved_task_id, resolved_plan, resolved_queue = _normalize_close_args(task_id, plan, queue)
    except ValueError as exc:
        raise typer.Exit(_fail(str(exc)))
    raise typer.Exit(
        _run_ship_close(
            resolved_task_id,
            resolved_plan,
            resolved_queue,
            branch,
            merge_commit,
            target_branch,
            dry_run,
            delete_branch,
        )
    )


if __name__ == "__main__":
    app()
