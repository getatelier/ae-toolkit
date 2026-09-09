"""aet-state — Owns queue mutations and stage transitions.

Standard-library Python only. Derives status from ground truth (git, filesystem),
validates transition legality, and updates the queue atomically. The stage
lives on the task record; plan files are never written (R-4/R-19).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import typer

from aet import queue as queue_lib  # noqa: E402
from aet import spec_backfill  # noqa: E402
from aet.backends.base import SHADOW_POSTURE  # noqa: E402
from aet.backends.factory import (  # noqa: E402, I001
    create_backend,
    queue_repo_root,
    resolve_config,
    resolve_integration_mode,
)
from aet.backends.git_refs_backend import GitRefsBackend  # noqa: E402
from aet.branch_ref import (  # noqa: E402
    resolve_integration_branch,
    resolve_integration_branch_for_task,
    resolve_trunk_branch,
)
from aet.ledger import Ledger, resolve_ledger_path  # noqa: E402

_INTEGRITY_ERRORS = (queue_lib.QueueIntegrityError,)

def make_backend(queue_path):
    """Create a task backend for the given queue path."""
    history_file = str(Path(queue_path).with_name("work-history.jsonl"))
    config_path = str(Path(queue_path).with_name("aet-config.json"))
    return create_backend(
        config_path=config_path, queue_file=queue_path, history_file=history_file
    )


def _resolve_trunk(queue_path):
    """Resolve the trunk branch for the repo containing the queue file."""
    cwd = os.path.dirname(queue_path) if queue_path else "."
    # The queue file lives in the .agents directory, so the project config is
    # right next to it (e.g. .agents/aet-config.json).
    config = resolve_config(os.path.join(cwd, "aet-config.json"))
    return resolve_trunk_branch(cwd, config).ref


def _resolve_integration(queue_path):
    """Resolve the integration branch for the repo containing the queue file."""
    cwd = os.path.dirname(queue_path) if queue_path else "."
    config = resolve_config(os.path.join(cwd, "aet-config.json"))
    return resolve_integration_branch(cwd, config).ref


def _resolve_integration_for_task(queue_path, task, cli_base=None):
    """Resolve the per-task integration branch, including PRD-derived branches.

    In ``single-pr`` mode the branch is derived from the task's PRD when no
    static override is supplied (R-17).  In ``pr-per-task`` mode the configured
    integration branch (or trunk) is used.
    """
    repo_root = queue_repo_root(queue_path)
    if repo_root is None:
        repo_root = os.path.dirname(queue_path) if queue_path else "."
    config_path = os.path.join(repo_root, ".agents", "aet-config.json")
    config = resolve_config(config_path, repo_root=repo_root)
    integration_mode = resolve_integration_mode(config_path, repo_root=repo_root)
    return resolve_integration_branch_for_task(
        repo_root, config, task, integration_mode, cli_base=cli_base
    )


def find_task(queue, task_id):
    for task in queue:
        if task.get("id") == task_id:
            return task
    return None


def resolve_task_record(task_id, queue, backend=None):
    """Resolve a task id to a live or sealed merged task record.

    Searches the live queue, then the sealed tombstone, then the history
    JSONL. Returns ``(task, sealed_task)`` where exactly one is non-``None``
    when a record is found, or ``(None, None)`` when no record exists.
    Idempotent on settled tasks (R-4).

    The tombstone is consulted before the JSONL because it is the record that
    always exists: ``seal`` writes it in every posture, in the same atomic
    transaction as the task-ref deletion, while shadow posture — the default
    for an unconfigured project — never writes the JSONL at all. Reading only
    the file made an already-settled task report as "Task not found", turning
    a resumed closure into a hard error.

    The JSONL remains as a fallback for records sealed before tombstones
    existed (ADR-055).
    """
    if backend is None:
        backend = make_backend(queue)
        backend.fetch()
    data = backend.load()
    task = find_task(data["queue"], task_id)
    if task:
        return task, None
    read_sealed = getattr(backend, "read_sealed", None)
    if read_sealed is not None:
        sealed = read_sealed(task_id)
        if sealed and sealed.get("state") == "merged":
            return None, sealed
    history_file = getattr(backend, "history_file", None)
    if history_file:
        sealed = find_task(queue_lib.read_history(history_file), task_id)
        if sealed and sealed.get("state") == "merged":
            return None, sealed
    return None, None


def run_git(*args, cwd=None):
    """Run a git command; return (returncode, stdout, stderr)."""
    cmd = ["git", *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, check=False
        )
    except FileNotFoundError:
        return (127, "", "git not found")
    return (result.returncode, result.stdout, result.stderr)


def run_gh(args, cwd=None):
    """Run a gh command; return (returncode, stdout, stderr)."""
    cmd = ["gh", *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, check=False
        )
    except FileNotFoundError:
        return (127, "", "gh not found")
    return (result.returncode, result.stdout, result.stderr)


def branch_exists(branch, cwd=None):
    if not branch:
        return False
    rc, _, _ = run_git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", cwd=cwd)
    return rc == 0


def is_ancestor_of_trunk(branch, trunk_branch, cwd=None):
    if not branch or not trunk_branch:
        return False
    rc, _, _ = run_git(
        "merge-base", "--is-ancestor", branch, f"origin/{trunk_branch}", cwd=cwd
    )
    return rc == 0


def is_ancestor_of_target(branch, target_branch, cwd=None):
    """Return True when ``branch`` is an ancestor of ``origin/<target_branch>``."""
    if not branch or not target_branch:
        return False
    rc, _, _ = run_git(
        "merge-base", "--is-ancestor", branch, f"origin/{target_branch}", cwd=cwd
    )
    return rc == 0


def _resolve_sha(ref, cwd=None):
    """Return the resolved sha for ``ref``, or None when it cannot be resolved."""
    if not ref:
        return None
    rc, out, _ = run_git("rev-parse", ref, cwd=cwd)
    if rc != 0:
        return None
    return out.strip() or None


def _is_same_commit(a, b, cwd=None):
    """Return True when ``a`` and ``b`` are provably the same commit.

    Compares the raw values first so a recorded sha needs no git call, then
    falls back to resolving both. Unresolvable refs return False: this answers
    "are these provably identical", and it is used to *disqualify* evidence,
    so an unknown answer must not disqualify.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    sha_a = _resolve_sha(a, cwd=cwd)
    sha_b = _resolve_sha(b, cwd=cwd)
    return bool(sha_a and sha_b and sha_a == sha_b)


def branch_has_own_commits(branch, base_commit, cwd=None):
    """Return True when ``branch`` has moved past the commit it was created at.

    ADR-064 decision 2: a branch still sitting on its ``base_commit`` has
    authored nothing, so nothing it authored can be on the trunk.

    Fails closed (decision 4): an unrecorded or unresolvable ``base_commit``
    returns False, because the absence of a recorded origin is not evidence
    that the branch carries work.
    """
    tip = _resolve_sha(branch, cwd=cwd)
    base = _resolve_sha(base_commit, cwd=cwd)
    if not tip or not base:
        return False
    return tip != base


def has_merge_evidence(branch, merge_commit, base_commit, target_branch, cwd=None):
    """Return True when there is evidence the task's work reached the target.

    ADR-064: ancestry alone is not merge evidence. An undiverged task branch
    sits at its base and is trivially an ancestor of that base, which is
    indistinguishable from a merged branch by ancestry alone.

    Evidence is either of:
      - a recorded ``merge_commit``, distinct from the branch's base, that is
        an ancestor of ``origin/<target_branch>``; or
      - a branch that has moved past its ``base_commit`` and is an ancestor of
        ``origin/<target_branch>``.
    """
    # A recorded merge commit is positive evidence on its own. The base check
    # only disqualifies it when the two are provably the same commit — a
    # "merge commit" that is the branch's own base records no work.
    if (
        merge_commit
        and not _is_same_commit(merge_commit, base_commit, cwd=cwd)
        and is_ancestor_of_target(merge_commit, target_branch, cwd=cwd)
    ):
        return True
    if (
        branch
        and branch_has_own_commits(branch, base_commit, cwd=cwd)
        and is_ancestor_of_target(branch, target_branch, cwd=cwd)
    ):
        return True
    return False


def resolve_merge_commit(
    branch,
    cwd=None,
    trunk_branch="main",
    target_branch=None,
    use_diff_fallback=True,
    base_commit=None,
):
    """Resolve the merge commit for a branch on the remote target branch.

    Tries, in order:
      1. Regular merge: branch tip is an ancestor of origin/<target_branch>.
      2. Squash merge via `gh pr view <branch> --json mergeCommit`.
      3. Diff-equivalence fallback against recent origin/<target_branch> commits
         (only when ``use_diff_fallback`` is True).

    ``target_branch`` defaults to ``trunk_branch`` so ``pr-per-task`` behavior is
    unchanged; ``single-pr`` callers pass the epic integration branch.

    ``base_commit`` is the commit the branch was created at. Per ADR-064
    decision 3, the ancestry path resolves only for a branch that has moved
    past it: a branch sitting at its base authored no commit, so reporting its
    tip would manufacture evidence out of the absence of work. An unrecorded
    ``base_commit`` fails that path closed; the squash and diff paths still
    apply, because both match on content the task actually produced.

    Returns (merge_commit, merge_strategy, match_kind). ``match_kind`` is
    ``ancestry`` for regular merges, ``gh-api`` for squash merges resolved
    through GitHub, ``exact``/``drift`` for diff fallback, ``ambiguous`` when
    the fallback cannot distinguish candidates, and ``None`` when unresolved.
    """
    if not branch:
        return None, None, None

    target = target_branch or trunk_branch

    # 1. Regular merge: branch tip is on the remote target branch, and the
    #    branch has moved past its base so the tip is a commit it authored.
    tip = _resolve_sha(branch, cwd=cwd)
    if tip and branch_has_own_commits(branch, base_commit, cwd=cwd):
        if is_ancestor_of_target(tip, target, cwd=cwd):
            return tip, "regular", "ancestry"

    # 2. Squash merge via GitHub CLI.
    rc, out, _ = run_gh(["pr", "view", branch, "--json", "mergeCommit"], cwd=cwd)
    if rc == 0:
        try:
            data = json.loads(out)
            sha = data.get("mergeCommit", {}).get("oid")
            if sha and is_ancestor_of_target(sha, target, cwd=cwd):
                return sha, "squash", "gh-api"
        except json.JSONDecodeError:
            pass

    # 3. Diff-equivalence fallback.
    if use_diff_fallback:
        sha, match_kind = resolve_by_diff(
            branch, cwd=cwd, trunk_branch=trunk_branch, target_branch=target
        )
        if sha:
            return sha, "squash", match_kind
        if match_kind == "ambiguous":
            return None, None, "ambiguous"

    return None, None, None


def _diff_changed_lines(diff: str) -> set[str]:
    """Return the set of changed content lines in a unified diff.

    Context lines and file headers are ignored. Content is stripped so that
    trailing/leading whitespace churn does not create false drift.
    """
    changed: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            changed.add(line[1:].strip())
        elif line.startswith("-") and not line.startswith("---"):
            changed.add(line[1:].strip())
    return changed


def resolve_by_diff(
    branch,
    cwd=None,
    max_commits=20,
    trunk_branch="main",
    target_branch=None,
    drift_threshold=20,
):
    """Find a squash merge by matching the branch diff to a recent target commit.

    First scans the last ``max_commits`` on ``origin/<target_branch>`` for an
    exact diff match. If none is found, performs a second pass that accepts a
    candidate whose changed-line set drifts from the branch diff by no more than
    ``drift_threshold`` lines.

    Returns ``(sha, match_kind)``. ``match_kind`` is ``exact`` or ``drift`` on
    success, ``ambiguous`` when the branch diff is empty or more than one drift
    candidate exists, and ``None`` when no match is found.
    """
    target = target_branch or trunk_branch
    rc, merge_base, _ = run_git(
        "merge-base", branch, f"origin/{target}", cwd=cwd
    )
    if rc != 0:
        return None, None
    merge_base = merge_base.strip()

    rc, branch_diff, _ = run_git("diff", f"{merge_base}..{branch}", cwd=cwd)
    if rc != 0:
        return None, None
    branch_diff = branch_diff.strip()
    if not branch_diff:
        return None, "ambiguous"

    rc, commits_out, _ = run_git(
        "rev-list", "--max-count", str(max_commits), f"origin/{target}", cwd=cwd
    )
    if rc != 0:
        return None, None
    commits = [c.strip() for c in commits_out.strip().splitlines() if c.strip()]

    # First pass: exact match.
    for commit in commits:
        rc, commit_diff, _ = run_git("diff", f"{commit}^..{commit}", cwd=cwd)
        if rc != 0:
            continue
        if commit_diff.strip() == branch_diff:
            return commit, "exact"

    # Second pass: tolerant drift match.
    branch_changed = _diff_changed_lines(branch_diff)
    drift_candidates = []
    for commit in commits:
        rc, commit_diff, _ = run_git("diff", f"{commit}^..{commit}", cwd=cwd)
        if rc != 0:
            continue
        commit_changed = _diff_changed_lines(commit_diff)
        drift = len(branch_changed.symmetric_difference(commit_changed))
        if drift <= drift_threshold:
            drift_candidates.append((commit, drift))

    if len(drift_candidates) == 1:
        return drift_candidates[0][0], "drift"
    if len(drift_candidates) > 1:
        return None, "ambiguous"

    return None, None


def derive_status(task, blocker_status_fn=None, cwd=None, trunk_branch="main", integration_branch=None):
    """Derive canonical state from ground truth.

    Derivation rules, applied in order:
      1. merged   — there is merge evidence on origin/<integration_branch>:
                   a recorded merge_commit, or a branch that has moved past
                   its base_commit, that is an ancestor of the target
                   (ADR-064; ancestry alone is not evidence).
      2. in_progress — local branch exists and carries own commits (has moved
                   past its base_commit; ADR-072 / eop-02).
      3. ready    — plan exists, no branch or branch sitting at base, and all
                   blockers are terminal (including the case of no blockers).
      4. blocked  — plan exists, no branch or branch sitting at base, and some
                   blocker is not terminal.
      5. drift    — plan file is missing and the record carries no spec.
      6. planned  — plan exists, no branch, no blockers.

    "Plan exists" means the file is on disk or the record carries a portable
    spec (R-19): the spec renders the working file on demand, so its absence
    on this machine is not drift.

    ``integration_branch`` defaults to ``trunk_branch`` so ``pr-per-task`` behavior
    is unchanged; ``single-pr`` callers pass the epic integration branch.
    """
    plan_file = task.get("plan_file")
    branch = task.get("branch")
    worktree = task.get("worktree")
    merge_commit = task.get("merge_commit")
    target_branch = (
        task.get("integration_branch")
        or (task.get("stamp", {}).get("branch") if isinstance(task.get("stamp"), dict) else None)
        or integration_branch
        or trunk_branch
    )

    derived = {"derived_status": "unknown"}


    # Plan file exists?  A record carrying a portable spec (R-19) counts as
    # having its plan: the spec renders the working file on demand, so the
    # file's absence on this machine is not drift.
    if plan_file and Path(plan_file).exists():
        derived["plan_exists"] = True
    elif isinstance(task.get("spec"), dict):
        derived["plan_exists"] = True
    else:
        derived["plan_exists"] = False

    # Branch exists?
    if branch and branch_exists(branch, cwd=cwd):
        derived["branch_exists"] = True
    else:
        derived["branch_exists"] = False

    # Merge evidence (ADR-064): ancestry alone is not proof. A branch that has
    # not moved past its base is trivially an ancestor of that base and has
    # authored nothing.
    on_trunk = has_merge_evidence(
        branch, merge_commit, task.get("base_commit"), target_branch, cwd=cwd
    )
    derived["on_trunk"] = on_trunk

    # Worktree present?
    if worktree and Path(worktree).is_dir():
        derived["has_worktree"] = True
    else:
        derived["has_worktree"] = False

    # Merge commit set?
    if merge_commit:
        derived["merge_verified"] = True
    else:
        derived["merge_verified"] = False

    # In-progress evidence (ADR-072 / eop-02): a branch sitting at its base
    # commit has authored nothing and is not evidence of active work.
    has_own_commits = (
        derived["branch_exists"]
        and branch_has_own_commits(branch, task.get("base_commit"), cwd=cwd)
    )

    # Determine actionable canonical state.
    status = "unknown"
    if on_trunk:
        status = "merged"
    elif has_own_commits:
        status = "in_progress"
    elif derived["plan_exists"]:
        blockers = task.get("blocked_by", [])
        if blockers and blocker_status_fn:
            terminal = {"merged", "abandoned"}
            all_terminal = all(blocker_status_fn(b) in terminal for b in blockers)
            status = "ready" if all_terminal else "blocked"
        elif blockers and not blocker_status_fn:
            # Blockers exist but we cannot resolve them; refuse an external
            # assertion of readiness and treat the task as blocked.
            status = "blocked"
        else:
            # No blockers means the task is actionable.
            status = "ready"
    else:
        status = "drift"
        derived["drift"] = "plan_file missing"

    # Warnings
    current_status = queue_lib.current_state(task) or ""
    warnings = []
    if current_status == "awaiting_merge" and not merge_commit and not on_trunk:
        warnings.append("awaiting_merge without merge verification")
    if current_status == "merged" and not on_trunk:
        warnings.append(f"merged state but not ancestor of origin/{target_branch}")
    if warnings:
        derived["warnings"] = warnings
        status = f"{status} (warning: {'; '.join(warnings)})"

    derived["derived_status"] = status
    return derived


def _clear_stale_runtime_fields(task, cwd=None):
    """Remove ``branch``/``worktree`` pointers whose referent no longer exists.

    Returns ``True`` when at least one runtime field was cleared.
    """
    cleared = False
    branch = task.get("branch")
    if branch and not branch_exists(branch, cwd=cwd):
        task.pop("branch", None)
        cleared = True
    worktree = task.get("worktree")
    if worktree and not Path(worktree).is_dir():
        task.pop("worktree", None)
        cleared = True
    return cleared


def validate_transition(task, from_stage, to_stage, cwd=None, trunk_branch="main", integration_branch=None):
    """Return (ok, message). ok=True means the state transition is legal.

    Validates the recorded-forward lifecycle (ADR-011).  ``from_stage`` and
    ``to_stage`` are canonical state values, not legacy status strings.
    """
    current_state = queue_lib.current_state(task)
    branch = task.get("branch")
    merge_commit = task.get("merge_commit")
    target_branch = (
        task.get("integration_branch")
        or (task.get("stamp", {}).get("branch") if isinstance(task.get("stamp"), dict) else None)
        or integration_branch
        or trunk_branch
    )


    # Basic: from_stage should match current state
    if from_stage != current_state:
        return (False, f"Current state is '{current_state}', not '{from_stage}'.")

    # Transition must be legal in the lifecycle
    legal = queue_lib.LEGAL_TRANSITIONS.get(from_stage, set())
    if to_stage not in legal:
        return (False, f"Illegal transition: {from_stage} -> {to_stage}.")

    # Cannot set merged without evidence of merged content (ADR-064).
    if to_stage == "merged":
        if not has_merge_evidence(
            branch, merge_commit, task.get("base_commit"), target_branch, cwd=cwd
        ):
            return (
                False,
                f"Cannot set merged: no merge evidence on origin/{target_branch} "
                f"(branch/merge_commit must carry commits past the task's base).",
            )

    return (True, "Transition is valid.")


def _apply_transition(
    backend,
    queue,
    task,
    from_state,
    to_state,
    by,
    evidence=None,
    cwd=None,
    history_file=None,
    trunk_branch="main",
    repair=False,
    integration_branch=None,
):
    """Apply a validated state transition and propagate the forward frontier.

    This is the only function that assigns ``task["state"]``.  It validates the
    transition, appends history, promotes dependents after terminal transitions,
    persists the queue through the configured backend, and seals terminal tasks
    to the settled history log.

    Terminal transitions record the stage on the task record and in the ledger;
    they no longer touch plan files — footer commits and archive moves were
    removed with R-4/R-19 (relocation is owb-03's job).  The caller must already
    hold the queue lock; the queue-ref write is atomic via the backend.

    When ``repair`` is true, lifecycle legality is bypassed so that heal and
    reset can move a task back to its git-derived state; the current-state check
    and merged ancestry guard are still enforced.
    """
    current_state = queue_lib.current_state(task)
    if from_state != current_state:
        raise RuntimeError(f"Current state is '{current_state}', not '{from_state}'.")

    target_branch = integration_branch or trunk_branch
    if not repair:
        ok, msg = validate_transition(
            task, from_state, to_state, cwd=cwd, trunk_branch=trunk_branch, integration_branch=target_branch
        )
        if not ok:
            raise RuntimeError(msg)
    elif to_state == "merged":
        # Repair bypasses lifecycle legality; it does not bypass evidence
        # (ADR-064 decision 5).
        if not has_merge_evidence(
            task.get("branch"),
            task.get("merge_commit"),
            task.get("base_commit"),
            target_branch,
            cwd=cwd,
        ):
            raise RuntimeError(
                f"Cannot set merged: no merge evidence on origin/{target_branch} "
                f"(branch/merge_commit must carry commits past the task's base)."
            )

    now = datetime.now(timezone.utc).isoformat()

    task["state"] = to_state

    if to_state == "merged":
        task["merged_at"] = now
        task["completed_at"] = now
    elif to_state in queue_lib.TERMINAL_STATES:
        task["completed_at"] = now

    queue_lib.append_history(task, from_state, to_state, by, evidence)

    # Repairs clear stale branch/worktree pointers whose referents disappeared.
    if repair:
        _clear_stale_runtime_fields(task, cwd=cwd)

    # Forward frontier: terminal transitions unblock dependents. A dependent is
    # promoted once its last blocker clears, whether it was curated as
    # ``blocked`` or is still sitting at ``planned`` (pre-frh-15 intake). The
    # release history entry records the actual from-state.
    if to_state in queue_lib.TERMINAL_STATES:
        for dep_id in task.get("blocks", []):
            dep = find_task(queue, dep_id)
            if not dep:
                continue
            pb = queue_lib.pending_blockers(dep)
            if pb > 0:
                pb -= 1
                dep["pending_blockers"] = pb
            dep_state = queue_lib.current_state(dep)
            if pb == 0 and dep_state in ("blocked", "planned"):
                dep["state"] = "ready"
                queue_lib.append_history(dep, dep_state, "ready", "release")

    backend.save(queue)
    backend.on_transition(task["id"], from_state, to_state, evidence)

    # Seal terminal tasks to the append-only settled history log. Routing
    # through the backend keeps the file-path assumption out of aet-state so
    # non-file backends (e.g. git refs) can drop their own live record first.
    if to_state in queue_lib.TERMINAL_STATES:
        if history_file is None:
            history_file = getattr(backend, "history_file", None) or str(
                Path(backend.queue_file).with_name("work-history.jsonl")
            )
        backend.seal(task["id"], history_file)
        backend.close_task(task["id"], evidence)

        # Record the terminal closure event in the content-addressed ledger.
        # Plan footer writes are gone (R-4/R-19), and the R-5 plan archive is
        # retired with R-7; the digest is derived from the task record itself.
        ledger_path = resolve_ledger_path()
        ledger = Ledger(ledger_path)
        merge_ref = task.get("merge_commit")
        land_payload = _land_digest(task)
        if merge_ref:
            ledger.write_event(
                source="aet-state",
                task=task["id"],
                kind="land",
                ref=merge_ref,
                ref_kind="git-sha",
                payload=land_payload,
            )
        else:
            occurred_at = task.get("completed_at") or datetime.now(
                timezone.utc
            ).isoformat()
            ledger.write_event(
                source="aet-state",
                task=task["id"],
                kind="land",
                occurred_at=occurred_at,
                payload=land_payload,
            )


def _land_digest(task: dict[str, Any]) -> dict[str, Any]:
    """Build the R-8 closure digest payload for a ``land`` event.

    The digest is derived from the task record's portable spec (R-19) when
    available; otherwise it falls back to the on-disk plan file.  The R-5
    ``archived_to`` field is no longer written (R-7), but historical ``land``
    events keep the field they were written with (ADR-059).
    """
    digest: dict[str, Any] = {
        "merge_ref": task.get("merge_commit") or task.get("branch")
    }
    content: bytes | None = None
    spec = task.get("spec")
    if isinstance(spec, dict):
        # Spec serialization is the durable source after R-19.
        content = json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")
    else:
        plan_file = task.get("plan_file")
        if plan_file is not None:
            try:
                content = Path(plan_file).read_bytes()
            except OSError:
                content = None
    if content is not None:
        digest["plan_hash"] = hashlib.sha256(content).hexdigest()
        text = content.decode("utf-8", errors="ignore")
        digest["prd_r_ids"] = sorted(set(re.findall(r"R-\d+", text)))
    return digest


def _set_stage(task, stage, by="orch"):
    """Set the pipeline stage sub-state on a task that is in_progress.

    This is the only function that assigns ``task["stage"]``.  It appends a
    history entry and returns nothing.  The caller must ensure the task is
    loaded from the latest queue and that the queue is saved afterwards.
    """
    current = queue_lib.current_state(task)
    if current != "in_progress":
        raise RuntimeError(
            f"Cannot set stage: task state is '{current}', must be 'in_progress'."
        )

    previous_stage = task.get("stage")
    task["stage"] = stage
    queue_lib.append_history(task, previous_stage, stage, by, {"kind": "stage"})

def cmd_set_stage(args):
    """Set the pipeline stage sub-state for a task in the queue.

    Writes the stage to the task record and clears any stale
    ``failure_reason`` left over from reactivation. A ``stage`` event is
    emitted to the content-addressed ledger after the queue is persisted.
    """
    backend = make_backend(args.queue)
    backend.fetch()

    if not queue_lib.lease_guard(args.queue, force=getattr(args, "force", False)):
        return queue_lib.LEASE_HELD_EXIT_CODE

    with queue_lib.queue_lock(args.queue):
        data = backend.load()
        queue = data["queue"]
        task = find_task(queue, args.task_id)
        if not task:
            print(f"Task not found: {args.task_id}", file=sys.stderr)
            return 1

        if args.dry_run:
            current = queue_lib.current_state(task)
            if current == "in_progress":
                print(
                    f"[dry-run] Would set stage for {args.task_id}: "
                    f"{task.get('stage')} -> {args.stage}"
                )
                return 0
            print(
                f"Cannot set stage: task state is '{current}', must be 'in_progress'.",
                file=sys.stderr,
            )
            return 1

        try:
            _set_stage(task, args.stage, by="orch")
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1

        previous_stage = task["history"][-1]["from"] if task.get("history") else None

        # Stale failure_reason from a previous failure/abandonment must not
        # survive reactivation (migration-aet-state.md:55).
        if task.get("failure_reason"):
            del task["failure_reason"]

        backend.save(queue)
    backend.push()

    print(f"Set stage for {args.task_id}: {args.stage}")

    ledger_path = resolve_ledger_path()
    ledger = Ledger(ledger_path)
    occurred_at = datetime.now(timezone.utc).isoformat()
    ledger.write_event(
        source="aet-state",
        task=args.task_id,
        kind="stage",
        occurred_at=occurred_at,
        payload={"stage": args.stage, "previous_stage": previous_stage},
    )

    return 0


def _derive_all_states(
    queue,
    cwd,
    trunk_branch="main",
    integration_branch=None,
    repo_root=None,
    config=None,
    integration_mode=None,
):
    """Return (task_by_id, derived) for every task in the queue.

    A task is on the board if and only if it is in ``queue``. A blocker that is
    no longer on the board has left the open-work set and is treated as
    terminal, so a dependent whose blocker already settled derives ``ready``
    instead of staying ``blocked`` forever. The settled history log is not an
    authority (R-8); it is kept only as a measurement input for metrics and
    retrospectives.

    When ``repo_root``, ``config`` and ``integration_mode`` are supplied, the
    integration branch is resolved per task. This lets ``single-pr`` tasks use
    their PRD-derived integration branch while ``pr-per-task`` tasks keep the
    static one (R-17).
    """
    tasks = queue
    task_by_id = {t["id"]: t for t in tasks if t.get("id")}
    derived = {}

    def _task_target(task):
        """Return the integration branch this task's status is derived against.

        Falls back to the static branch when the caller supplied no repository
        context, which is what keeps the many direct callers unchanged.
        """
        stamped = task.get("integration_branch") or (
            task.get("stamp", {}).get("branch") if isinstance(task.get("stamp"), dict) else None
        )
        if stamped:
            return stamped
        if repo_root is not None and config is not None and integration_mode is not None:
            return resolve_integration_branch_for_task(
                repo_root, config, task, integration_mode
            ).ref
        return integration_branch


    def blocker_status(task_id):
        if task_id in task_by_id:
            if task_id not in derived:
                blocker = task_by_id[task_id]
                derived[task_id] = derive_status(
                    blocker,
                    blocker_status,
                    cwd=cwd,
                    trunk_branch=trunk_branch,
                    integration_branch=_task_target(blocker),
                )
            status = derived[task_id]["derived_status"]
        else:
            # Not on the board: the blocker has left the open-work set.
            status = "merged"
        return status.split(" (warning")[0]

    for task in tasks:
        task_id = task["id"]
        if task_id not in derived:
            derived[task_id] = derive_status(
                task,
                blocker_status,
                cwd=cwd,
                trunk_branch=trunk_branch,
                integration_branch=_task_target(task),
            )

    return task_by_id, derived


def cmd_audit(args):
    """Reconcile stored state against git ground truth without mutating.

    Reports every task where the recorded state disagrees with the state
    derived from git. This is the old ``derive`` command repurposed as an
    explicit, human-run audit; it never runs during normal operation.

    A queue whose integrity envelope no longer matches its tasks (edited
    outside ``aet-state``) is still auditable: the mismatch is reported on
    stderr and the audit proceeds with the unverified data, so audit works
    as the diagnostic for exactly the situation it is recommended in. Run
    ``aet state heal --apply`` to reconcile and restamp the envelope.
    """
    backend = make_backend(args.queue)
    backend.fetch()
    try:
        backend.load()
    except _INTEGRITY_ERRORS:
        print(
            "⚠️  Queue integrity check failed (content_hash mismatch); "
            "audit continues with unverified data. "
            "Run `aet state heal --apply` to reconcile and restamp.",
            file=sys.stderr,
        )
    data = backend.load(verify=False)
    queue = data["queue"]
    cwd = os.path.dirname(args.queue) if args.queue else "."
    trunk_branch = _resolve_trunk(args.queue)
    repo_root = queue_repo_root(args.queue) or cwd
    config_path = os.path.join(repo_root, ".agents", "aet-config.json")
    config = resolve_config(config_path, repo_root=repo_root)
    integration_mode = resolve_integration_mode(config_path, repo_root=repo_root)
    task_by_id, derived = _derive_all_states(
        queue,
        cwd,
        trunk_branch=trunk_branch,
        repo_root=repo_root,
        config=config,
        integration_mode=integration_mode,
    )

    missing_spec = set(spec_backfill.records_missing_spec(queue))

    results = {}
    for task in queue:
        task_id = task["id"]
        stored_state = queue_lib.current_state(task)
        derived_state = derived[task_id]["derived_status"].split(" (warning")[0]
        results[task_id] = {
            "stored": stored_state,
            "derived": derived[task_id]["derived_status"],
            "discrepancy": stored_state != derived_state,
            "missing_spec": task_id in missing_spec,
        }

    print(json.dumps(results, indent=2))
    if missing_spec:
        # R-19 moved a task's spec onto the record so a task planned on one
        # machine is executable on another; a record carrying only
        # ``plan_file`` points at a path that may not exist in any other
        # clone, which is how the board became unrunnable when the plan
        # files were deleted. This check used to live in the test suite,
        # asserted over whatever board the developer happened to have
        # checked out, so real debris failed `make validate` for everyone
        # and the property was only ever verified by accident. The audit is
        # where debris is the subject rather than a spurious red.
        print(
            "⚠️  These live task records carry no plan spec and are not "
            f"executable in another clone: {', '.join(missing_spec)}. "
            "Run `aet state backfill-specs --apply` to recover them from git.",
            file=sys.stderr,
        )
    return 0


def cmd_heal(args):
    """Reconcile stored state against git ground truth and apply safe fixes.

    Safe fixes:
      - merged: task branch or merge_commit is an ancestor of origin/main.
      - failed -> ready: plan exists, no branch, and blockers are terminal.
      - pending_blockers recount: the stored counter is reconciled against
        blockers that are not terminal in the live queue or the settled
        history log, so tasks added after a blocker merged cannot deadlock
        on a stale count.

    With ``--apply``, transitions are applied; otherwise the command prints a
    dry-run report.

    A queue whose integrity envelope no longer matches its tasks (edited
    outside ``aet-state``) is loaded unverified so heal can act as the
    repair path. ``--apply`` restamps the envelope (revision + content_hash)
    before applying any fixes, so a successful heal always leaves the queue
    verifiable again — including when there is nothing else to fix.
    """
    backend = make_backend(args.queue)
    backend.fetch()
    integrity_ok = True
    try:
        backend.load()
    except _INTEGRITY_ERRORS:
        integrity_ok = False
        print(
            "⚠️  Queue integrity check failed (content_hash mismatch); "
            "heal continues with unverified data.",
            file=sys.stderr,
        )
    data = backend.load(verify=False)
    queue = data["queue"]
    cwd = os.path.dirname(args.queue) if args.queue else "."
    trunk_branch = _resolve_trunk(args.queue)
    repo_root = queue_repo_root(args.queue) or cwd
    config_path = os.path.join(repo_root, ".agents", "aet-config.json")
    config = resolve_config(config_path, repo_root=repo_root)
    integration_mode = resolve_integration_mode(config_path, repo_root=repo_root)
    task_by_id, derived = _derive_all_states(
        queue,
        cwd,
        trunk_branch=trunk_branch,
        repo_root=repo_root,
        config=config,
        integration_mode=integration_mode,
    )

    # A blocker counts as pending only while it is on the board and not
    # terminal. A blocker that has left the board is settled by definition.
    terminal_ids = {
        t["id"]
        for t in queue
        if t.get("id") and queue_lib.current_state(t) in queue_lib.TERMINAL_STATES
    }

    changes: list[dict] = []
    for task in queue:
        task_id = task["id"]
        stored_state = queue_lib.current_state(task)
        derived_state = derived[task_id]["derived_status"].split(" (warning")[0]

        # Quarantined is a human-held state: it reconciles to itself and is never
        # auto-derived away by heal (nsr-02).
        if stored_state == "quarantined":
            continue

        change = None
        # Only heal toward terminal/ready states; never move a merged task backward.
        if derived_state == "merged" and stored_state != "merged":
            change = {
                "task_id": task_id,
                "from": stored_state,
                "to": "merged",
                "reason": "branch/merge_commit is ancestor of origin/main",
                "branch": task.get("branch"),
            }
        elif derived_state == "ready" and stored_state in ("failed", "blocked", "planned"):
            change = {
                "task_id": task_id,
                "from": stored_state,
                "to": "ready",
                "reason": "plan exists and blockers are terminal",
                "repair": True,
            }
        elif derived_state == "failed" and stored_state == "in_progress":
            change = {
                "task_id": task_id,
                "from": stored_state,
                "to": "failed",
                "reason": "branch does not exist and plan is missing or blocked",
                "repair": True,
            }
        elif derived_state in ("ready", "blocked") and stored_state in ("in_progress", "awaiting_merge"):
            change = {
                "task_id": task_id,
                "from": stored_state,
                "to": derived_state,
                "reason": "branch no longer exists; reset to derived state",
                "repair": True,
            }

        computed_pb = len(
            [
                b
                for b in task.get("blocked_by", [])
                if b in task_by_id and b not in terminal_ids
            ]
        )
        if computed_pb != queue_lib.pending_blockers(task):
            if change is None:
                change = {
                    "task_id": task_id,
                    "from": stored_state,
                    "to": stored_state,
                    "reason": "pending_blockers recount against settled blockers",
                }
            change["pending_blockers"] = computed_pb

        if change is not None:
            changes.append(change)

    if not changes:
        print("No healable discrepancies found.")
        if integrity_ok:
            return 0
        if not args.apply:
            print("Queue integrity envelope is stale; run with --apply to restamp it.")
            return 0
        # Fall through: no state fixes, but the envelope needs restamping.
    else:
        print("Proposed changes:")
        for change in changes:
            line = f"  {change['task_id']}: {change['from']} -> {change['to']} ({change['reason']})"
            if "pending_blockers" in change:
                line += f" [pending_blockers -> {change['pending_blockers']}]"
            print(line)

        if not args.apply:
            print("\nRun with --apply to apply these changes.")
            return 0

    if not queue_lib.lease_guard(args.queue, force=getattr(args, "force", False)):
        return queue_lib.LEASE_HELD_EXIT_CODE

    if not integrity_ok:
        # Restamp before applying fixes: every later load in this run (the
        # per-change reloads below and any record-merge invocation) verifies
        # against the new hash.
        with queue_lib.queue_lock(args.queue):
            fresh = backend.load(verify=False)
            backend.save(fresh["queue"])
        print("Restamped queue integrity envelope (revision + content_hash).")
        if not changes:
            return 0

    applied = 0
    failed = 0
    for change in changes:
        task_id = change["task_id"]

        # Each change is a full read-modify-write cycle on the queue; hold the
        # lock for the duration so concurrent writers cannot interleave.
        with queue_lib.queue_lock(args.queue):
            # Re-load the queue before each change; previous changes (especially
            # record-merge sealing a task) mutate the stored queue.
            data = backend.load()
            queue = data["queue"]
            task = find_task(queue, task_id)
            if not task:
                # Task was already sealed by a previous heal step.
                applied += 1
                continue

            from_state = queue_lib.current_state(task)
            to_state = change["to"]

            if "pending_blockers" in change:
                task["pending_blockers"] = change["pending_blockers"]

            if from_state == to_state:
                # Counter-only reconciliation: no transition, just persist.
                if "pending_blockers" in change:
                    backend.save(queue)
                    backend.push()
                applied += 1
                continue

            if to_state == "merged":
                # Prefer resolving via record-merge so merge_commit is captured.
                branch = task.get("branch") or change.get("branch")
                if branch:
                    merge_ns = argparse.Namespace(
                        command="record-merge",
                        task_id=task_id,
                        queue=args.queue,
                        dry_run=False,
                        plan=None,
                        branch=branch,
                        merge_commit=task.get("merge_commit"),
                    )
                    rc = cmd_record_merge(merge_ns)
                    if rc == 0:
                        applied += 1
                    else:
                        failed += 1
                    continue

            try:
                _apply_transition(
                    backend, queue, task, from_state, to_state,
                    by="heal", evidence={"reason": change["reason"]}, cwd=cwd,
                    trunk_branch=trunk_branch,
                    repair=change.get("repair", False),
                )
                backend.push()
                applied += 1
            except RuntimeError as e:
                print(f"  Could not heal {task_id}: {e}", file=sys.stderr)
                failed += 1

    print(f"\nHealed {applied} task(s); {failed} failed.")
    return 1 if failed > 0 else 0


def cmd_validate(args):
    backend = make_backend(args.queue)
    backend.fetch()
    data = backend.load()
    queue = data["queue"]
    task = find_task(queue, args.task_id)
    if not task:
        print(f"Task not found: {args.task_id}", file=sys.stderr)
        return 1
    cwd = os.path.dirname(args.queue) if args.queue else "."
    trunk_branch = _resolve_trunk(args.queue)
    integration_branch = _resolve_integration_for_task(args.queue, task).ref
    ok, msg = validate_transition(
        task,
        args.from_stage,
        args.to_stage,
        cwd=cwd,
        trunk_branch=trunk_branch,
        integration_branch=integration_branch,
    )
    if ok:
        print(msg)
        return 0
    print(msg, file=sys.stderr)
    return 1


def cmd_reset(args):
    """Recompute a single task from git + blockers and reset it to ready/blocked.

    This is the pointed, single-task form of ``heal``: it clears stale runtime
    fields and moves the task to the state derived from ground truth. It is the
    supported way to un-start a task whose branch/worktree has disappeared.
    """
    backend = make_backend(args.queue)
    backend.fetch()
    try:
        backend.load()
    except _INTEGRITY_ERRORS:
        print(
            "⚠️  Queue integrity check failed (content_hash mismatch); "
            "reset continues with unverified data.",
            file=sys.stderr,
        )
    data = backend.load(verify=False)
    queue = data["queue"]
    cwd = os.path.dirname(args.queue) if args.queue else "."
    trunk_branch = _resolve_trunk(args.queue)
    repo_root = queue_repo_root(args.queue) or cwd
    config_path = os.path.join(repo_root, ".agents", "aet-config.json")
    config = resolve_config(config_path, repo_root=repo_root)
    integration_mode = resolve_integration_mode(config_path, repo_root=repo_root)

    task = find_task(queue, args.task_id)
    if not task:
        print(f"Task not found: {args.task_id}", file=sys.stderr)
        return 1

    _, derived = _derive_all_states(
        queue,
        cwd,
        trunk_branch=trunk_branch,
        repo_root=repo_root,
        config=config,
        integration_mode=integration_mode,
    )
    derived_state = derived[args.task_id]["derived_status"].split(" (warning")[0]
    stored_state = queue_lib.current_state(task)

    if not args.apply:
        print(f"[dry-run] Would reset {args.task_id}: {stored_state} -> {derived_state}")
        return 0

    if not queue_lib.lease_guard(args.queue, force=getattr(args, "force", False)):
        return queue_lib.LEASE_HELD_EXIT_CODE

    with queue_lib.queue_lock(args.queue):
        # Re-load under the lock in case another process changed the queue.
        data = backend.load(verify=False)
        queue = data["queue"]
        task = find_task(queue, args.task_id)
        if not task:
            print(f"Task not found: {args.task_id}", file=sys.stderr)
            return 1

        stored_state = queue_lib.current_state(task)
        _, derived = _derive_all_states(
            queue,
            cwd,
            trunk_branch=trunk_branch,
            repo_root=repo_root,
            config=config,
            integration_mode=integration_mode,
        )
        derived_state = derived[args.task_id]["derived_status"].split(" (warning")[0]

        if derived_state not in ("ready", "blocked"):
            if stored_state == derived_state:
                cleared = _clear_stale_runtime_fields(task, cwd=cwd)
                if cleared:
                    backend.save(queue)
                    backend.push()
                print(f"Reset {args.task_id}: already {stored_state}")
                return 0
            print(
                f"Cannot reset {args.task_id}: derived state is {derived_state}, "
                "not ready/blocked.",
                file=sys.stderr,
            )
            return 1

        if stored_state == derived_state:
            cleared = _clear_stale_runtime_fields(task, cwd=cwd)
            if cleared:
                backend.save(queue)
                backend.push()
            print(f"Reset {args.task_id}: {stored_state} (runtime fields cleared)")
            return 0

        try:
            _apply_transition(
                backend, queue, task, stored_state, derived_state,
                by="reset", evidence={"reason": "reset to derived state"}, cwd=cwd,
                trunk_branch=trunk_branch, repair=True,
            )
            backend.push()
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1

    print(f"Reset {args.task_id}: {stored_state} -> {derived_state}")
    return 0


def _resolve_history_path(history_file: str, repo_root: str) -> str:
    """Resolve a possibly-relative history file path against the repo root."""
    if os.path.isabs(history_file):
        return history_file
    return os.path.join(repo_root, history_file)


def _write_history_file(history_file: str, records: list[dict[str, Any]]) -> None:
    """Atomically rewrite the append-only JSONL history log.

    The rewrite changes only the ``spec`` key on existing records; it must not
    add, remove, or reorder them.  A temp-file + rename keeps the update atomic.
    """
    history_dir = os.path.dirname(history_file)
    os.makedirs(history_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=history_dir, prefix=".history-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, history_file)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def cmd_backfill_specs(args):
    """Backfill the portable plan spec into records that predate R-19.

    Records created before R-19 carry only ``plan_file``, and the plan files
    were deleted in the commit that introduced the spec. This recovers each
    record's plan from ``--rev`` in git — reproducible in any clone — or from
    the working tree for plans added after that revision.

    By default the live queue is backfilled.  Pass ``--history-file`` to
    backfill the settled history log instead; the rewrite is atomic and touches
    only the ``spec`` key on existing records.
    """
    repo_root = queue_repo_root(args.queue) or os.path.dirname(
        os.path.abspath(args.queue)
    )
    history_file = getattr(args, "history_file", None)

    if history_file:
        history_path = _resolve_history_path(history_file, repo_root)
        records = queue_lib.read_history(history_path)
    else:
        backend = make_backend(args.queue)
        backend.fetch()
        data = backend.load(verify=False)
        records = data["queue"]

    if not args.apply:
        preview = json.loads(json.dumps(records))
        result = spec_backfill.backfill_specs(
            preview, rev=args.rev, repo_root=repo_root
        )
        _report_backfill(result, args.rev, applied=False, records=preview)
        return 0

    if not queue_lib.lease_guard(args.queue, force=getattr(args, "force", False)):
        return queue_lib.LEASE_HELD_EXIT_CODE

    with queue_lib.queue_lock(args.queue):
        # Re-load under the lock in case another process changed the file.
        if history_file:
            records = queue_lib.read_history(history_path)
        else:
            data = backend.load(verify=False)
            records = data["queue"]
        result = spec_backfill.backfill_specs(
            records, rev=args.rev, repo_root=repo_root
        )
        if result.filled:
            if history_file:
                _write_history_file(history_path, records)
            else:
                backend.save(records)
                backend.push()

    _report_backfill(result, args.rev, applied=True, records=records)
    return 0


def _report_backfill(result, rev, applied, records=None):
    """Print what the backfill did, naming every task it could not recover."""
    prefix = "" if applied else "[dry-run] Would backfill: "
    if not result.rev_available:
        print(
            f"⚠️  Revision {rev} does not resolve in this clone; only plans "
            "still on disk or in the archive can be recovered.",
            file=sys.stderr,
        )
    if result.filled:
        if applied:
            print(f"Backfilled {len(result.filled)} record(s) from {rev}:")
            for task_id in result.filled:
                print(f"  ✓ {task_id}")
        else:
            print(prefix + ", ".join(result.filled))
    elif not result.skipped:
        print(
            "Spec backfill: nothing to backfill "
            f"({len(result.already)} already carry a spec)."
        )
    else:
        print(
            f"Spec backfill: recovered nothing "
            f"({len(result.already)} already carry a spec)."
        )

    if records is not None:
        carrying_size = sum(
            1
            for r in records
            if isinstance(r.get("spec"), dict)
            and r["spec"].get("frontmatter", {}).get("size") is not None
        )
        print(
            f"Records carrying spec.frontmatter.size: {carrying_size}/{len(records)}"
        )

    for task_id, reason in result.skipped:
        print(f"⚠️  Skipped {task_id}: {reason}", file=sys.stderr)
    if result.skipped:
        print(
            f"⚠️  {len(result.skipped)} record(s) have no recoverable plan; "
            "they still carry no spec.",
            file=sys.stderr,
        )


def cmd_transition(args):
    backend = make_backend(args.queue)
    backend.fetch()
    cwd = os.path.dirname(args.queue) if args.queue else "."
    trunk_branch = _resolve_trunk(args.queue)

    if not queue_lib.lease_guard(args.queue, force=getattr(args, "force", False)):
        return queue_lib.LEASE_HELD_EXIT_CODE

    with queue_lib.queue_lock(args.queue):
        data = backend.load()
        queue = data["queue"]
        task = find_task(queue, args.task_id)
        if not task:
            print(f"Task not found: {args.task_id}", file=sys.stderr)
            return 1

        integration_branch = _resolve_integration_for_task(args.queue, task).ref

        if args.dry_run:
            ok, msg = validate_transition(
                task,
                args.from_stage,
                args.to_stage,
                cwd=cwd,
                trunk_branch=trunk_branch,
                integration_branch=integration_branch,
            )
            if ok:
                print(f"[dry-run] Would transition {args.task_id} {args.from_stage} -> {args.to_stage}")
                return 0
            print(msg, file=sys.stderr)
            return 1

        evidence = {"reason": args.reason} if args.reason else None
        try:
            _apply_transition(
                backend, queue, task, args.from_stage, args.to_stage,
                by="transition", evidence=evidence, cwd=cwd,
                trunk_branch=trunk_branch,
                integration_branch=integration_branch,
            )
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1

    # Replicate the transition to the forge remote; otherwise a later
    # fetch-on-read command silently reverts the local ref (see
    # docs/bugs/2026-08-14-aet-state-transition-does-not-push-refs.md).
    backend.push()

    print(f"Transitioned {args.task_id}: {args.from_stage} -> {args.to_stage}")
    return 0


def cmd_record_merge(args):
    """Resolve and record the merge commit for a task atomically."""
    backend = make_backend(args.queue)
    backend.fetch()
    cwd = os.path.dirname(args.queue) if args.queue else "."
    trunk_branch = _resolve_trunk(args.queue)

    if not queue_lib.lease_guard(args.queue, force=getattr(args, "force", False)):
        return queue_lib.LEASE_HELD_EXIT_CODE

    # Load task. If a previous record-merge already transitioned the task to
    # merged, the durable outcome is already recorded; plan files are no longer
    # committed or pushed by this command (R-4, R-19).
    with queue_lib.queue_lock(args.queue):
        task, sealed_task = resolve_task_record(
            args.task_id, args.queue, backend=backend
        )
        if not task and not sealed_task:
            print(f"Task not found: {args.task_id}", file=sys.stderr)
            return 1

        if task:
            integration_branch = _resolve_integration_for_task(
                args.queue, task, cli_base=getattr(args, "target_branch", None)
            ).ref
        else:
            integration_branch = getattr(args, "target_branch", None) or _resolve_integration(args.queue)

    if sealed_task:
        # Plan footer updates and archival are no longer part of the closure
        # transaction (R-4, R-19); the merge record itself is the durable outcome.
        print(
            f"Recorded merge for {args.task_id}: "
            f"{sealed_task.get('merge_commit')} ({sealed_task.get('merge_strategy')})"
        )
        return 0

    # Resolve the merge commit against git before touching the queue.
    branch = getattr(args, "branch", None)
    cli_merge_commit = getattr(args, "merge_commit", None)

    # Fetch origin first.
    rc, _, err = run_git("fetch", "origin", cwd=cwd)
    if rc != 0:
        print(f"git fetch origin failed: {err}", file=sys.stderr)
        return 1

    if cli_merge_commit:
        candidate_merge_commit = cli_merge_commit
    elif task.get("merge_commit"):
        candidate_merge_commit = task["merge_commit"]
    else:
        candidate_merge_commit = None

    if candidate_merge_commit:
        if not is_ancestor_of_target(candidate_merge_commit, integration_branch, cwd=cwd):
            print(
                f"Merge verification failed: {candidate_merge_commit} is not an ancestor "
                f"of origin/{integration_branch}.",
                file=sys.stderr,
            )
            return 1
        merge_commit = candidate_merge_commit
        merge_strategy = task.get("merge_strategy") or "manual"
    else:
        branch = branch or task.get("branch")
        if not branch:
            print(f"Task {args.task_id} has no branch. Use --branch or --merge-commit.", file=sys.stderr)
            return 1
        merge_commit, merge_strategy, _match_kind = resolve_merge_commit(
            branch,
            cwd=cwd,
            trunk_branch=trunk_branch,
            target_branch=integration_branch,
            base_commit=task.get("base_commit"),
        )

    if not merge_commit:
        print(
            f"Merge verification failed: could not determine merge commit on origin/{integration_branch}.",
            file=sys.stderr,
        )
        return 1

    with queue_lib.queue_lock(args.queue):
        # Re-load in case another process changed the queue while we talked to git.
        data = backend.load()
        queue = data["queue"]
        task = find_task(queue, args.task_id)
        if not task:
            print(f"Task not found: {args.task_id}", file=sys.stderr)
            return 1

        current_state = queue_lib.current_state(task)
        previous_merge_commit = task.get("merge_commit")
        previous_merge_strategy = task.get("merge_strategy")
        previous_branch = task.get("branch")
        task["merge_commit"] = merge_commit
        task["merge_strategy"] = merge_strategy
        if branch and task.get("branch") != branch:
            task["branch"] = branch

        if args.dry_run:
            ok, msg = validate_transition(
                task,
                current_state,
                "merged",
                cwd=cwd,
                trunk_branch=trunk_branch,
                integration_branch=integration_branch,
            )
            if ok:
                print(
                    f"[dry-run] Would record merge for {args.task_id}: "
                    f"{merge_commit} ({merge_strategy})"
                )
                return 0
            task["merge_commit"] = previous_merge_commit
            task["merge_strategy"] = previous_merge_strategy
            task["branch"] = previous_branch
            print(msg, file=sys.stderr)
            return 1

        evidence = {"merge_commit": merge_commit, "merge_strategy": merge_strategy}
        try:
            _apply_transition(
                backend, queue, task, current_state, "merged",
                by="record-merge", evidence=evidence, cwd=cwd,
                trunk_branch=trunk_branch,
                integration_branch=integration_branch,
            )
        except RuntimeError as e:
            task["merge_commit"] = previous_merge_commit
            task["merge_strategy"] = previous_merge_strategy
            task["branch"] = previous_branch
            print(str(e), file=sys.stderr)
            return 1

    try:
        backend.push(mandatory=True)
    except backend.RefsPushError as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        # Shadow posture explicitly exempts the mandatory closure push
        # (ADR-055 decision 8). The local record is intact; only remote
        # replication is skipped, so the closure itself succeeds.
        if backend.posture == SHADOW_POSTURE:
            print(f"Recorded merge for {args.task_id}: {merge_commit} ({merge_strategy})")
            return 0
        return 1

    print(f"Recorded merge for {args.task_id}: {merge_commit} ({merge_strategy})")
    return 0


def cmd_reconcile(args):
    """Report and optionally remove local refs stranded by the pre-tombstone scheme.

    Compares local ``refs/aet/tasks/*`` against ``origin`` using ``ls-remote``
    (no fetch, no prune). A local task ref with a remote tombstone but no local
    tombstone is stranded — sealed elsewhere and still visible on this clone.
    A local task with no origin counterpart and no remote tombstone is a
    genuinely unpushed local task and is never offered for removal.

    This command only mutates the local clone. It deliberately does not push
    deletions to origin: cleaning origin from a stale clone is how tasks have
    been resurrected in the past (R-6, ADR-055).
    """
    backend = make_backend(args.queue)
    if not isinstance(backend, GitRefsBackend):
        print(
            "reconcile is only supported for the git-refs backend.",
            file=sys.stderr,
        )
        return 1

    candidates = backend.reconcile_candidates()
    stranded = candidates["stranded"]
    unpushed = candidates["unpushed"]

    if not stranded and not unpushed:
        print("No stranded refs found.")
        return 0

    if not args.apply:
        if stranded:
            print("Stranded refs that would be removed:")
            for task_id in sorted(stranded):
                print(
                    f"  {task_id}: sealed elsewhere (remote tombstone exists)"
                )
        if unpushed:
            print("Unpushed local tasks that would be kept:")
            for task_id in sorted(unpushed):
                print(
                    f"  {task_id}: no origin counterpart and no remote tombstone"
                )
        return 0

    if not queue_lib.lease_guard(args.queue, force=getattr(args, "force", False)):
        return queue_lib.LEASE_HELD_EXIT_CODE

    removed: list[str] = []
    with queue_lib.queue_lock(args.queue):
        # Re-evaluate under the lock; remote state may have changed.
        candidates = backend.reconcile_candidates()
        for task_id in sorted(candidates["stranded"]):
            if backend.delete_task_ref(task_id):
                removed.append(task_id)

    if removed:
        print(f"Removed {len(removed)} stranded ref(s):")
        for task_id in removed:
            print(f"  {task_id}")
    else:
        print("No stranded refs found.")

    kept = candidates.get("unpushed", set())
    if kept:
        print("Kept unpushed local task(s):")
        for task_id in sorted(kept):
            print(f"  {task_id}")

    return 0


app = typer.Typer()


@app.command("audit")
def audit(
    queue: Optional[str] = typer.Argument(".agents/aet-queue", help="Path to queue anchor."),
) -> None:
    """Reconcile stored state against git without mutating."""
    args = argparse.Namespace(queue=queue)
    rc = cmd_audit(args)
    raise typer.Exit(rc)


@app.command("heal")
def heal(
    queue: Optional[str] = typer.Argument(
        ".agents/aet-queue", help="Path to queue anchor."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Apply proposed changes; otherwise dry-run."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override a live run lease and mutate the queue anyway (with a warning).",
    ),
) -> None:
    """Reconcile stored state against git and apply safe fixes."""
    args = argparse.Namespace(queue=queue, apply=apply, force=force)
    try:
        rc = cmd_heal(args)
    except _INTEGRITY_ERRORS as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        raise typer.Exit(1)
    raise typer.Exit(rc)


@app.command("validate")
def validate(
    task_id: str = typer.Argument(..., help="Task ID."),
    from_stage: str = typer.Argument(..., help="Current stage."),
    to_stage: str = typer.Argument(..., help="Target stage."),
    queue: Optional[str] = typer.Argument(".agents/aet-queue", help="Path to queue anchor."),
) -> None:
    """Check if a transition is legal."""
    args = argparse.Namespace(task_id=task_id, from_stage=from_stage, to_stage=to_stage, queue=queue)
    try:
        rc = cmd_validate(args)
    except _INTEGRITY_ERRORS as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        raise typer.Exit(1)
    raise typer.Exit(rc)


@app.command("reset")
def reset(
    task_id: str = typer.Argument(..., help="Task ID."),
    queue: Optional[str] = typer.Argument(
        ".agents/aet-queue", help="Path to queue anchor."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Apply the reset; otherwise dry-run."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override a live run lease and mutate the queue anyway (with a warning).",
    ),
) -> None:
    """Recompute a task from git and blockers, reset to ready/blocked, clear stale runtime fields."""
    args = argparse.Namespace(
        command="reset", task_id=task_id, queue=queue, apply=apply, force=force
    )
    try:
        rc = cmd_reset(args)
    except _INTEGRITY_ERRORS as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        raise typer.Exit(1)
    raise typer.Exit(rc)


@app.command("backfill-specs")
def backfill_specs(
    queue: Optional[str] = typer.Argument(
        ".agents/aet-queue", help="Path to queue anchor."
    ),
    rev: str = typer.Option(
        spec_backfill.DEFAULT_SOURCE_REV,
        "--rev",
        help="Git revision that still carries the plan files.",
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write the recovered specs; otherwise dry-run."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override a live run lease and mutate the queue anyway (with a warning).",
    ),
    history_file: Optional[str] = typer.Option(
        None,
        "--history-file",
        help="Backfill settled history JSONL instead of the live queue.",
    ),
) -> None:
    """Backfill the portable plan spec into records that predate R-19."""
    args = argparse.Namespace(
        queue=queue, rev=rev, apply=apply, force=force, history_file=history_file
    )
    try:
        rc = cmd_backfill_specs(args)
    except _INTEGRITY_ERRORS as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        raise typer.Exit(1)
    raise typer.Exit(rc)


@app.command("transition")
def transition(
    task_id: str = typer.Argument(..., help="Task ID."),
    from_stage: str = typer.Argument(..., help="Current stage."),
    to_stage: str = typer.Argument(..., help="Target stage."),
    queue: Optional[str] = typer.Argument(
        ".agents/aet-queue", help="Path to queue anchor."
    ),
    reason: Optional[str] = typer.Option(
        None, "--reason", help="Reason for transition (used as history evidence)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show changes without applying them."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override a live run lease and mutate the queue anyway (with a warning).",
    ),
) -> None:
    """Validate legality, then apply state change."""
    args = argparse.Namespace(
        task_id=task_id,
        from_stage=from_stage,
        to_stage=to_stage,
        queue=queue,
        reason=reason,
        dry_run=dry_run,
        force=force,
    )
    try:
        rc = cmd_transition(args)
    except _INTEGRITY_ERRORS as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        raise typer.Exit(1)
    raise typer.Exit(rc)


@app.command("set-stage")
def set_stage(
    task_id: str = typer.Argument(..., help="Task ID."),
    stage: str = typer.Argument(..., help="Pipeline stage to record."),
    queue: Optional[str] = typer.Argument(
        ".agents/aet-queue", help="Path to queue anchor."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show changes without applying them."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override a live run lease and mutate the queue anyway (with a warning).",
    ),
) -> None:
    """Set the pipeline stage sub-state for an in-progress task."""
    args = argparse.Namespace(task_id=task_id, stage=stage, queue=queue, dry_run=dry_run, force=force)
    try:
        rc = cmd_set_stage(args)
    except _INTEGRITY_ERRORS as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        raise typer.Exit(1)
    raise typer.Exit(rc)


@app.command("record-merge")
def record_merge(
    task_id: str = typer.Argument(..., help="Task ID."),
    queue: Optional[str] = typer.Argument(
        ".agents/aet-queue", help="Path to queue anchor."
    ),
    branch: Optional[str] = typer.Option(
        None,
        "--branch",
        help="Branch name to use for merge verification. Overrides the task's branch field.",
    ),
    merge_commit: Optional[str] = typer.Option(
        None,
        "--merge-commit",
        help="Merge commit SHA to record directly. Must be an ancestor of origin/<target-branch>.",
    ),
    target_branch: Optional[str] = typer.Option(
        None,
        "--target-branch",
        help="Branch to verify the merge against. Defaults to the configured integration branch.",
    ),
    plan: Optional[str] = typer.Option(
        None,
        "--plan",
        help="Deprecated and ignored: plan footer writes were removed (R-4/R-19).",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show changes without applying them."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override a live run lease and mutate the queue anyway (with a warning).",
    ),
) -> None:
    """Resolve and record the merge commit for a task."""
    args = argparse.Namespace(
        task_id=task_id,
        queue=queue,
        branch=branch,
        merge_commit=merge_commit,
        target_branch=target_branch,
        plan=plan,
        dry_run=dry_run,
        force=force,
    )
    try:
        rc = cmd_record_merge(args)
    except _INTEGRITY_ERRORS as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        raise typer.Exit(1)
    raise typer.Exit(rc)


@app.command("reconcile")
def reconcile(
    queue: Optional[str] = typer.Argument(
        ".agents/aet-queue", help="Path to queue anchor."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Remove stranded refs; otherwise dry-run."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override a live run lease and mutate the queue anyway (with a warning).",
    ),
) -> None:
    """Report/remove local refs stranded by the old model. Local-only; never touches origin."""
    args = argparse.Namespace(queue=queue, apply=apply, force=force)
    try:
        rc = cmd_reconcile(args)
    except _INTEGRITY_ERRORS as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        raise typer.Exit(1)
    raise typer.Exit(rc)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        return app(argv, standalone_mode=False)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    except Exception as exc:
        if hasattr(exc, "exit_code"):
            return int(exc.exit_code)
        raise


if __name__ == "__main__":
    app()
