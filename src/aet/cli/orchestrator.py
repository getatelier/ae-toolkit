"""Unified orchestrator for the Agentic Engineering Toolkit.

Usage:
    orchestrator --queue-file .agents/aet-queue
    orchestrator --plan-file docs/plans/FEAT-001-plan.md

Daemonization design (Open Question #3, nc-06-run-daemonization):

The orchestrator itself is process-attachment-agnostic: it reads stdin/stdout
normally and relies on the dispatcher to decide whether to wait for it.  When
invoked with ``--log-file`` the orchestrator redirects its own stdout/stderr to
that file so the log is authoritative even if the parent dispatcher exits.  The
dispatcher performs the actual detach by spawning the orchestrator with
``subprocess.Popen(..., start_new_session=True)`` and immediately returning.
This keeps all fork/session-leader logic in one place (the dispatcher) while the
orchestrator remains a well-behaved Python program that can still be run
interactively for debugging.

Run metadata lives under ``.agents/runs/<run-id>/``:

* ``output.log`` — stdout/stderr of the orchestrator
* ``pid`` — orchestrator pid, written after startup
* ``started`` — ISO timestamp

The per-task ``--task-timeout`` wall-clock backstop remains overridable; the
stall interval is resolved from the active ``CLIAdapter`` and enforced by
hybrid liveness (process-tree activity + run-log/file writes) rather than
stdout silence (ADR-053, superseded in part by the liveness redesign).
"""

from __future__ import annotations

import argparse
import collections
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Collection
from pathlib import Path
from typing import Any, Optional

import typer

_SCRIPT_DIR = Path(__file__).resolve().parent
from aet import (  # noqa: E402
    breaker,
    divergence,
    evidence,
    gate,
    handoff,
    liveness,
    plan_parser,
    plan_size,
    session_log,
    telemetry,
    track_record,
    triage,
    validation,
)
from aet import failure as failure_lib  # noqa: E402
from aet import usage as usage_lib  # noqa: E402
from aet.backends.factory import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    SHADOW_POSTURE,
    create_backend,
    resolve_config,
    resolve_integration_mode,
    resolve_posture,
)
from aet.branch_ref import (  # noqa: E402
    resolve_base_ref,
    resolve_integration_branch,
    resolve_integration_branch_for_task,
    resolve_trunk_branch,
)
from aet.cli_adapter import resolve_cli_adapter  # noqa: E402
from aet.integration_lock import (  # noqa: E402
    IntegrationFailureError,
    integration_lock,
)
from aet.queue import (  # noqa: E402
    LEASE_HELD_EXIT_CODE,
    LEGAL_TRANSITIONS,
    LeaseHeldError,
    QueueIntegrityError,
    acquire_lease,
    current_state,
    get_next_unblocked,
    queue_lock,
    record_task_meta,
    release_lease,
    resolve_base_commit,
)
from aet.queue import (  # noqa: E402
    has_pending_tasks as queue_has_pending_tasks,
)
from aet.verifier import (  # noqa: E402
    read_plan_stage,
    verify_branch_has_commits,
    verify_stage_advancement,
)
from aet.workflow import Workflow, WorkflowError, WorkflowStage, load_workflow  # noqa: E402
from aet.worktree import (  # noqa: E402
    WorktreeBlockedError,
    _format_paths,
    check_base_hygiene,
    copy_untracked_files,
    create_worktree,
    delete_local_branch,
    prepare_worktree_dependencies,
    push_branch,
    render_task_plan,
    run_git_plain,
    teardown_worktree,
)


def _task_in_queue(backend, task_id: str) -> bool:
    """Return True when ``task_id`` is present in the backend's live queue."""
    try:
        queue = backend.load()["queue"]
    except Exception:
        return False
    return any(t.get("id") == task_id for t in queue)


# Global shutdown flag
_shutdown_requested = False


class LeaseRefusedError(Exception):
    """Raised when a queue write is refused because another run owns the queue.

    This is not a failure of the work. The commits are on the branch and the
    verdicts are on disk; only the record could not be written. Callers abort
    the task and leave its recorded state untouched, so it resumes once the
    lease clears instead of being marked failed for a write it never got to do.
    """


class MissingPlanError(Exception):
    """Raised when the resolved base branch does not contain the plan file."""

    def __init__(self, base_branch: str, plan_file: str) -> None:
        self.base_branch = base_branch
        self.plan_file = plan_file
        super().__init__(
            f"⛔ Plan not found in worktree — resolved base `{base_branch}` "
            f"does not contain `{plan_file}`. Override with "
            f"`--base <branch>` or `AET_WORK_BASE_BRANCH=<branch>`."
        )


def _handle_signal(signum: int, _frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    print(f"\n⚠️  Received signal {signum}. Shutting down gracefully...")


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def _killpg(pid: int, sig: int) -> None:
    """Send a signal to the process group led by pid, ignoring stale targets."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _terminate_process_group(proc: subprocess.Popen, timeout: float = 10) -> None:
    """Escalate from SIGTERM to SIGKILL for a process group."""
    if proc.poll() is not None:
        return
    _killpg(proc.pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    _killpg(proc.pid, signal.SIGKILL)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _make_backend(queue_file: str):
    """Create a task backend for the given queue file.

    The history file is derived from the queue file path so the backend pair
    stays consistent regardless of where the queue lives.
    """
    history_file = str(Path(queue_file).with_name("work-history.jsonl"))
    config_path = str(Path(queue_file).with_name("aet-config.json"))
    return create_backend(
        config_path=config_path, queue_file=queue_file, history_file=history_file
    )


def _save_task_record(backend, queue: list[dict]) -> None:
    """Persist a direct task-record write and replicate it in the same breath.

    Every ``aet state`` invocation fetches ``+refs/aet/*:refs/aet/*`` before it
    does anything else (``cli/aet_state.py:113``), and the leading ``+`` makes
    that a force-reset of each local task ref to origin's copy. The refspec is
    coherent for a store whose only writer is ``aet state``, because ``aet
    state`` pushes after saving; it discards the work of any other writer that
    does not.

    The orchestrator is that other writer. A record saved here and left
    unreplicated is overwritten by the next transition, which is how a task
    requeued 22 times while the per-task breaker never counted past one
    (``docs/bugs/20260828-fetch-discards-unpushed-record-writes.md``). Pushing
    is what makes the write survive, so every direct write goes through here.

    The push is best-effort, as elsewhere: it is a no-op in shadow posture and
    with no remote, both of which return success. A genuine push failure leaves
    the write local, where the next fetch will drop it, so it is reported rather
    than swallowed — silent loss is the defect this function exists to close.
    """
    backend.save(queue)
    try:
        replicated = backend.push()
    except Exception as exc:  # noqa: BLE001 - a read-only remote must not fail a run
        replicated = False
        print(f"   ⚠️  Could not replicate the task record: {exc}")
    # Only an explicit False is a failure: the interface returns bool, and a
    # stub backend that returns nothing must not raise a false alarm.
    if replicated is False:
        print(
            "   ⚠️  Task record saved locally but not pushed; the next "
            "`aet state` fetch will discard it."
        )


def _runs_dir(repo_root: str) -> Path:
    """Return the canonical directory for detached-run metadata."""
    return Path(repo_root) / ".agents" / "runs"


def _run_dir(repo_root: str, run_id: str) -> Path:
    """Return the per-run metadata directory for ``run_id``."""
    return _runs_dir(repo_root) / run_id


def _write_run_metadata(repo_root: str, run_id: str) -> None:
    """Persist pid and started timestamp for an active detached run.

    Best-effort: any filesystem failure is logged but does not block the run.
    """
    rdir = _run_dir(repo_root, run_id)
    try:
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "pid").write_text(str(os.getpid()), encoding="utf-8")
        (rdir / "started").write_text(telemetry.iso_now(), encoding="utf-8")
    except OSError as exc:
        print(f"   ⚠️  Could not write run metadata for {run_id}: {exc}")


def _write_telemetry_path(
    repo_root: str, run_id: str, telemetry_run_dir: Path
) -> None:
    """Persist the telemetry run directory path so the follower can find it."""
    rdir = _run_dir(repo_root, run_id)
    try:
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "telemetry_dir").write_text(str(telemetry_run_dir), encoding="utf-8")
    except OSError as exc:
        print(f"   ⚠️  Could not write telemetry path for {run_id}: {exc}")


def _write_returncode(repo_root: str, run_id: str, exit_code: int) -> None:
    """Persist the orchestrator's exit code so ``aet run --follow`` can mirror it.

    Best-effort: any filesystem failure is logged but does not block the run.
    """
    rc_file = _run_dir(repo_root, run_id) / "returncode"
    try:
        rc_file.parent.mkdir(parents=True, exist_ok=True)
        rc_file.write_text(str(exit_code), encoding="utf-8")
    except OSError as exc:
        print(f"   ⚠️  Could not write returncode for {run_id}: {exc}")


def _redirect_output(log_file: str | None) -> None:
    """Redirect stdout/stderr to ``log_file`` when in detached-run mode.

    The original stdout/stderr file descriptors are duplicated so tracebacks
    during early startup still have somewhere to go.  ``log_file`` is created
    if it does not exist and appended to if it does (supports ``--follow`` on
    a restarted run).
    """
    if not log_file:
        return
    try:
        # Ensure the log directory exists before reopening fds.
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        log = open(log_file, "a", buffering=1, encoding="utf-8")
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(log.fileno(), sys.stdout.fileno())
        os.dup2(log.fileno(), sys.stderr.fileno())
        # Keep the file object alive so the interpreter does not close the fd.
        sys._aet_run_log = log  # type: ignore[attr-defined]
    except OSError as exc:
        print(f"   ⚠️  Could not redirect output to {log_file}: {exc}", file=sys.stderr)



def read_plan_pipeline(plan_data: dict[str, Any]) -> str | None:
    """Return the pipeline mode from parsed frontmatter, if valid."""
    value = plan_data.get("pipeline")
    if isinstance(value, str) and value in ("minimal", "standard", "full"):
        return value
    return None


def effective_isolation(plan_data: dict[str, Any], cli_isolation: str) -> str:
    """Return the isolation level for a task.

    Plan frontmatter takes precedence; the CLI flag is the fallback.
    """
    plan_isolation = read_plan_pipeline(plan_data)
    return plan_isolation if plan_isolation else cli_isolation


def get_current_stage(task: dict, plan_file: str, entry_stage: str) -> str:
    """Return the current pipeline stage from the task record.

    The footer is consulted only as a backward-compatible fallback; it is
    never used to make scheduling decisions (ADR-011). With no record and no
    footer the task starts at the workflow's entry stage.
    """
    return task.get("stage") or read_plan_stage(plan_file) or entry_stage


def _record_stage(task: dict, stage: str, repo_root: str) -> bool:
    """Persist an advanced pipeline stage to the task record.

    When the task is tracked in the work queue, this routes through
    ``aet-state set-stage`` so the sole-writer rule is preserved.  Otherwise
    the in-memory task dict is updated directly (single-plan mode without a
    queue).
    """
    task_id = task.get("id")
    if not task_id:
        task["stage"] = stage
        return True

    # git-refs backend: a tracked task has a ref under refs/aet/tasks/.
    task_ref = f"refs/aet/tasks/{task_id}"
    ref_check = subprocess.run(
        ["git", "-C", repo_root, "rev-parse", "--verify", "-q", task_ref],
        capture_output=True,
        text=True,
    )
    if ref_check.returncode != 0:
        # Task is not tracked in the queue; update in-memory only.
        task["stage"] = stage
        return True

    queue_file = os.path.join(repo_root, ".agents", "aet-queue")
    aet_state_bin = str(_SCRIPT_DIR / "aet_state.py")
    result = subprocess.run(
        [
            sys.executable,
            aet_state_bin,
            "set-stage",
            task_id,
            stage,
            queue_file,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        task["stage"] = stage
        return True
    if result.returncode == LEASE_HELD_EXIT_CODE:
        # The queue is owned by another run. This says nothing about the work,
        # so it must not be reported as a failure of the work: the caller
        # aborts the task and leaves its recorded state untouched.
        raise LeaseRefusedError(
            f"Cannot record stage '{stage}' for {task_id}: "
            f"{result.stderr.strip() or 'the queue is owned by another run'}"
        )
    print(f"   ⚠️  Could not set stage for {task_id}: {result.stderr.strip()}")
    return False


def enforce_base_hygiene(
    repo_root: str, integration_branch: str, trunk_branch: str
) -> bool:
    """Check base hygiene and decide whether to proceed.

    Returns True when the caller should continue, False when it should halt.
    Base hygiene is a mechanical durability check (see ADR-005/ADR-027/ADR-044):
    a real violation halts in both interactive and unattended mode so an AFK
    run never builds an empty worktree off a dirty or unpushed base.
    """
    ok, msg = check_base_hygiene(repo_root, integration_branch, trunk_branch)
    if ok:
        return True

    print(f"⛔ {msg}. Halting.")
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AE Toolkit Unified Orchestrator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--queue-file", help="Path to queue anchor (batch mode)")
    group.add_argument("--plan-file", help="Path to a single plan.md (single-plan mode)")
    parser.add_argument("--repo-root", default=os.getcwd(), help="Repository root path")
    parser.add_argument(
        "--cli-bin",
        default=None,
        help=(
            "Agent CLI binary path. Defaults to the agent CLI that invoked aet; "
            "required when no agent CLI is detected."
        ),
    )
    parser.add_argument(
        "--base",
        default=None,
        help="Override the worktree base branch/ref (default: origin/main or AET_WORK_BASE_BRANCH).",
    )
    parser.add_argument("--isolation", default="standard", choices=["minimal", "standard", "full"])
    parser.add_argument("--max-jobs", type=int, default=4, help="Max parallel tasks (batch mode)")
    parser.add_argument(
        "--task-timeout",
        type=int,
        default=None,
        help="Per-task wall-clock timeout in seconds (default: adapter wall backstop).",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=60,
        help="Seconds between heartbeat log lines (default: 60).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run identifier used for telemetry and run metadata.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Redirect stdout/stderr to this file (detached-run mode).",
    )
    parser.add_argument(
        "--on-failure",
        choices=["triage", "continue", "halt"],
        default="triage",
        help=(
            "What to do when a task fails in batch mode: triage (default) "
            "requeues transient failures; continue marks failed and keeps "
            "spawning; halt stops the shift on the first failure."
        ),
    )
    parser.add_argument(
        "--skip-intake",
        action="store_true",
        help=(
            "Run a plan that fails intake validation. The bypassed check ids "
            "are recorded on the task record, so the audit trail says the task "
            "did not pass intake."
        ),
    )
    return parser


def parse_args(argv) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _freshness_clause(decision: str) -> str:
    """Prompt text that modulates the 'run validations' instruction.

    Empty for RUN or unknown — validations run as normal. For a fresh QA
    verdict it tells the stage to trust that verdict instead of re-running the
    suite on a tree QA already proved green: the F2 dedup, decided in code and
    obeyed in prose.
    """
    if decision == evidence.SKIP:
        return (
            " The toolkit verified the working tree is UNCHANGED since QA"
            " validated it green: trust the QA verdict and do NOT re-run the"
            " test suite to reconfirm it. Run validations only if you modify"
            " code in this stage; if you do, re-run full validation before"
            " finishing."
        )
    if decision == evidence.LINT_ONLY:
        return (
            " The toolkit verified only non-code files changed since QA"
            " validated the tree green: run lint/format checks only and do NOT"
            " re-run the test suite. If you modify code, re-run full validation"
            " before finishing."
        )
    return ""


def _qa_freshness_decision(
    task_id: str | None, repo_root: str, worktree_dir: str
) -> str:
    """Freshness of the QA verdict vs. the current worktree, or "" on any error.

    Never raises: a stage spawn must not hinge on this optimization. The
    worktree is hashed here, where the orchestrator knows the real path, rather
    than left for a stage session to resolve from env.
    """
    if not task_id:
        return ""
    try:
        result = evidence.validation_freshness(
            task_id,
            "qa",
            worktree_dir=worktree_dir,
            project_slug=telemetry.derive_project_slug(repo_root),
        )
        return result.decision
    except (OSError, ValueError):
        return ""


def _handoff_clause(repo_root: str, run_id: str | None) -> str:
    """Run handoff note prompt block for ``run_id``, or "" on any error.

    Never raises: a stage spawn must not hinge on run-scoped working memory.
    """
    if not run_id:
        return ""
    try:
        note = handoff.read_note(repo_root, run_id)
    except Exception:
        return ""
    if note is None:
        return ""
    try:
        block = handoff.render_prompt_block(note)
    except Exception:
        return ""
    return "\n\n" + block


def _targeted_tests_path(repo_root: str, run_id: str) -> Path:
    """Run-scoped file where ``aet-implement`` records its targeted tests."""
    return validation.targeted_tests_path(repo_root, run_id)


def _record_targeted_tests_handoff(repo_root: str, run_id: str, stage: str) -> None:
    """If implement wrote targeted-test commands, append them to the handoff.

    This passes the implement floor to QA so a later full-suite failure can be
    analyzed for gaps (R-8). The file is best-effort: a missing or malformed
    file is silently ignored.
    """
    path = _targeted_tests_path(repo_root, run_id)
    commands = validation.read_targeted_tests(path)
    if not commands:
        return
    try:
        handoff.append_entry(
            repo_root,
            run_id,
            stage=stage,
            validation_commands=commands,
        )
    except Exception:  # noqa: BLE001
        pass


def _stage_targeted_tests(
    repo_root: str,
    run_id: str | None,
    exit_code: int,
    should_record: bool = False,
) -> list[str] | None:
    """Read implement-targeted test commands when a stage session succeeded.

    Returns ``None`` when the session failed, no run id is available, or the
    stage did not involve ``aet-implement``. This keeps targeted tests attached
    only to the stage that produced them (R-8).
    """
    if not should_record or run_id is None or exit_code != 0:
        return None
    return validation.read_targeted_tests(_targeted_tests_path(repo_root, run_id))


def _implement_targeted_commands(
    logger: telemetry.RunLogger,
    task_id: str,
    repo_root: str | None = None,
) -> list[str]:
    """Return the targeted test commands recorded during the implement stage.

    Searches this run's telemetry for the stage record whose span includes
    ``implemented``. Falls back to the run-scoped ``implement-targeted-tests.json``
    file when no telemetry record exists yet (e.g., a group session failed before
    the stage record was emitted). Returns an empty list when neither source has
    data.
    """
    for record in telemetry.read_jsonl(logger.task_log_path(task_id)):
        if record.get("type") != "stage":
            continue
        actual_stages = record.get("actual_stages") or [record.get("stage")]
        if "implemented" in actual_stages:
            return record.get("targeted_tests") or []
    if repo_root is not None and logger.run_id is not None:
        return validation.read_targeted_tests(
            _targeted_tests_path(repo_root, logger.run_id)
        )
    return []


def _attach_gap_analysis_to_task(
    task: dict,
    backend,
    task_id: str | None,
    repo_root: str,
    logger: telemetry.RunLogger | None = None,
) -> None:
    """Best-effort: attach a QA gap analysis to the task's failure record.

    Reads the QA verdict for failed tests, compares them against the implement
    stage's targeted test set, and stores the result on the most recent failure
    signature entry (or appends a new entry if none exists).
    """
    if not task_id:
        return
    if logger is None:
        run_id = os.environ.get("AET_RUN_ID")
        logger = telemetry.RunLogger(repo_root, run_id=run_id)
    try:
        record = _load_checking_verdict(task_id, "qa", repo_root)
    except Exception:  # noqa: BLE001
        return
    failed_tests = record.get("failed_tests", [])
    if not failed_tests:
        return
    implement_commands = _implement_targeted_commands(logger, task_id, repo_root)
    analysis = validation.gap_analysis(failed_tests, implement_commands)
    if not analysis.get("missed_tests"):
        return
    sigs = task.setdefault("failure_signatures", [])
    if sigs:
        sigs[-1]["gap_analysis"] = analysis
    else:
        sigs.append(
            {
                "signature": failure_lib.signature(stage="qa", tail=str(analysis)),
                "class": failure_lib.FailureClass.DESIGN.value,
                "stage": "qa",
                "tail_preview": f"QA gap analysis: {analysis}",
                "gap_analysis": analysis,
                "at": telemetry.iso_now(),
            }
        )
    if backend is not None:
        try:
            queue = backend.load()["queue"]
            for qt in queue:
                if qt.get("id") == task.get("id"):
                    qt["failure_signatures"] = task.get("failure_signatures", [])
                    break
            _save_task_record(backend, queue)
        except Exception:  # noqa: BLE001
            pass


def _evidence_clause(kind: str, env_var: str) -> str:
    """Name the required verdict, its builder command, and its output path.

    The command comes from :func:`evidence.submit_command` so the prompt cannot
    drift from the CLI, and it is builder mode rather than
    ``--evidence <payload-file>``: an agent that hand-writes the JSON has to
    reproduce schema fields it cannot see, which is how payloads ended up
    missing required keys.
    """
    clause = (
        f"\n\nThis stage requires a {kind!r} verdict. Submit it with: "
        f"`{evidence.submit_command(kind, 'pass')}`. The required output path "
        f"is in `${env_var}`. The stage is not complete until the verdict is "
        f"written."
    )
    if kind == "qa":
        keys = ", ".join(evidence.QA_REPORT_MINIMAL_KEYS)
        clause += (
            f" For `--from-pytest`, a pytest-json-report file works, or write a "
            f"scratch JSON object with just: {keys}."
        )
    return clause


def build_prompt(
    skills: list[str],
    plan_file: str,
    current_stage: str,
    next_stage: str,
    freshness_clause: str = "",
    handoff_clause: str = "",
    verdict_kind: str | None = None,
) -> str:
    skills_str = " → ".join(skills)
    evidence_clause = ""
    if verdict_kind is not None:
        evidence_clause = _evidence_clause(verdict_kind, "AET_EVIDENCE_PATH")
    return (
        f"Run {skills_str} on {plan_file}\n"
        f"Current stage: {current_stage}. Target stage: {next_stage}.\n"
        f"Execute only this stage. Do not proceed to subsequent stages."
        f"{freshness_clause}{handoff_clause}{evidence_clause}\n"
        f"Commit your work before exiting."
    )


def _session_diff_stats(
    worktree_dir: str, base_ref: str = "origin/main"
) -> tuple[list[str], int]:
    """Return (files_modified, commits_created) for a worktree relative to base.

    Best-effort: any git failure yields an empty/zero result so telemetry
    emission never blocks a run.
    """
    files_modified: list[str] = []
    commits_created = 0

    diff = subprocess.run(
        ["git", "-C", worktree_dir, "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if diff.returncode == 0:
        files_modified = [line for line in diff.stdout.splitlines() if line]

    rev = subprocess.run(
        ["git", "-C", worktree_dir, "rev-list", "--count", f"{base_ref}..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if rev.returncode == 0:
        try:
            commits_created = int(rev.stdout.strip() or 0)
        except ValueError:
            commits_created = 0

    return files_modified, commits_created


def _plan_snapshot(plan_data: dict[str, Any]) -> dict[str, Any] | None:
    """Return a shallow snapshot of frontmatter fields used for routing.

    Captures ``size``, ``pipeline``, ``security_review``, ``docs_sync``, and
    ``aet_version`` when present. Returns ``None`` when no routing keys are
    available.
    """
    if not plan_data:
        return None
    snapshot: dict[str, Any] = {}
    for key in ("size", "pipeline", "security_review", "docs_sync", "aet_version"):
        if key in plan_data:
            snapshot[key] = plan_data[key]
    return snapshot if snapshot else None


def _next_attempt(logger: telemetry.RunLogger, task_id: str, stage: str) -> int:
    """Return the next attempt number for ``task_id`` + ``stage`` in this run.

    Attempts are counted from the stage records already emitted for this task
    in the current run. Existing records (legacy or otherwise) that lack an
    ``attempt`` field default to one attempt each.
    """
    count = 0
    for record in telemetry.read_jsonl(logger.task_log_path(task_id)):
        if record.get("type") != "stage":
            continue
        if record.get("stage") != stage:
            continue
        previous = record.get("attempt")
        if isinstance(previous, int) and previous > 0:
            count = max(count, previous)
        else:
            count = max(count, 1)
    return count + 1


def _bounded_output_excerpt(
    output: str,
    max_lines: int = telemetry.COMPLETION_REPORT_EXCERPT_LINES,
) -> str:
    """Return the last ``max_lines`` lines of captured session output."""
    lines = output.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines)


def _emit_stage_session(
    logger: telemetry.RunLogger,
    task_id: str,
    plan_file: str,
    agent_cli: str,
    isolation_level: str,
    stage: str,
    stages: list[str] | None,
    worktree_dir: str,
    start_time: str,
    end_time: str,
    exit_code: int,
    usage: dict | None = None,
    session_ref: str | None = None,
    base_branch: str = "origin/main",
    output: str = "",
    plan_data: dict[str, Any] | None = None,
    verdict_recorded: bool = False,
    targeted_tests: list[str] | None = None,
) -> None:
    """Emit one stage telemetry record for a completed agent session.

    ``usage`` is the parsed CLI usage dict (or ``None`` for CLIs without a
    usage mode); it populates ``token_count`` / ``cost_estimate`` on the
    record. Null is the honest value when usage was not measurable.

    ``session_ref`` is the adapter-resolved session identifier for the session
    (a session id for both kimi and Claude, ``None`` when unresolvable).
    When present, one observed ``test_run`` record is appended per extracted
    test invocation, tagged with the session's ``stage``.

    ``output`` is the captured session tail used to classify failures on the
    nsr-01 taxonomy. ``verdict_recorded`` is True when the failing session had
    already written an evidence verdict before failing.
    """
    files_modified, commits_created = _session_diff_stats(worktree_dir, base_branch)
    actual_stages = stages if stages is not None else [stage]
    failure_class: str | None = None
    if exit_code != 0:
        failure_class = _classify_failure(
            exit_code=exit_code,
            tail=output,
            stage=stage,
            verdict_recorded=verdict_recorded,
            shutdown=_shutdown_requested,
            killed_by_timeout=exit_code < 0,
        ).value
    logger.append_record(
        telemetry.stage_record(
            run_id=logger.run_id,
            task_id=task_id,
            plan_file=plan_file,
            stage=stage,
            agent_cli=agent_cli,
            isolation_level=isolation_level,
            start_time=start_time,
            end_time=end_time,
            exit_code=exit_code,
            files_modified=files_modified,
            commits_created=commits_created,
            stages=stages,
            actual_stages=actual_stages,
            failure_class=failure_class,
            plan_snapshot=_plan_snapshot(plan_data or {}),
            attempt=_next_attempt(logger, task_id, stage),
            token_count=usage.get("total_tokens") if usage else None,
            cost_estimate=usage.get("cost_usd") if usage else None,
            output_excerpt=(_bounded_output_excerpt(output) if exit_code != 0 else None),
            session_identifier=session_ref,
            targeted_tests=targeted_tests,
        ),
        task_id=task_id,
    )
    _emit_session_test_runs(
        logger, task_id, plan_file, stage, agent_cli, session_ref, worktree_dir
    )


def _emit_session_test_runs(
    logger: telemetry.RunLogger,
    task_id: str,
    plan_file: str,
    stage: str,
    agent_cli: str,
    session_ref: str | None,
    worktree_dir: str,
) -> None:
    """Append one ``test_run`` record per session-log test invocation.

    ``session_ref`` is an adapter-resolved session identifier. ``worktree_dir``
    is needed by the Claude reader to locate the transcript from the cwd slug.

    Best-effort, mirroring ``_session_diff_stats``: extraction is defensive,
    and any unexpected failure must never block a run.
    """
    if session_ref is None:
        return
    try:
        invocations = session_log.extract_test_invocations(
            agent_cli, session_ref, worktree_dir=worktree_dir
        )
    except Exception as exc:  # noqa: BLE001
        print(f"   ⚠️  Session test-run extraction failed (skipping): {exc}")
        return
    for invocation in invocations:
        logger.append_record(
            telemetry.test_run_record(
                run_id=logger.run_id,
                task_id=task_id,
                plan_file=plan_file,
                stage=stage,
                scope=telemetry.classify_test_scope(
                    invocation["command"], invocation.get("output")
                ),
                test_command=invocation["command"],
                source="wire",
                start_time=invocation["start_time"],
                end_time=invocation["end_time"],
                exit_code=invocation["exit_code"],
            ),
            task_id=task_id,
        )


def _usage_aggregates(logger: telemetry.RunLogger) -> tuple[int | None, float | None]:
    """Sum token/cost over this run's stage records; all-null -> ``(None, None)``.

    The ``work-history.jsonl`` copy is queue history, not execution telemetry,
    and is skipped (mirrors the panel's filtering).
    """
    total_tokens = 0
    total_cost = 0.0
    have_tokens = False
    have_cost = False
    for path in logger.run_dir.glob("*.jsonl"):
        if path.name == "work-history.jsonl":
            continue
        for record in telemetry.read_jsonl(path):
            if record.get("type") != "stage":
                continue
            if record.get("token_count") is not None:
                total_tokens += record["token_count"]
                have_tokens = True
            if record.get("cost_estimate") is not None:
                total_cost += record["cost_estimate"]
                have_cost = True
    return (total_tokens if have_tokens else None, total_cost if have_cost else None)


def _task_usage_aggregates(
    logger: telemetry.RunLogger, task_id: str
) -> tuple[int | None, float | None]:
    """Sum token/cost over ``task_id``'s stage records; all-null -> ``(None, None)``.

    Mirrors ``_usage_aggregates`` but filtered to a single task. The result is
    written to the task's ledger record at close and is analytics-only: no
    control path reads it (ADR-031).
    """
    total_tokens = 0
    total_cost = 0.0
    have_tokens = False
    have_cost = False
    path = logger.task_log_path(task_id)
    if not path.exists():
        return (None, None)
    for record in telemetry.read_jsonl(path):
        if record.get("type") != "stage":
            continue
        if record.get("task_id") != task_id:
            continue
        if record.get("token_count") is not None:
            total_tokens += record["token_count"]
            have_tokens = True
        if record.get("cost_estimate") is not None:
            total_cost += record["cost_estimate"]
            have_cost = True
    return (total_tokens if have_tokens else None, total_cost if have_cost else None)


def _load_checking_verdict(task_id: str, kind: str, repo_root: str) -> dict:
    """Read and schema-validate a checking verdict from the evidence home.

    Raises ``FileNotFoundError`` when the verdict is absent and
    ``evidence.VerdictValidationError`` / ``VerdictValueError`` when it is
    malformed.
    """
    path = evidence.evidence_path(
        task_id=task_id,
        kind=kind,
        project_slug=telemetry.derive_project_slug(repo_root),
    )
    record = evidence.read_verdict(path)
    evidence.validate_verdict(record, kind)
    return record


def _emit_test_run_from_verdict(
    logger: telemetry.RunLogger,
    record: dict,
    task_id: str,
    plan_file: str,
    stage: str,
) -> None:
    """Derive a ``test_run`` telemetry record from a passing qa verdict.

    The record is ``source: "verdict"`` — a claim, not a measurement (ADR-051).
    Nothing here was timed or observed, so ``exit_code`` stays null and the
    record reads ``result: "unknown"`` rather than restating the verdict's own
    pass as a green test run. Its value is the test counts, which no session log
    exposes.
    """
    test_command = record.get("test_command", "")
    logger.append_record(
        telemetry.test_run_record(
            run_id=logger.run_id,
            task_id=task_id,
            plan_file=plan_file,
            stage=stage,
            scope=telemetry.classify_test_scope(test_command),
            test_command=test_command,
            source="verdict",
            start_time=None,
            end_time=None,
            exit_code=None,
            tests_total=record.get("tests_total"),
            tests_passed=record.get("tests_passed"),
            tests_failed=record.get("tests_failed"),
        ),
        task_id=task_id,
    )


def _verdict_state(
    task_id: str, kind: str, repo_root: str
) -> tuple[str, dict | None, str]:
    """Classify a checking stage's verdict as pass / missing / invalid / fail.

    ``missing`` is the only recoverable state: the stage work exists and is
    committed, and the sole absent artifact is a file written outside the tree.
    ``invalid`` and ``fail`` are judgments the gate must not paper over.
    """
    try:
        record = _load_checking_verdict(task_id, kind, repo_root)
    except FileNotFoundError:
        path = evidence.evidence_path(
            task_id=task_id,
            kind=kind,
            project_slug=telemetry.derive_project_slug(repo_root),
        )
        return "missing", None, f"missing {kind} verdict (looked at {path})"
    except (evidence.VerdictValidationError, evidence.VerdictValueError) as exc:
        return "invalid", None, f"invalid {kind} verdict: {exc}"
    if record.get("verdict") != "pass":
        return "fail", record, f"{kind} verdict is {record.get('verdict')!r}"
    return "pass", record, ""


def _run_verdict_recovery(
    adapter,
    repo_root: str,
    plan_file: str,
    worktree_dir: str,
    task_id: str,
    kind: str,
    stage: str,
    logger: telemetry.RunLogger,
    stall_timeout: float | None,
    isolation: str,
    base_branch: str,
) -> None:
    """Spawn one narrow session whose only job is to write the missing verdict.

    A missing verdict file is often not a failed stage: the work is committed
    and the gate is refusing over an artifact that costs one command to
    produce. Discarding the whole stage and re-running it from scratch pays for
    the entire session again to recover a file. This asks once, for that file
    only, with no license to touch the tree.

    The prompt deliberately does **not** assert that the stage's work was
    completed. A group session can end having skipped a later stage entirely,
    so "verdict missing" and "stage never ran" are indistinguishable from here.
    Asserting completion would put a false premise in front of the agent and
    invite a fabricated pass; asking it to distinguish the two turns the
    ambiguity into a reported signal instead.

    The session is telemetry-visible as another attempt at the same stage, so
    recovery cost stays attributable and a stage that needs it every run is
    legible as a defect rather than hidden in a retry.
    """
    prompt = (
        f"The {stage} stage session for {task_id} has ended without writing "
        f"the required {kind!r} stage verdict, which the orchestrator gate is "
        f"fail-closed on.\n\n"
        f"Write that verdict now, and nothing else. Submit it with: "
        f"`{evidence.submit_command(kind)}`. The required output path is in "
        f"`$AET_EVIDENCE_PATH`.\n\n"
        f"First establish what actually happened, from the branch's commits and "
        f"the working tree — do not assume the stage completed. Then:\n"
        f"- If its work is complete, submit the verdict that work earned; if it "
        f"found blocking problems, that is `--verdict fail`.\n"
        f"- If the stage was not performed at all, submit `--verdict fail` with "
        f"a summary saying so. Do not pass a stage that did not run.\n\n"
        f"Do not modify, re-run, or commit anything in the repository; the "
        f"verdict file is written outside the working tree."
    )
    if kind == "qa":
        keys = ", ".join(evidence.QA_REPORT_MINIMAL_KEYS)
        prompt += (
            f"\n\nFor `--from-pytest`, use the test results already produced by "
            f"this stage: a pytest-json-report file, or a scratch JSON object "
            f"with just {keys}. Do not re-run the suite to obtain them unless "
            f"no record of the run survives."
        )

    cmd = adapter.build_cmd(prompt, workdir=worktree_dir, headless=True)
    env = os.environ.copy()
    env["AET_EXECUTION_MODE"] = "unattended"
    env["AET_ORCHESTRATOR_PID"] = str(os.getpid())
    env["AET_TASK_ID"] = task_id
    if logger.run_id is not None:
        env["AET_RUN_ID"] = logger.run_id
    env["AET_EVIDENCE_PATH"] = str(
        evidence.evidence_path(
            task_id=task_id,
            kind=kind,
            project_slug=telemetry.derive_project_slug(repo_root),
        )
    )

    print(f"   ↻ Verdict recovery: asking for the {kind} verdict only")
    start_time = telemetry.iso_now()
    exit_code, usage, session_ref, output = _spawn_session_with_tail(
        adapter, cmd, worktree_dir, env, stall_timeout=stall_timeout
    )
    end_time = telemetry.iso_now()
    _emit_stage_session(
        logger,
        task_id,
        plan_file,
        adapter.name,
        isolation,
        stage,
        None,
        worktree_dir,
        start_time,
        end_time,
        exit_code,
        usage=usage,
        session_ref=session_ref,
        base_branch=base_branch,
        output=output,
        verdict_recorded=False,
    )


def _credit_proven_stages(
    task: dict,
    runnable: list[WorkflowStage],
    workflow: Workflow,
    *,
    task_id: str,
    repo_root: str,
    worktree_dir: str,
    run_id: str | None,
) -> str | None:
    """Record the stages a failed group session proved it finished (ADR-069).

    A stage is credited only by its own schema-valid passing verdict, walking
    the group's span in order and stopping at the first stage that cannot be
    credited. A stage with no evidence binding is never credited: its artifact
    is commits, and a commit proves work happened, not that the stage finished.

    Without this, a group that dies late leaves the record at the group's entry
    stage and the retry re-runs stages that were complete — 21 times over, on
    2026-08-27 (``docs/bugs/20260828-group-stage-advance-is-all-or-nothing.md``).

    What the session did leave behind goes to the run's handoff note instead, so
    the retry is told rather than the record overstating. Returns the last stage
    credited, or ``None``. Never raises: this runs on a failure path that must
    stay a failure.
    """
    credited: str | None = None
    for stage in runnable:
        if stage.evidence is None:
            break
        state, _record, _detail = _verdict_state(task_id, stage.evidence, repo_root)
        if state != "pass":
            break
        target = workflow.next_stage(stage.name) or stage.name
        if not _record_stage(task, target, repo_root):
            print(f"   ⚠️  Could not credit stage {target} for {task_id}")
            break
        credited = target
    if credited:
        print(f"   ↩️  {task_id} keeps its proven progress; resumes at {credited}")
    _note_branch_state(
        repo_root,
        run_id,
        task=task,
        task_id=task_id,
        runnable=runnable,
        worktree_dir=worktree_dir,
        credited=credited,
    )
    return credited


def _note_branch_state(
    repo_root: str,
    run_id: str | None,
    *,
    task: dict,
    task_id: str,
    runnable: list[WorkflowStage],
    worktree_dir: str,
    credited: str | None,
) -> None:
    """Tell the retry what this branch already carries (ADR-069 decision 3).

    The handoff note is the only channel that reaches the next session's prompt
    without claiming a stage finished. Best-effort by construction: a note that
    cannot be written must not turn a stage failure into something else.
    """
    if not run_id:
        return
    try:
        base = task.get("base_commit") or "HEAD~1"
        result = subprocess.run(
            ["git", "-C", worktree_dir, "log", "--oneline", f"{base}..HEAD"],
            capture_output=True,
            text=True,
        )
        commits = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        decisions: list[str] = []
        if commits:
            decisions.append(
                f"This branch already carries {len(commits)} commit(s) from an "
                f"earlier attempt of this task; do not redo that work: "
                + "; ".join(commits[:10])
            )
        for stage in runnable:
            if stage.evidence is None:
                continue
            state, _record, _detail = _verdict_state(task_id, stage.evidence, repo_root)
            if state == "pass":
                decisions.append(
                    f"The '{stage.evidence}' verdict for stage '{stage.name}' is "
                    "already recorded and passing."
                )
        if credited:
            decisions.append(f"The pipeline stage was advanced to '{credited}'.")
        if not decisions:
            return
        handoff.append_entry(
            repo_root,
            run_id,
            stage=runnable[0].name,
            decisions=decisions,
        )
    except Exception:  # noqa: BLE001 - working memory is never load-bearing
        return


def _require_passing_verdict(
    task_id: str,
    kind: str,
    repo_root: str,
    plan_file: str,
    stage: str,
    logger: telemetry.RunLogger,
    *,
    adapter=None,
    worktree_dir: str | None = None,
    stall_timeout: float | None = None,
    isolation: str = "worktree",
    base_branch: str = "origin/main",
    task: dict | None = None,
    backend=None,
) -> bool:
    """Fail-closed evidence gate for a checking stage.

    Returns ``True`` only when a schema-valid verdict with ``verdict: "pass"``
    exists. A malformed or failing verdict returns ``False`` so the caller takes
    the same failure path as a non-zero session exit. On a passing ``qa``
    verdict a derived ``test_run`` telemetry record is emitted.

    When *adapter* and *worktree_dir* are supplied and the verdict is merely
    **missing**, one recovery session is spawned to write it before the gate
    decides. The gate itself never softens: recovery re-reads the file and a
    still-missing verdict fails exactly as before.

    When a ``qa`` verdict fails and *task* / *backend* are supplied, the task's
    failure record is enriched with a gap analysis comparing failed tests
    against the implement stage's targeted test set (R-8).
    """
    state, record, detail = _verdict_state(task_id, kind, repo_root)

    if state == "missing" and adapter is not None and worktree_dir is not None:
        print(f"   ⚠️  {detail}; attempting one recovery session")
        _run_verdict_recovery(
            adapter,
            repo_root,
            plan_file,
            worktree_dir,
            task_id,
            kind,
            stage,
            logger,
            stall_timeout,
            isolation,
            base_branch,
        )
        state, record, detail = _verdict_state(task_id, kind, repo_root)
        if state == "pass":
            print(f"   ✅ {kind} verdict recovered")

    if state != "pass":
        print(f"   ❌ Gate fail-closed: {detail} for {task_id}")
        if kind == "qa" and task is not None:
            _attach_gap_analysis_to_task(
                task, backend, task_id, repo_root, logger
            )
        return False

    if kind == "qa" and record is not None:
        _emit_test_run_from_verdict(logger, record, task_id, plan_file, stage)
    return True


def _run_with_live_tee(
    cmd: list[str],
    cwd: str,
    env: dict,
    stall_timeout: float,
    wall_backstop: float | None = None,
    watched_paths: list[str] | None = None,
) -> tuple[int, str]:
    """Spawn a session: echo its output live, keep a bounded tail buffer.

    Stage sessions run up to ~1 hour, so ``capture_output=True`` is not an
    option — it would silence live agent output for the whole session. This
    reader loop mirrors each line to the terminal as it arrives AND keeps the
    last ~256 KB (usage blocks are emitted at exit). Returns
    ``(exit_code, tail_text)``.

    A watchdog thread monitors hybrid liveness. The stall timer is reset by
    either process-tree activity (active descendants) or writes to watched
    run-log/telemetry files. If no liveness signal arrives for
    ``stall_timeout`` seconds, the process group is terminated and the result
    is classified as a timeout (nsr-01), the same class as a wall-clock kill.
    An optional ``wall_backstop`` enforces a hard ceiling regardless of
    liveness (R-3).
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    chunks: collections.deque[str] = collections.deque()
    buffered = 0

    # The liveness log is a run-log file whose mtime advances with every
    # emitted line, giving RunLogLiveness a signal even when stdout is the
    # only observable output.
    liveness_log = tempfile.NamedTemporaryFile(
        mode="w", suffix=".liveness.log", delete=False, encoding="utf-8"
    )
    liveness_log_path = liveness_log.name
    all_watched_paths = list(watched_paths or [])
    all_watched_paths.append(liveness_log_path)

    # Poll quickly for short test timeouts, but never more often than 10 s in
    # production to keep system-load noise low.
    poll_interval = max(0.05, min(stall_timeout / 2, 10.0))
    monitor = liveness.LivenessMonitor(
        proc.pid, all_watched_paths, poll_interval=poll_interval
    )
    monitor.start()

    stop_watchdog = threading.Event()
    cause_lock = threading.Lock()
    cause: str | None = None
    start_time = time.monotonic()

    def _watchdog() -> None:
        nonlocal cause
        poll_interval = 0.1
        while not stop_watchdog.wait(timeout=poll_interval):
            if proc.poll() is not None:
                return
            if _shutdown_requested:
                with cause_lock:
                    cause = "shutdown"
                _terminate_process_group(proc, timeout=10)
                return
            now = time.monotonic()
            if wall_backstop is not None and now - start_time > wall_backstop:
                with cause_lock:
                    cause = "wall"
                _terminate_process_group(proc, timeout=10)
                return
            if now - monitor.last_sign_of_life > stall_timeout:
                with cause_lock:
                    cause = "stall"
                _terminate_process_group(proc, timeout=10)
                return

    watchdog = threading.Thread(target=_watchdog, daemon=True)
    watchdog.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            liveness_log.write(line)
            liveness_log.flush()
            monitor.mark_alive()
            chunks.append(line)
            buffered += len(line)
            while buffered > usage_lib.TAIL_SCAN_BYTES and chunks:
                buffered -= len(chunks.popleft())
    finally:
        stop_watchdog.set()
        watchdog.join(timeout=5)
        monitor.stop()
        monitor.join(timeout=5)
        liveness_log.close()
        try:
            os.unlink(liveness_log_path)
        except OSError:
            pass

    exit_code = proc.wait()
    with cause_lock:
        if cause in ("stall", "wall"):
            return -9, "".join(chunks)
    return exit_code, "".join(chunks)


def _spawn_session(
    adapter,
    cmd: list[str],
    worktree_dir: str,
    env: dict,
    stall_timeout: float | None = None,
    wall_backstop: float | None = None,
    watched_paths: list[str] | None = None,
) -> tuple[int, dict | None, str | None]:
    """Run one agent session, returning ``(exit_code, usage, session_ref)``.

    ``usage`` is parsed from the captured tail only when the adapter declares
    a usage mode; otherwise it is ``None`` and the record keeps null fields.
    ``session_ref`` is the adapter-resolved session identifier (``None`` for
    unresolvable sessions); it feeds adapter-dispatched test-run extraction.

    ``stall_timeout`` and ``wall_backstop`` default to the active adapter's
    configured values.
    """
    if stall_timeout is None:
        stall_timeout = adapter.stall_timeout
    if wall_backstop is None:
        wall_backstop = adapter.wall_backstop
    return _spawn_session_with_tail(
        adapter,
        cmd,
        worktree_dir,
        env,
        stall_timeout=stall_timeout,
        wall_backstop=wall_backstop,
        watched_paths=watched_paths,
    )[:3]


def _spawn_session_with_tail(
    adapter,
    cmd: list[str],
    worktree_dir: str,
    env: dict,
    stall_timeout: float | None = None,
    wall_backstop: float | None = None,
    watched_paths: list[str] | None = None,
) -> tuple[int, dict | None, str | None, str]:
    """Run one agent session, returning ``(exit_code, usage, session_ref, tail)``.

    The bounded ``tail`` is used by the circuit breaker to classify failures.
    The public ``run_stage``/``run_stage_group`` functions call this helper and
    record signatures when a *task* and *backend* are provided.

    ``session_ref`` is an adapter-resolved session identifier (a session id
    for both kimi and Claude); the orchestrator asks the adapter and does not
    branch on ``adapter.name``. Resolution is guarded: a throwing resolver is
    treated as an unresolvable session rather than aborting the run.

    ``stall_timeout`` and ``wall_backstop`` default to the active adapter's
    configured values.
    """
    if stall_timeout is None:
        stall_timeout = adapter.stall_timeout
    if wall_backstop is None:
        wall_backstop = adapter.wall_backstop
    exit_code, output = _run_with_live_tee(
        cmd,
        worktree_dir,
        env,
        stall_timeout=stall_timeout,
        wall_backstop=wall_backstop,
        watched_paths=watched_paths,
    )
    usage = None
    if adapter.usage_mode is not None:
        usage = usage_lib.parse_usage(adapter.name, output)
    session_ref = _resolve_session_ref_guarded(adapter, output, worktree_dir)
    return exit_code, usage, session_ref, output


def _resolve_session_ref_guarded(adapter, output: str, worktree_dir: str) -> str | None:
    """Ask the adapter for a session identifier, never raising.

    A resolver that throws is treated as ``None``; telemetry is best-effort
    and must never block a run (ADR-031).
    """
    try:
        return adapter.resolve_session_ref(output, workdir=worktree_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"   ⚠️  Session-reference resolution failed (skipping): {exc}")
        return None


def run_stage(
    adapter,
    repo_root: str,
    plan_file: str,
    worktree_dir: str,
    skills: list[str],
    current_stage: str,
    next_stage: str,
    task_id: str | None = None,
    run_id: str | None = None,
    verdict_kind: str | None = None,
    task: dict | None = None,
    backend=None,
    stall_timeout: float | None = None,
) -> tuple[int, dict | None, str | None, str]:
    """Spawn a single stage session, returning ``(exit_code, usage, session_ref, output)``.

    When *task* and *backend* are provided, a non-zero exit records a failure
    signature on the task's ledger record for the circuit breaker (nsr-03).
    """
    freshness = _qa_freshness_decision(task_id, repo_root, worktree_dir)
    handoff_clause = _handoff_clause(repo_root, run_id)
    prompt = build_prompt(
        skills, plan_file, current_stage, next_stage,
        freshness_clause=_freshness_clause(freshness),
        handoff_clause=handoff_clause,
        verdict_kind=verdict_kind,
    )
    cmd = adapter.build_cmd(prompt, workdir=worktree_dir, headless=True)

    env = os.environ.copy()
    env["AET_EXECUTION_MODE"] = "unattended"
    env["AET_ORCHESTRATOR_PID"] = str(os.getpid())
    if freshness:
        env["AET_QA_FRESHNESS"] = freshness
    if task_id is not None:
        env["AET_TASK_ID"] = task_id
    if run_id is not None:
        env["AET_RUN_ID"] = run_id
    if task_id is not None and verdict_kind is not None:
        env["AET_EVIDENCE_PATH"] = str(
            evidence.evidence_path(
                task_id=task_id,
                kind=verdict_kind,
                project_slug=telemetry.derive_project_slug(repo_root),
            )
        )
    if run_id is not None:
        env["AET_TARGETED_TESTS_PATH"] = str(_targeted_tests_path(repo_root, run_id))

    watched_paths: list[str] = []
    if run_id is not None and task_id is not None:
        session_logger = telemetry.RunLogger(repo_root, run_id=run_id)
        watched_paths.append(str(session_logger.task_log_path(task_id)))

    print(f"   Invoking: {' '.join(cmd)}")
    exit_code, usage, session_ref, output = _spawn_session_with_tail(
        adapter,
        cmd,
        worktree_dir,
        env,
        stall_timeout=stall_timeout,
        watched_paths=watched_paths,
    )
    if exit_code == 0 and run_id is not None:
        # The tests were run while advancing toward next_stage; label the
        # handoff entry with the stage that produced them.
        _record_targeted_tests_handoff(repo_root, run_id, next_stage)
    if exit_code != 0 and task is not None:
        _record_failure_on_task(
            backend,
            task,
            _classify_failure(
                exit_code=exit_code,
                tail=output,
                stage=current_stage,
                verdict_recorded=verdict_kind is not None,
                shutdown=_shutdown_requested,
                killed_by_timeout=exit_code < 0,
            ),
            current_stage,
            output,
        )
        if verdict_kind == "qa":
            _attach_gap_analysis_to_task(task, backend, task_id, repo_root)
    return exit_code, usage, session_ref, output


def build_stage_group_prompt(
    plan_file: str,
    stages: list[WorkflowStage],
    workflow: Workflow,
    freshness_clause: str = "",
    handoff_clause: str = "",
) -> str:
    """Build a compound prompt for running multiple stages in one session.

    Each stage block preserves the single-stage prompt format so the agent
    can execute them sequentially, committing between stages. Stage state is
    recorded on the task record by the engine, not in plan footers (R-4/R-19).
    Successors resolve through the workflow's list order.
    """
    preamble = (
        "Execute the following consecutive pipeline stages in order. "
        "Complete each stage (including its commit) before starting the next. "
        "Do not proceed past the final stage listed." + freshness_clause + handoff_clause
    )
    blocks = [preamble]
    for stage in stages:
        next_stage = workflow.next_stage(stage.name) or stage.name
        skills_str = " → ".join(stage.skills)
        evidence_clause = ""
        if stage.evidence is not None:
            evidence_clause = _evidence_clause(
                stage.evidence, evidence.evidence_path_env_var(stage.evidence)
            )
        blocks.append(
            f"Run {skills_str} on {plan_file}\n"
            f"Current stage: {stage.name}. Target stage: {next_stage}.\n"
            f"Finish this stage completely, then continue to the next stage "
            f"block in this prompt. Do not go past the last block.\n"
            f"Commit your work before exiting.{evidence_clause}"
        )
    return "\n\n".join(blocks)


def run_stage_group(
    adapter,
    repo_root: str,
    plan_file: str,
    worktree_dir: str,
    stages: list[WorkflowStage],
    task_id: str | None = None,
    run_id: str | None = None,
    *,
    workflow: Workflow,
    task: dict | None = None,
    backend=None,
    stall_timeout: float | None = None,
) -> tuple[int, dict | None, str | None, str]:
    """Spawn one session that runs every stage in the group sequentially.

    Returns ``(exit_code, usage, session_ref, output)``; usage covers the whole
    group session and ``session_ref`` is the adapter-resolved session
    identifier (``None`` for unresolvable sessions). When *task* and *backend*
    are provided, a non-zero exit records a failure signature on the task's
    ledger record using the first stage's name (nsr-03).
    """
    freshness = _qa_freshness_decision(task_id, repo_root, worktree_dir)
    handoff_clause = _handoff_clause(repo_root, run_id)
    prompt = build_stage_group_prompt(
        plan_file, stages, workflow,
        freshness_clause=_freshness_clause(freshness),
        handoff_clause=handoff_clause,
    )
    cmd = adapter.build_cmd(prompt, workdir=worktree_dir, headless=True)

    env = os.environ.copy()
    env["AET_EXECUTION_MODE"] = "unattended"
    env["AET_ORCHESTRATOR_PID"] = str(os.getpid())
    if freshness:
        env["AET_QA_FRESHNESS"] = freshness
    if task_id is not None:
        env["AET_TASK_ID"] = task_id
    if run_id is not None:
        env["AET_RUN_ID"] = run_id
    if task_id is not None:
        # Publish the canonical verdict path per evidence-bound stage so
        # writers and the gate share one derivation in group sessions too
        # (ADR-023). Same formula run_stage uses for AET_EVIDENCE_PATH.
        project_slug = telemetry.derive_project_slug(repo_root)
        for stage in stages:
            if stage.evidence is None:
                continue
            env[evidence.evidence_path_env_var(stage.evidence)] = str(
                evidence.evidence_path(
                    task_id=task_id,
                    kind=stage.evidence,
                    project_slug=project_slug,
                )
            )
    if run_id is not None:
        env["AET_TARGETED_TESTS_PATH"] = str(_targeted_tests_path(repo_root, run_id))

    watched_paths: list[str] = []
    if run_id is not None and task_id is not None:
        session_logger = telemetry.RunLogger(repo_root, run_id=run_id)
        watched_paths.append(str(session_logger.task_log_path(task_id)))

    print(f"   Invoking group: {' '.join(cmd)}")
    exit_code, usage, session_ref, output = _spawn_session_with_tail(
        adapter,
        cmd,
        worktree_dir,
        env,
        stall_timeout=stall_timeout,
        watched_paths=watched_paths,
    )
    if exit_code == 0 and run_id is not None:
        # Use the last stage name as the recorder stage; the file is written by
        # the implement portion of the group session.
        _record_targeted_tests_handoff(repo_root, run_id, stages[-1].name)
    if exit_code != 0 and task is not None:
        _record_failure_on_task(
            backend,
            task,
            _classify_failure(
                exit_code=exit_code,
                tail=output,
                stage=stages[0].name,
                verdict_recorded=False,
                shutdown=_shutdown_requested,
                killed_by_timeout=exit_code < 0,
            ),
            stages[0].name,
            output,
        )
    return exit_code, usage, session_ref, output


def stage_enabled(stage: WorkflowStage, plan_fm: dict) -> bool:
    """Return True when ``stage`` should run for the given plan frontmatter.

    A stage without a ``gate_key`` always runs. A gated stage runs unless the
    plan frontmatter sets its gate key to ``skipped``. When the gate key is
    absent from frontmatter, resolution falls back to ``stage.gate_default``:
    ``"required"`` runs (fail-safe), while ``"critical-only"`` runs only when
    ``work_class`` is ``"critical"``. An explicit frontmatter value is always
    authoritative over the default.
    """
    if not stage.gate_key:
        return True
    if stage.gate_key in plan_fm:
        return plan_fm[stage.gate_key] != "skipped"
    if stage.gate_default == "critical-only":
        return plan_fm.get("work_class") == "critical"
    return True


def _report_gate_decision(stage: WorkflowStage, plan_fm: dict, enabled: bool) -> None:
    """Print how a gated stage's run/skip decision was resolved.

    The source is ``frontmatter`` when the plan sets the gate key and
    ``default`` when the key is absent (fail-safe run or critical-only skip).
    Ungated stages and frontmatter-directed runs are silent.
    """
    if not stage.gate_key:
        return
    if enabled:
        if stage.gate_key not in plan_fm:
            print(
                f"   🔒 Gate {stage.gate_key} unset; running {stage.name} (source: default)"
            )
        return
    if stage.gate_key in plan_fm:
        print(
            f"   ⏭️  Skipping gated stage: {stage.name} "
            f"({stage.gate_key}=skipped, source: frontmatter)"
        )
    else:
        work_class = plan_fm.get("work_class") or "unclassified"
        print(
            f"   ⏭️  Skipping gated stage: {stage.name} "
            f"(work_class={work_class}, source: default)"
        )


def process_task(
    task: dict,
    repo_root: str,
    adapter,
    isolation: str,
    logger: telemetry.RunLogger | None = None,
    worktree_dir: str | None = None,
    workflow: Workflow | None = None,
    backend=None,
    stall_timeout: float | None = None,
    *,
    base_branch: str = "origin/main",
    integration_mode: str = "pr-per-task",
) -> bool:
    """Process a single task through all its stage groups.

    The stage sequence, skill bindings, evidence kinds, and session grouping
    come from the workflow file (``workflow:`` plan frontmatter key, default
    ``software``) — loaded once per task and threaded through every decision.

    ``integration_mode`` is resolved once per run by the caller and passed
    down so every task in a batch sees the same mode. Only ``pr-per-task``
    is supported in this version; ``single-pr`` lands in ``epi-08``.
    """
    if integration_mode not in ("pr-per-task", "single-pr"):
        print(
            f"   ❌ Integration mode {integration_mode!r} is not supported. "
            "Use 'pr-per-task' or 'single-pr'."
        )
        return False

    if logger is None:
        logger = telemetry.RunLogger(repo_root)
    task_id = task["id"]
    plan_data = plan_parser.task_routing_data(task, repo_root)
    config = resolve_config(DEFAULT_CONFIG_PATH, repo_root=repo_root)
    canonical_rel = f"docs/plans/{task_id}.md"
    plan_file = os.path.join(repo_root, canonical_rel)

    print(f"▶️  Task: {task.get('title', task_id)} ({task_id})")
    print(f"   Plan: {plan_file}")

    # Create or reuse worktree
    if worktree_dir is None:
        worktree_dir = create_worktree(repo_root, task_id, base_branch=base_branch)
    copy_untracked_files(repo_root, worktree_dir)

    # Render the working plan from the task record into the worktree (R-19).
    # The plan file is ephemeral: it is never committed and never overlays the
    # main-checkout copy, which removes the _copy_deferred_files clobber defect.
    rendered = render_task_plan(repo_root, worktree_dir, task)
    if rendered:
        print(f"   📝 Rendered plan for {task_id}")

    # Warm up configured worktree dependencies.
    warmup_results = prepare_worktree_dependencies(repo_root, worktree_dir)
    for result in warmup_results:
        name = result["name"]
        if result["status"] == "created":
            print(f"   🔗 Warmed dependency: {name}")
        elif result["status"] == "skipped":
            print(f"   ℹ️  Dependency skipped: {name} ({result['message']})")
        elif result["status"] == "failed":
            print(f"   ⚠️  Dependency warmup failed: {name} ({result['message']})")
    print(f"   Worktree: {worktree_dir}")

    # Emit telemetry for any failed dependency warmups.
    for result in warmup_results:
        if result["status"] != "failed":
            continue
        logger.append_record(
            telemetry.environment_issue_record(
                run_id=logger.run_id,
                task_id=task_id,
                plan_file=plan_file,
                issue_type="missing_dependency",
                dependency=result.get("target", result.get("name", "unknown")),
                message=f"Dependency warmup failed: {result['message']}",
            ),
            task_id=task_id,
        )

    # Use the worktree copy of the plan file for stages and verification.
    plan_file = os.path.join(worktree_dir, canonical_rel)

    # Fail loudly if the plan is missing in the worktree. A missing plan means
    # the task record has no spec and no legacy plan_file path; this is a
    # misconfiguration, not a flaky task, so it halts rather than requeues (R-6).
    if not os.path.exists(plan_file):
        raise MissingPlanError(base_branch, plan_file)

    # Gate routing resolves against the task record (R-19).  The rendered plan
    # file is parsed only as a backward-compatible fallback for legacy records
    # that were created before the spec field existed.
    plan_fm = plan_data or plan_parser.parse_frontmatter(Path(plan_file))

    # The workflow file is the engine's source of truth for stage sequencing.
    # A missing or invalid file fails the run loudly at task start — there is
    # no silent fallback to a baked-in sequence; the packaged default is the
    # fallback (ADR-020).
    if workflow is None:
        workflow_name = plan_fm.get("workflow") or "software"
        try:
            workflow = load_workflow(repo_root, workflow_name)
        except WorkflowError as exc:
            print(f"   ❌ {exc}")
            return False

    # Determine current stage from the task record.
    current_stage = get_current_stage(task, plan_file, workflow.entry_stage)

    # A terminal or unknown stage with no commits means the plan footer (or a
    # stale worktree) is lying. Fail loudly instead of marking the task done.
    if current_stage not in workflow.stage_map:
        ok, msg = verify_branch_has_commits(worktree_dir)
        if not ok:
            print(f"   ❌ Stage '{current_stage}' is not a runnable pipeline stage and {msg}")
            return False

    # Allow the plan frontmatter to override the CLI isolation default.
    task_isolation = effective_isolation(plan_fm, isolation)
    if task_isolation != isolation:
        print(f"   📋 Plan isolation: {task_isolation}")

    # Group stages by isolation level
    groups = workflow.session_groups(task_isolation)
    agent_invoked = False

    for group in groups:
        if _shutdown_requested:
            print(f"   ⚠️  Shutdown requested, stopping task {task_id}")
            return False

        # Find the first stage in this group that hasn't been completed yet.
        start_idx = None
        for i, stage in enumerate(group):
            if stage.name == current_stage:
                start_idx = i
                break

        if start_idx is None:
            # All stages in this group are done; move to the next group.
            continue

        remaining = group[start_idx:]

        # For standard isolation, try to run the remaining stages in one session.
        if task_isolation == "standard":
            decisions = [(s, stage_enabled(s, plan_fm)) for s in remaining]
            runnable = [s for s, ok in decisions if ok]
            if len(runnable) != 1:
                # The per-stage walk below only runs when exactly one stage is
                # runnable; in every other case this is where skip decisions
                # are final, so report them here.
                for s, ok in decisions:
                    _report_gate_decision(s, plan_fm, ok)
            if runnable and len(runnable) > 1:
                expected_final = workflow.next_stage(runnable[-1].name) or runnable[-1].name
                stage_span = [s.name for s in runnable]
                print(
                    f"   Stage group: {' → '.join(stage_span)} → {expected_final}"
                )

                start_time = telemetry.iso_now()
                exit_code, usage, session_ref, output = run_stage_group(
                    adapter,
                    repo_root,
                    plan_file,
                    worktree_dir,
                    runnable,
                    task_id=task_id,
                    run_id=logger.run_id,
                    workflow=workflow,
                    task=task,
                    backend=backend,
                    stall_timeout=stall_timeout,
                )
                end_time = telemetry.iso_now()
                targeted_tests = _stage_targeted_tests(
                    repo_root,
                    logger.run_id,
                    exit_code,
                    should_record=any("aet-implement" in s.skills for s in runnable),
                )
                _emit_stage_session(
                    logger,
                    task_id,
                    plan_file,
                    adapter.name,
                    task_isolation,
                    expected_final,
                    stage_span,
                    worktree_dir,
                    start_time,
                    end_time,
                    exit_code,
                    usage=usage,
                    session_ref=session_ref,
                    base_branch=base_branch,
                    output=output,
                    verdict_recorded=False,
                    plan_data=plan_fm,
                    targeted_tests=targeted_tests,
                )
                agent_invoked = True
                if exit_code != 0:
                    print(f"   ❌ Stage group failed with exit code {exit_code}")
                    _credit_proven_stages(
                        task,
                        runnable,
                        workflow,
                        task_id=task_id,
                        repo_root=repo_root,
                        worktree_dir=worktree_dir,
                        run_id=logger.run_id,
                    )
                    return False

                # Verify the group session produced commits.
                ok, msg = verify_branch_has_commits(worktree_dir)
                if not ok:
                    print(f"   ❌ Stage group verification failed: {msg}")
                    return False

                # Fail-closed evidence gates: every stage in the group span
                # with an evidence binding must have a schema-valid passing
                # verdict. Group advancement is determined by evidence.
                for stage in runnable:
                    kind = stage.evidence
                    if kind is None:
                        continue
                    target = workflow.next_stage(stage.name) or stage.name
                    if not _require_passing_verdict(
                        task_id,
                        kind,
                        repo_root,
                        plan_file,
                        target,
                        logger,
                        adapter=adapter,
                        worktree_dir=worktree_dir,
                        stall_timeout=stall_timeout,
                        isolation=task_isolation,
                        base_branch=base_branch,
                        task=task,
                        backend=backend,
                    ):
                        return False

                if not _record_stage(task, expected_final, repo_root):
                    print(f"   ❌ Could not record stage {expected_final} for {task_id}")
                    return False

                ok, msg = verify_stage_advancement(
                    task.get("stage"), worktree_dir, expected_final
                )
                if not ok:
                    print(f"   ❌ Stage group advancement verification failed: {msg}")
                    return False

                print(f"   ✅ Stage group advanced to {expected_final}")
                current_stage = expected_final
                continue
            elif not runnable:
                # All remaining stages are gated skips; jump to the end of the group.
                current_stage = workflow.next_stage(remaining[-1].name) or remaining[-1].name
                continue

        # Per-stage execution: used for minimal/full isolation and for single-stage
        # groups. Standard multi-stage groups fail closed on missing evidence
        # rather than falling back here.
        while True:
            # Find the first stage in this group that hasn't been completed yet.
            target_stage = None
            for stage in group:
                if stage.name == current_stage:
                    target_stage = stage
                    break

            if not target_stage:
                # All stages in this group are done; break to next group.
                break

            # Gated stages resolve from the plan frontmatter — pure data,
            # no runtime judgment.
            enabled = stage_enabled(target_stage, plan_fm)
            _report_gate_decision(target_stage, plan_fm, enabled)
            if not enabled:
                current_stage = workflow.next_stage(target_stage.name) or current_stage
                continue

            next_stage_name = workflow.next_stage(target_stage.name) or current_stage
            skills = target_stage.skills

            if not skills:
                # Terminal stage (skill-less, e.g. synced).
                current_stage = next_stage_name
                continue

            print(f"   Stage: {target_stage.name} → {next_stage_name} ({' → '.join(skills)})")

            kind = target_stage.evidence
            start_time = telemetry.iso_now()
            exit_code, usage, session_ref, output = run_stage(
                adapter,
                repo_root,
                plan_file,
                worktree_dir,
                skills,
                target_stage.name,
                next_stage_name,
                task_id=task_id,
                run_id=logger.run_id,
                verdict_kind=kind,
                task=task,
                backend=backend,
                stall_timeout=stall_timeout,
            )
            end_time = telemetry.iso_now()
            targeted_tests = _stage_targeted_tests(
                repo_root,
                logger.run_id,
                exit_code,
                should_record="aet-implement" in target_stage.skills,
            )
            _emit_stage_session(
                logger,
                task_id,
                plan_file,
                adapter.name,
                task_isolation,
                next_stage_name,
                None,
                worktree_dir,
                start_time,
                end_time,
                exit_code,
                usage=usage,
                session_ref=session_ref,
                base_branch=base_branch,
                output=output,
                verdict_recorded=kind is not None,
                plan_data=plan_fm,
                targeted_tests=targeted_tests,
            )
            agent_invoked = True

            if exit_code != 0:
                print(f"   ❌ Stage failed with exit code {exit_code}")
                return False

            # Verify the stage produced commits before persisting the advance.
            ok, msg = verify_branch_has_commits(worktree_dir)
            if not ok:
                print(f"   ❌ Stage verification failed: {msg}")
                return False

            # Fail-closed evidence gate for checking stages (qa/review/cso/sync-docs).
            if kind is not None and not _require_passing_verdict(
                task_id,
                kind,
                repo_root,
                plan_file,
                next_stage_name,
                logger,
                adapter=adapter,
                worktree_dir=worktree_dir,
                stall_timeout=stall_timeout,
                isolation=task_isolation,
                base_branch=base_branch,
                task=task,
                backend=backend,
            ):
                return False

            # Record the advanced stage in the task record.
            if not _record_stage(task, next_stage_name, repo_root):
                print(f"   ❌ Could not record stage {next_stage_name} for {task_id}")
                return False

            # Confirm the recorded stage matches the expected target.
            ok, msg = verify_stage_advancement(
                task.get("stage"), worktree_dir, next_stage_name
            )
            if not ok:
                print(f"   ❌ Stage verification failed: {msg}")
                return False

            print(f"   ✅ Stage advanced to {next_stage_name}")
            current_stage = next_stage_name

    # If the orchestrator never actually invoked an agent, the only legitimate
    # success is a task whose branch already contains work (e.g. a resumed
    # terminal stage). An empty branch here means a stale footer or corrupt
    # worktree fooled us into skipping all stages.
    if not agent_invoked:
        ok, msg = verify_branch_has_commits(worktree_dir)
        if not ok:
            print(f"   ❌ Task completed without running any stage and {msg}")
            return False

    # In single-pr mode, integrate the task branch into the epic integration
    # branch locally, push the integration branch, delete the per-task branch,
    # and mark the task merged. This is the "done means integrated" semantics
    # of ADR-045 decision 3.
    if integration_mode == "single-pr":
        task_integration = resolve_integration_branch_for_task(
            repo_root, config, task, integration_mode
        )
        try:
            _integrate_single_pr_task(
                repo_root=repo_root,
                task_id=task_id,
                integration_branch=task_integration.ref,
                worktree_dir=worktree_dir,
                backend=backend,
                plan_file=plan_file,
                plan_data=plan_fm,
            )
        except IntegrationFailureError as exc:
            print(f"   ❌ Integration failure for {task_id}: {exc}")
            queue_file = os.path.join(repo_root, ".agents", "aet-queue")
            _mark_integration_failure(
                backend,
                queue_file,
                task_id,
                current_state(task) if task else "in_progress",
                str(exc),
            )
            raise

    print(f"   ✅ Task complete: {task_id}")
    return True


def _validate_after_rebase(worktree_dir: str) -> tuple[bool, str]:
    """Re-run task validation in the rebased worktree.

    Returns ``(True, "")`` on success, ``(False, output)`` on failure. The
    default command is the project's full validation gate; tests and unusual
    projects can override it via ``AET_INTEGRATION_VALIDATE_CMD``.
    """
    cmd_env = os.environ.get("AET_INTEGRATION_VALIDATE_CMD", "")
    if cmd_env:
        cmd = cmd_env.split()
    else:
        cmd = ["make", "validate"]
    result = subprocess.run(
        cmd,
        cwd=worktree_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = result.stdout + result.stderr
        return False, output
    return True, ""


def _mark_integration_failure(
    backend,
    queue_file: str,
    task_id: str,
    from_state: str | None,
    reason: str,
) -> None:
    """Mark a task as failed due to an integration failure.

    Integration failure is an engine-level outcome, not a member of the
    ADR-030 failure-class menu. It is not triaged as a task failure and does
    not increment the per-task circuit breaker (ADR-045, R-19).
    """
    if from_state is None:
        from_state = "in_progress"
    aet_state_bin = str(_SCRIPT_DIR / "aet_state.py")
    result = subprocess.run(
        [
            sys.executable,
            aet_state_bin,
            "transition",
            task_id,
            from_state,
            "failed",
            queue_file,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"   ⚠️  Could not transition {task_id} to failed after integration failure: "
            f"{result.stderr.strip()}"
        )
        return

    sig = failure_lib.signature(stage="integration", tail=reason)
    with queue_lock(queue_file):
        data = backend.load()
        queue = data["queue"]
        task = next((t for t in queue if t.get("id") == task_id), None)
        if task is not None:
            task["integration_failure"] = {
                "reason": reason,
                "signature": sig,
                "at": telemetry.iso_now(),
            }
            _save_task_record(backend, queue)


def _integrate_single_pr_task(
    repo_root: str,
    task_id: str,
    integration_branch: str,
    worktree_dir: str,
    backend=None,
    plan_file: str | None = None,
    plan_data: dict[str, Any] | None = None,
) -> bool:
    """Serialize, rebase, re-validate, squash-merge, push, and clean up.

    In ``single-pr`` mode the integration step (rebase onto current tip →
    re-validate → squash-merge) is gated behind the local advisory integration
    lock while implementation stays concurrent (ADR-045, R-18). A rebase
    conflict or post-rebase validation failure is reported as an Integration
    Failure, not triaged as a task failure (R-19).

    Also transitions the queued task to ``merged`` when a queue file exists.
    Returns ``True`` on success and raises ``IntegrationFailureError`` on any
    integration failure.
    """
    print(f"   🔀 Integrating {task_id} into {integration_branch}")
    queue_file = os.path.join(repo_root, ".agents", "aet-queue")

    # Remember repo_root HEAD so we can restore it after checking out the
    # integration branch for the squash-merge.
    head_ref = subprocess.run(
        ["git", "-C", repo_root, "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    original_branch = head_ref.stdout.strip() if head_ref.returncode == 0 else None
    original_sha_proc = subprocess.run(
        ["git", "-C", repo_root, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    original_sha = original_sha_proc.stdout.strip() if original_sha_proc.returncode == 0 else None

    with integration_lock(repo_root):
        try:
            # Rebase the task branch onto the live integration tip inside the
            # worktree. This is the "rebase onto current tip" part of R-18.
            rebase = subprocess.run(
                ["git", "-C", worktree_dir, "rebase", f"origin/{integration_branch}"],
                capture_output=True,
                text=True,
            )
            if rebase.returncode != 0:
                subprocess.run(
                    ["git", "-C", worktree_dir, "rebase", "--abort"],
                    capture_output=True,
                )
                raise IntegrationFailureError(
                    f"rebase conflict integrating {task_id}: {rebase.stderr.strip()}"
                )

            # Re-validate the rebased combination before it lands (R-18).
            ok, output = _validate_after_rebase(worktree_dir)
            if not ok:
                raise IntegrationFailureError(
                    f"validation failed after rebase for {task_id}:\n{output}"
                )

            # Verify required gate evidence before the squash-merge lands (R-22).
            # Prefer the routing data already resolved from the task record;
            # fall back to parsing the rendered plan file for legacy records.
            _plan_path = Path(plan_file) if plan_file else Path(worktree_dir) / "docs" / "plans" / f"{task_id}.md"
            _plan_fm = plan_data or plan_parser.parse_frontmatter(_plan_path)
            _evidence_ok, _evidence_failures = gate.check_task_evidence(
                task_id, _plan_fm, repo_root
            )
            if not _evidence_ok:
                raise IntegrationFailureError(
                    "missing required gate evidence for "
                    f"{task_id}:\n" + "\n".join(_evidence_failures)
                )

            # Squash-merge the rebased task branch into the integration branch.
            # Fetch first so the local integration branch tracks the live remote
            # tip; previous integration pushes may have moved it.
            subprocess.run(
                ["git", "-C", repo_root, "fetch", "origin", integration_branch],
                capture_output=True,
                text=True,
            )
            checkout = subprocess.run(
                ["git", "-C", repo_root, "checkout", integration_branch],
                capture_output=True,
                text=True,
            )
            if checkout.returncode != 0:
                raise IntegrationFailureError(
                    f"checkout {integration_branch} failed: {checkout.stderr.strip()}"
                )
            reset = subprocess.run(
                ["git", "-C", repo_root, "reset", "--hard", f"origin/{integration_branch}"],
                capture_output=True,
                text=True,
            )
            if reset.returncode != 0:
                raise IntegrationFailureError(
                    f"reset to origin/{integration_branch} failed: {reset.stderr.strip()}"
                )

            merge = subprocess.run(
                ["git", "-C", repo_root, "merge", "--squash", task_id],
                capture_output=True,
                text=True,
            )
            if merge.returncode != 0:
                subprocess.run(
                    ["git", "-C", repo_root, "merge", "--abort"],
                    capture_output=True,
                )
                raise IntegrationFailureError(
                    f"squash merge of {task_id} failed: {merge.stderr.strip()}"
                )

            commit = subprocess.run(
                ["git", "-C", repo_root, "commit", "-m", f"Integrate {task_id}"],
                capture_output=True,
                text=True,
            )
            if commit.returncode != 0:
                raise IntegrationFailureError(
                    f"commit after squash merge failed: {commit.stderr.strip()}"
                )

            rc, out, _ = run_git_plain(["-C", repo_root, "rev-parse", "HEAD"])
            if rc != 0:
                raise IntegrationFailureError("could not resolve merge commit")
            merge_commit = out.strip()

            ok, err = push_branch(repo_root, integration_branch)
            if not ok:
                raise IntegrationFailureError(
                    f"push of {integration_branch} failed: {err}"
                )
        finally:
            # Restore repo_root HEAD before releasing the lock so the next task
            # does not race for repo_root's index.lock.
            if original_branch:
                subprocess.run(
                    ["git", "-C", repo_root, "checkout", original_branch],
                    capture_output=True,
                )
            elif original_sha:
                subprocess.run(
                    ["git", "-C", repo_root, "checkout", original_sha],
                    capture_output=True,
                )

    # Update the remote-tracking ref so the ancestry check in aet_state
    # passes before we transition the task to merged.
    subprocess.run(
        ["git", "-C", repo_root, "update-ref", f"refs/remotes/origin/{integration_branch}", merge_commit],
        capture_output=True,
    )

    # Lock released. Clean up the task branch and worktree, then transition
    # the queued task to merged.
    subprocess.run(
        ["git", "-C", repo_root, "worktree", "remove", "--force", worktree_dir],
        capture_output=True,
    )
    delete_local_branch(repo_root, task_id)

    # Record the merge commit on the task so the merged-state ancestry check
    # can pass even though the per-task branch has been deleted.
    if backend is not None and _task_in_queue(backend, task_id):
        queue = backend.load()["queue"]
        for t in queue:
            if t.get("id") == task_id:
                t["merge_commit"] = merge_commit
                break
        # The aet-state transition below fetches origin first, so this write is
        # replicated in the same call that saves it.
        _save_task_record(backend, queue)

    if backend is not None and _task_in_queue(backend, task_id):
        aet_state_bin = str(_SCRIPT_DIR / "aet_state.py")
        # Record the integration as awaiting_merge so the batch parent can
        # finalize it. We avoid transitioning straight to merged here because
        # aet_state seals merged tasks out of the live queue, which would
        # race with the parent's _finalize_task bookkeeping.
        result = subprocess.run(
            [
                sys.executable,
                aet_state_bin,
                "transition",
                task_id,
                "in_progress",
                "awaiting_merge",
                queue_file,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(
                f"   ⚠️  Could not transition {task_id} to awaiting_merge: {result.stderr.strip()}"
            )
            return False

    print(f"   ✅ {task_id} integrated into {integration_branch}")
    return True


def get_next_ready_task(queue: list[dict]) -> dict | None:
    """Return the first task whose stored state is ``ready``."""
    return get_next_unblocked(queue)


def has_pending_tasks(queue: list[dict]) -> bool:
    """Return True if any task is still actionable (stored non-terminal)."""
    return queue_has_pending_tasks(queue)


# States that can still make progress on their own inside the batch loop: a
# ``ready`` task will be spawned on the next pass, and an ``in_progress`` task
# has a live child. Anything else non-terminal (awaiting_merge/blocked/planned/
# failed) is stranded until an external actor (record-merge, curation, a human)
# moves it, so the batch must exit instead of spinning.
_BATCH_ACTIONABLE_STATES = frozenset({"ready", "in_progress"})

# Stranded non-terminal states, in the order they should appear in the leftover
# report. Terminal states (merged/abandoned) are excluded: a fully terminal
# queue is a clean completion, not a leftover. ``quarantined`` is non-actionable
# and must be surfaced so a human can un-quarantine it (nsr-02).
_BATCH_LEFTOVER_STATES = (
    "in_progress",
    "awaiting_merge",
    "blocked",
    "planned",
    "failed",
    "quarantined",
)
_BATCH_LEFTOVER_LABELS = {
    # An in_progress task in the leftover report is one no live worker owns:
    # a run died holding it. It is the most alarming leftover, so it leads.
    "in_progress": "orphaned in progress",
    "awaiting_merge": "awaiting merge",
    "blocked": "blocked",
    "planned": "planned",
    "failed": "failed",
    "quarantined": "quarantined",
}


def has_actionable_tasks(queue: list[dict], owned_ids: Collection[str] = ()) -> bool:
    """Return True if any stored task can still make progress on its own.

    A ``ready`` task is actionable: the spawn loop can pick it up. An
    ``in_progress`` task is actionable only when this run owns a live worker
    for it — ``owned_ids`` carries those task ids.

    Stored state alone is not enough. A task left ``in_progress`` by a run
    that died is not going to advance: no worker owns it, and the spawn loop
    will not dispatch it because it is not ``ready``. Counting it as
    actionable is what kept an idle orchestrator sleeping and retrying for
    eight hours while holding the lease.
    """
    owned = set(owned_ids)
    for task in queue:
        state = current_state(task)
        if state == "ready":
            return True
        if state == "in_progress" and task.get("id") in owned:
            return True
    return False


def leftover_counts(queue: list[dict]) -> dict[str, int]:
    """Count stranded non-terminal tasks by state (zero counts omitted)."""
    counts = {state: 0 for state in _BATCH_LEFTOVER_STATES}
    for task in queue:
        state = current_state(task)
        if state in counts:
            counts[state] += 1
    return {state: counts[state] for state in _BATCH_LEFTOVER_STATES if counts[state]}


def format_leftover_report(counts: dict[str, int]) -> str:
    """Render leftover counts as ``N awaiting merge, M blocked, ...``."""
    parts = [
        f"{counts[state]} {_BATCH_LEFTOVER_LABELS[state]}"
        for state in _BATCH_LEFTOVER_STATES
        if state in counts
    ]
    return ", ".join(parts)


def _classify_failure(
    *,
    exit_code: int,
    tail: str,
    stage: str,
    verdict_recorded: bool,
    shutdown: bool,
    killed_by_timeout: bool,
) -> failure_lib.FailureClass:
    """Classify a finished session using the nsr-01 taxonomy."""
    return failure_lib.classify(
        exit_code=exit_code,
        tail=tail,
        stage=stage,
        verdict_recorded=verdict_recorded,
        shutdown=shutdown,
        killed_by_timeout=killed_by_timeout,
    )


def _record_failure_on_task(
    backend,
    task: dict,
    failure_class: failure_lib.FailureClass,
    stage: str,
    tail: str,
    timestamp: str | None = None,
) -> str | None:
    """Record a failure signature on *task* when it is countable.

    Stores the signature together with the deterministic class, stage, and a
    bounded tail preview so the finalize path can consult a triage session
    without re-running the failed stage (nsr-04). ``canceled`` failures are
    skipped (ADR-030); ``throttled`` ones are recorded as non-countable, because
    the finalize path reads the class off this record to stop the run. Returns
    the computed signature when an entry was recorded, otherwise ``None``.
    """
    sig = failure_lib.signature(stage=stage, tail=tail)
    before = len(task.get("failure_signatures") or [])
    breaker.append_failure_if_countable(task, failure_class, sig, timestamp=timestamp)
    entries = task.get("failure_signatures") or []
    if len(entries) == before:
        # Nothing was recorded (``canceled``): there is no entry to enrich.
        return None
    # Enrich the latest signature entry with triage inputs. The breaker only
    # cares about ``signature`` and ``countable``; extra keys are ignored.
    entry = entries[-1]
    entry["class"] = failure_class.value
    entry["stage"] = stage
    entry["tail_preview"] = tail[-1500:] if tail else ""
    # Persist the updated task record if a backend is available.
    if backend is not None:
        queue = backend.load()["queue"]
        for qt in queue:
            if qt.get("id") == task.get("id"):
                qt["failure_signatures"] = task.get("failure_signatures", [])
                break
        _save_task_record(backend, queue)
    return sig


# Fail-closed fallback when the triage session errors or returns an unparseable
# verdict. The deterministic classifier's class drives the default action.
_TRIAGE_DEFAULT_ACTIONS: dict[str, str] = {
    failure_lib.FailureClass.ENVIRONMENT.value: "requeue",
    failure_lib.FailureClass.FLAKY.value: "requeue",
    failure_lib.FailureClass.TIMEOUT.value: "requeue",
    failure_lib.FailureClass.DESIGN.value: "quarantine",
    failure_lib.FailureClass.CANCELED.value: "quarantine",
    failure_lib.FailureClass.THROTTLED.value: "requeue",
}


def _requeue_task(
    backend, queue_file: str, task_id: str, failed_state: str, aet_state_bin: str
) -> bool:
    """Transition ``failed -> ready``, reporting failure rather than raising."""
    result = subprocess.run(
        [
            sys.executable,
            aet_state_bin,
            "transition",
            task_id,
            failed_state,
            "ready",
            queue_file,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    print(
        f"   ⚠️  Could not transition {task_id} to ready: "
        f"{result.stderr.strip()}; leaving failed"
    )
    return False


def _consult_triage_session(
    adapter,
    repo_root: str,
    worktree_dir: str,
    *,
    task_id: str,
    stage: str,
    failure_class: failure_lib.FailureClass,
    tail: str,
    signature: str,
    stall_timeout: float | None = None,
) -> dict | None:
    """Spawn a triage session and return its parsed verdict, or ``None``.

    A ``None`` result (insufficient evidence, spawn error, non-zero exit, or
    unparseable output) tells the caller to fall back to the deterministic
    classifier default.
    """
    if not triage.has_sufficient_evidence(tail=tail, signature=signature):
        return None
    prompt = triage.build_triage_prompt(
        task_id=task_id,
        stage=stage,
        failure_class=failure_class.value,
        tail=tail,
        signature=signature,
    )
    try:
        cmd = adapter.build_cmd(prompt, workdir=worktree_dir, headless=True)
    except Exception:  # pragma: no cover - defensive fallback
        return None
    env = os.environ.copy()
    env["AET_EXECUTION_MODE"] = "unattended"
    env["AET_ORCHESTRATOR_PID"] = str(os.getpid())
    try:
        exit_code, _usage, _session_ref, output = _spawn_session_with_tail(
            adapter, cmd, worktree_dir, env, stall_timeout=stall_timeout
        )
    except Exception:  # pragma: no cover - defensive fallback
        return None
    if exit_code != 0:
        return None
    return triage.parse_triage_verdict(output)


def _mark_quarantined(
    backend, queue_file: str, task_id: str, from_state: str | None
) -> bool:
    """Mark a task as quarantined through the canonical state transition.

    Returns ``True`` when the transition succeeded.
    """
    if from_state is None:
        from_state = "in_progress"
    aet_state_bin = str(_SCRIPT_DIR / "aet_state.py")
    result = subprocess.run(
        [
            sys.executable,
            aet_state_bin,
            "transition",
            task_id,
            from_state,
            "quarantined",
            queue_file,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"   🚫 {task_id} quarantined (circuit breaker)")
        return True
    print(f"   ⚠️  Could not transition {task_id} to quarantined: {result.stderr.strip()}")
    return False


def _mark_failed(
    backend, queue_file: str, task_id: str, from_state: str | None
) -> None:
    """Mark a task as failed, preferring the canonical state transition.

    Routes through ``aet-state transition`` so the stored ``state`` field is
    updated. If the transition cannot be applied because the task has already
    moved, the queue is re-read under ``queue_lock`` and the transition is
    retried from the current state. No direct ``task["state"]`` assignment is
    ever performed; if no legal transition to ``failed`` exists (e.g. the task
    is already terminal), the state is left untouched and the failure is logged.
    """
    if from_state is None:
        from_state = "in_progress"
    aet_state_bin = str(_SCRIPT_DIR / "aet_state.py")
    result = subprocess.run(
        [
            sys.executable,
            aet_state_bin,
            "transition",
            task_id,
            from_state,
            "failed",
            queue_file,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"   ⚠️  Could not transition {task_id} to failed: {result.stderr.strip()}")
        with queue_lock(queue_file):
            data = backend.load()
            queue = data["queue"]
            task = next((t for t in queue if t.get("id") == task_id), None)
            if task is None:
                print(f"   ⚠️  Task {task_id} disappeared from queue; not marking failed")
                return
            current = current_state(task)
            if current == "failed":
                return
            if current is None or "failed" not in LEGAL_TRANSITIONS.get(current, set()):
                print(
                    f"   🚫  Cannot mark {task_id} as failed from state '{current}' "
                    "(no legal transition); leaving state untouched"
                )
                return
            retry = subprocess.run(
                [
                    sys.executable,
                    aet_state_bin,
                    "transition",
                    task_id,
                    current,
                    "failed",
                    queue_file,
                ],
                capture_output=True,
                text=True,
            )
            if retry.returncode != 0:
                print(
                    f"   🚫  Could not retry transition {task_id} {current} -> failed: "
                    f"{retry.stderr.strip()}; leaving state untouched"
                )


def _maybe_auto_merge(task: dict, queue_file: str, repo_root: str) -> bool:
    """Auto-merge ``task`` if its class is enabled and meets the threshold.

    Returns True when the task was auto-merged through the record-merge closure
    path. Returns False when the task should be left for a human decision at
    the desk (the default, since the shipped policy is empty).
    """
    try:
        policy_path = os.path.join(repo_root, track_record.DEFAULT_POLICY_PATH)
        policy = track_record.load_policy(policy_path)
    except Exception:  # pragma: no cover - defensive fallback
        return False
    if not track_record.is_eligible_for_auto_merge(task, policy=policy):
        return False
    return track_record.perform_auto_merge(task, queue_file, repo_root)


def _write_task_cost(
    backend,
    queue_file: str,
    task_id: str,
    logger: telemetry.RunLogger | None,
) -> None:
    """Roll up per-task cost from telemetry and write it to the ledger record.

    Null is preserved (analytics-only): when every stage record was null, the
    field is omitted rather than written as a pair of nulls.
    """
    if logger is None:
        return
    queue = backend.load()["queue"]
    task = next((t for t in queue if t.get("id") == task_id), None)
    if task is None:
        return
    tokens, usd = _task_usage_aggregates(logger, task_id)
    if tokens is not None or usd is not None:
        task["cost"] = {"tokens": tokens, "usd": usd}
        _save_task_record(backend, queue)


def _attach_delivered_size(task: dict, repo_root: str) -> bool:
    """Record delivered diff size on the task record when the merge commit is known.

    The measurement is best-effort and analytics-only: any failure is recorded
    as a ``failed`` status with a reason and the task continues to settle. If
    no ``merge_commit`` is present yet (normal awaiting_merge closure), the
    field is left for ``append_history_record`` to populate at terminal seal
    time.

    After R-19 the declared size travels in the task record's rendered spec;
    pre-R-19 records still carrying ``plan_file`` fall back to the plan file on
    disk.

    Returns ``True`` when the task record was mutated.
    """
    merge_commit = task.get("merge_commit")
    if not merge_commit:
        return False
    size_info = plan_size.delivered_size(repo_root, merge_commit)
    routing_data = plan_parser.task_routing_data(task, repo_root=repo_root)
    declared_size = routing_data.get("size")
    task["delivered_size"] = {**size_info, "declared_size": declared_size}
    task["divergence"] = divergence.compute_divergence(
        repo_root, merge_commit, spec=task.get("spec"), task=task
    )
    return True


def _finalize_task(
    backend,
    queue_file: str,
    task_id: str,
    ret: int,
    repo_root: str | None = None,
    logger: telemetry.RunLogger | None = None,
    on_failure: str = "triage",
    adapter=None,
    worktree_dir: str | None = None,
) -> dict[str, int | bool]:
    """Finalize a single task after its child process exits.

    State changes go through ``aet-state transition``; the orchestrator avoids
    blind ``backend.save`` calls for state. The one exception is the analytics-
    only ``cost`` field, which is rolled up from stage telemetry and written to
    the task's ledger record before the transition so it is preserved when the
    task is later sealed. No control path reads ``cost`` (ADR-031).
    """
    aet_state_bin = str(_SCRIPT_DIR / "aet_state.py")
    repo_root = repo_root or os.path.dirname(os.path.dirname(queue_file))
    if ret == 0:
        queue = backend.load()["queue"]
        task = next((t for t in queue if t.get("id") == task_id), None)
        from_state = current_state(task) if task else "in_progress"
        # Single-pr mode: the child has already integrated locally, recorded the
        # merge commit, and transitioned to awaiting_merge. Seal it to merged in
        # the batch parent so dependents unblock and the queue reflects ADR-045
        # "done means integrated". The ancestry check uses the recorded merge
        # commit against the resolved integration branch.
        if task and task.get("merge_commit") and from_state == "awaiting_merge":
            result = subprocess.run(
                [
                    sys.executable,
                    aet_state_bin,
                    "transition",
                    task_id,
                    "awaiting_merge",
                    "merged",
                    queue_file,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return {"successes": 1, "failures": 0, "stop_spawn": False}
            print(
                f"   ⚠️  Could not transition {task_id} to merged: "
                f"{result.stderr.strip()}"
            )
            # Fall through to awaiting-merge bookkeeping.
        # A recorded merge_commit that is already terminal (or could not be
        # sealed above) counts as a success.
        if task and task.get("merge_commit"):
            return {"successes": 1, "failures": 0, "stop_spawn": False}
        # In single-pr mode the child may already have integrated the task and
        # transitioned it to awaiting_merge before the batch parent finalizes.
        # Trust that state rather than failing because the worktree is gone.
        if from_state == "awaiting_merge":
            return {"successes": 1, "failures": 0, "stop_spawn": False}
        if from_state == "merged":
            # Single-pr mode: process_task already integrated locally.
            return {"successes": 1, "failures": 0, "stop_spawn": False}
        # A successful child that produced no commits is a false completion.
        # Fail the task rather than promoting an empty branch to awaiting_merge.
        if task:
            worktree_rel = task.get("worktree")
            if worktree_rel:
                ok, msg = verify_branch_has_commits(os.path.join(repo_root, worktree_rel))
                if not ok:
                    print(f"   ❌ {task_id} succeeded but produced no commits: {msg}")
                    _mark_failed(backend, queue_file, task_id, current_state(task))
                    return {"successes": 0, "failures": 1, "stop_spawn": True}
        # Record delivered diff size when the merge commit is already known
        # (e.g. auto-merge closure). Normal awaiting_merge closure defers the
        # measurement to terminal seal time in ``append_history_record``.
        if task and _attach_delivered_size(task, repo_root):
            _save_task_record(backend, queue)
        # Roll up per-task cost from this run's telemetry and write it to the
        # ledger record before transition.
        _write_task_cost(backend, queue_file, task_id, logger)
        if task and _maybe_auto_merge(task, queue_file, repo_root):
            return {"successes": 1, "failures": 0, "stop_spawn": False}
        print(f"   ✅ {task_id} awaiting merge")
        result = subprocess.run(
            [
                sys.executable,
                aet_state_bin,
                "transition",
                task_id,
                from_state,
                "awaiting_merge",
                queue_file,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(
                f"   ⚠️  Could not transition {task_id} to awaiting_merge: {result.stderr.strip()}"
            )
            _mark_failed(backend, queue_file, task_id, from_state)
            return {"successes": 0, "failures": 1, "stop_spawn": True}
        return {"successes": 1, "failures": 0, "stop_spawn": False}

    print(f"   ❌ {task_id} failed (exit {ret})")
    queue = backend.load()["queue"]
    task = next((t for t in queue if t.get("id") == task_id), None)
    from_state = current_state(task) if task else "in_progress"

    # Roll up per-task cost for incident tasks too (nsr-07).
    _write_task_cost(backend, queue_file, task_id, logger)

    # Missing-plan failures are terminal misconfigurations: leave the task
    # failed and stop spawning. The child exits 2 so the parent can tell
    # this apart from a transient session failure (R-6).
    if ret == 2:
        print(f"   ⛔ {task_id} halted: plan missing from resolved base")
        _mark_failed(backend, queue_file, task_id, from_state)
        return {"successes": 0, "failures": 1, "stop_spawn": True}

    # Integration failures (exit code 3) are engine-level outcomes, not task
    # failures. The task passed; the combination did not. They are not triaged
    # and do not increment the circuit breaker (ADR-045, R-19).
    if ret == 3:
        print(f"   ❌ {task_id} integration failure; bypassing triage/requeue")
        _mark_failed(backend, queue_file, task_id, from_state)
        return {"successes": 0, "failures": 1, "stop_spawn": False}

    # Signal-killed sessions are terminal timeouts. The child process may have
    # recorded a TIMEOUT signature itself (stall watchdog), or the parent may
    # have killed it before it could. Make the exit signal authoritative so a
    # signal-killed session is never requeued just because the signature is
    # missing (osd-02).
    last_entry = (task.get("failure_signatures") or [])[-1:] if task else []
    entry = last_entry[0] if last_entry else {}
    is_timeout = (
        entry.get("class") == failure_lib.FailureClass.TIMEOUT.value or ret < 0
    )
    if is_timeout:
        if ret < 0 and entry.get("class") != failure_lib.FailureClass.TIMEOUT.value:
            # Append the authoritative timeout signature the child could not.
            _record_failure_on_task(
                backend,
                task,
                failure_lib.FailureClass.TIMEOUT,
                stage=task.get("stage") or from_state,
                tail=f"killed by signal {-ret}",
            )
        print(f"   ⏱️  {task_id} killed by timeout; leaving failed")
        _mark_failed(backend, queue_file, task_id, from_state)
        return {"successes": 0, "failures": 1, "stop_spawn": False}

    # Circuit breaker has absolute precedence over triage routing (nsr-03).
    if task and breaker.should_quarantine_task(task):
        if _mark_quarantined(backend, queue_file, task_id, from_state):
            return {"successes": 0, "failures": 1, "stop_spawn": True}

    # Establish the canonical failed state. All non-breaker failure modes route
    # from here so transitions stay legal (failed -> ready, failed -> quarantined).
    _mark_failed(backend, queue_file, task_id, from_state)
    queue = backend.load()["queue"]
    task = next((t for t in queue if t.get("id") == task_id), None)
    failed_state = current_state(task) if task else "failed"

    # A closed provider window is shared by every task in the run, so the
    # remedy is to stop and come back — not to triage, not to keep spawning
    # into the same wall. This overrides `--on-failure continue` deliberately:
    # continuing would burn the rest of the queue on the same limit.
    throttled = failure_lib.FailureClass.THROTTLED.value
    if ((task.get("failure_signatures") or [{}])[-1].get("class") if task else None) == throttled:
        requeued = _requeue_task(
            backend, queue_file, task_id, failed_state, aet_state_bin
        )
        print(
            f"   ⏸️  {task_id} hit a provider limit; "
            f"{'requeued and ' if requeued else ''}stopping the run. "
            "Re-run once the window resets."
        )
        return {
            "successes": 0,
            "failures": 0 if requeued else 1,
            "stop_spawn": True,
        }

    if on_failure == "halt":
        return {"successes": 0, "failures": 1, "stop_spawn": True}

    if on_failure == "continue":
        return {"successes": 0, "failures": 1, "stop_spawn": False}

    # on_failure == "triage" (default).
    last_entry = (task.get("failure_signatures") or [])[-1:] if task else []
    entry = last_entry[0] if last_entry else {}
    failure_class_name = entry.get("class", failure_lib.FailureClass.ENVIRONMENT.value)
    stage = entry.get("stage", "")
    tail = entry.get("tail_preview", "")
    signature = entry.get("signature", "")

    verdict = None
    triage_skipped = False
    if not triage.has_sufficient_evidence(tail=tail, signature=signature):
        triage_skipped = True
        print(f"   ⚠️  Triage for {task_id} skipped: insufficient evidence (no tail or signature)")
    elif adapter is not None and worktree_dir is not None:
        try:
            failure_class = failure_lib.FailureClass(failure_class_name)
        except ValueError:
            failure_class = failure_lib.FailureClass.ENVIRONMENT
        verdict = _consult_triage_session(
            adapter,
            repo_root,
            worktree_dir,
            task_id=task_id,
            stage=stage,
            failure_class=failure_class,
            tail=tail,
            signature=signature,
        )

    action = verdict.get("action") if verdict else None
    if action is None:
        # Fail-closed: unparseable or errored triage falls back to the
        # deterministic classifier default (nsr-01).
        action = _TRIAGE_DEFAULT_ACTIONS.get(failure_class_name, "requeue")
        if not triage_skipped:
            print(f"   ⚠️  Triage for {task_id} failed closed; using {action} ({failure_class_name})")

    triage_outcome = "skipped" if triage_skipped else ("triaged" if verdict else "failed_closed")
    if logger is not None:
        logger.append_record(
            telemetry.triage_record(
                run_id=logger.run_id,
                task_id=task_id,
                plan_file=task.get("plan_file") if task else None,
                outcome=triage_outcome,
                action=action,
                failure_class=failure_class_name,
                reason="insufficient_evidence" if triage_skipped else None,
            ),
            task_id=task_id,
        )

    if action == "quarantine":
        if _mark_quarantined(backend, queue_file, task_id, failed_state):
            return {"successes": 0, "failures": 1, "stop_spawn": True, "triage_outcome": triage_outcome}
        # If quarantine transition fails, fall through to requeue/failed.

    # action == "requeue" (or quarantine transition failed): failed -> ready.
    if _requeue_task(backend, queue_file, task_id, failed_state, aet_state_bin):
        print(f"   🔄 {task_id} requeued")
        return {"successes": 0, "failures": 0, "stop_spawn": False, "triage_outcome": triage_outcome}
    return {"successes": 0, "failures": 1, "stop_spawn": False, "triage_outcome": triage_outcome}


def run_batch(args: argparse.Namespace, adapter) -> int:
    """Run batch mode from queue file."""
    queue_file = args.queue_file
    repo_root = args.repo_root
    max_jobs = min(args.max_jobs, 8)
    backend = _make_backend(queue_file)
    backend.fetch()
    breaker_store = breaker.BreakerStore(repo_root)
    systemic_tally = breaker_store.load()

    logger = telemetry.RunLogger(repo_root, run_id=getattr(args, "run_id", None))
    _write_telemetry_path(repo_root, logger.run_id, logger.run_dir)
    start_time = telemetry.iso_now()
    task_ids: list[str] = []

    try:
        queue = backend.load()["queue"]
    except QueueIntegrityError as exc:
        # Fail closed before spawning anything: a tampered queue must be
        # repaired explicitly (audit / heal --apply), not crashed into with a
        # traceback mid-batch (ADR-024).
        print(f"⛔ {exc}", file=sys.stderr)
        return 1
    if not queue:
        print("✅ Queue is empty.")
        end_time = telemetry.iso_now()
        logger.write_last_run(
            telemetry.run_summary_record(
                run_id=logger.run_id,
                start_time=start_time,
                end_time=end_time,
                tasks_spawned=0,
                tasks_succeeded=0,
                tasks_failed=0,
                outcome="success",
                exit_code=0,
                task_ids=[],
                final_stage=None,
            )
        )
        print(f"   📁 Telemetry: {logger.run_dir}")
        return 0

    # If a prior shift already tripped the systemic breaker, stop before
    # spawning anything. The tally persists across shifts (R-6).
    if breaker.systemic_tripped(systemic_tally):
        report = breaker.systemic_report(systemic_tally)
        print(f"⛔ {report}")
        end_time = telemetry.iso_now()
        logger.write_last_run(
            telemetry.run_summary_record(
                run_id=logger.run_id,
                start_time=start_time,
                end_time=end_time,
                tasks_spawned=0,
                tasks_succeeded=0,
                tasks_failed=0,
                outcome="failure",
                exit_code=1,
                task_ids=[],
                final_stage=None,
            )
        )
        print(f"   📁 Telemetry: {logger.run_dir}")
        return 1

    print("🚀 Batch orchestrator starting")
    print(f"   Queue: {queue_file}")
    print(f"   Concurrency: {max_jobs}")
    print(f"   Telemetry: {logger.run_dir}")
    print()

    # Resolve trunk and integration branch once per run so every consumer
    # agrees on the base (ADR-044), while still allowing --base /
    # AET_WORK_BASE_BRANCH to override the integration branch.
    config = resolve_config(DEFAULT_CONFIG_PATH, repo_root=repo_root)
    trunk = resolve_trunk_branch(repo_root, config)
    integration = resolve_integration_branch(
        repo_root, config, cli_base=getattr(args, "base", None)
    )
    base_branch = resolve_base_ref(repo_root, integration.ref)
    print(f"   Trunk: {trunk.ref} ({trunk.provenance})")
    print(f"   Integration: {integration.ref} ({integration.provenance})")
    print(f"   Worktree base: {base_branch}")

    # Check base hygiene
    if not enforce_base_hygiene(repo_root, integration.ref, trunk.ref):
        end_time = telemetry.iso_now()
        logger.write_last_run(
            telemetry.run_summary_record(
                run_id=logger.run_id,
                start_time=start_time,
                end_time=end_time,
                tasks_spawned=0,
                tasks_succeeded=0,
                tasks_failed=0,
                outcome="failure",
                exit_code=1,
                task_ids=[],
                final_stage=None,
            )
        )
        return 1

    print("   📋 Plan durability is deferred to the PR (docs/plans/ only).")

    # Resolve integration_mode once per run through the external-first config
    # chain so every task in the batch sees the same value.
    try:
        integration_mode = resolve_integration_mode(DEFAULT_CONFIG_PATH, repo_root=repo_root)
    except Exception as exc:
        print(f"⛔ Could not resolve integration_mode: {exc}")
        end_time = telemetry.iso_now()
        logger.write_last_run(
            telemetry.run_summary_record(
                run_id=logger.run_id,
                start_time=start_time,
                end_time=end_time,
                tasks_spawned=0,
                tasks_succeeded=0,
                tasks_failed=0,
                outcome="failure",
                exit_code=1,
                task_ids=[],
                final_stage=None,
            )
        )
        return 1

    # Declare that this run owns the queue so out-of-band mutators refuse, and
    # ensure every subprocess inherits the run id for the lease check.
    os.environ["AET_RUN_ID"] = logger.run_id

    running: dict[str, subprocess.Popen] = {}
    spawn_times: dict[str, float] = {}
    successes = 0
    failures = 0
    stop_spawn = False
    last_heartbeat = time.monotonic()
    summary_written = False
    leftover_report: dict[str, int] = {}
    teardown_leftovers: list[str] = []
    task_timeout = getattr(args, "task_timeout", 3600)
    heartbeat_interval = getattr(args, "heartbeat_interval", 60)

    def _write_summary(outcome: str, exit_code: int) -> None:
        nonlocal summary_written
        if summary_written:
            return
        summary_written = True
        end_time = telemetry.iso_now()
        total_tokens, total_cost_usd = _usage_aggregates(logger)
        logger.write_last_run(
            telemetry.run_summary_record(
                run_id=logger.run_id,
                start_time=start_time,
                end_time=end_time,
                tasks_spawned=len(task_ids),
                tasks_succeeded=successes,
                tasks_failed=failures,
                outcome=outcome,
                exit_code=exit_code,
                task_ids=task_ids,
                final_stage=None,
                leftover=(
                    {**leftover_report, "teardown": len(teardown_leftovers)}
                    if leftover_report or teardown_leftovers
                    else None
                ),
                total_tokens=total_tokens,
                total_cost_usd=total_cost_usd,
            )
        )
        logger.copy_work_history(os.path.join(repo_root, ".agents", "work-history.jsonl"))
        print()
        print("🏁 Orchestrator finished.")
        print(f"   Succeeded: {successes}")
        print(f"   Failed:    {failures}")
        if leftover_report:
            print(f"   Leftover:  {format_leftover_report(leftover_report)}")
        if teardown_leftovers:
            print(f"   Teardown failures: {', '.join(teardown_leftovers)}")
        print(f"   Telemetry: {logger.run_dir}")

    def _cleanup_task(task_id: str, ret: int) -> None:
        nonlocal successes, failures, stop_spawn, systemic_tally
        running.pop(task_id, None)
        spawn_times.pop(task_id, None)
        queue = backend.load()["queue"]
        task = next((t for t in queue if t.get("id") == task_id), None)
        worktree_rel = task.get("worktree") if task else None
        worktree_dir = (
            os.path.join(repo_root, worktree_rel) if worktree_rel else None
        )
        deltas = _finalize_task(
            backend,
            queue_file,
            task_id,
            ret,
            repo_root=repo_root,
            logger=logger,
            on_failure=getattr(args, "on_failure", "triage"),
            adapter=adapter,
            worktree_dir=worktree_dir,
        )
        successes += deltas["successes"]
        failures += deltas["failures"]
        if deltas["stop_spawn"]:
            stop_spawn = True
        # Update the systemic breaker tally on every failure. A signature that
        # reaches the threshold across distinct tasks stops the shift.
        if ret != 0:
            queue = backend.load()["queue"]
            task = next((t for t in queue if t.get("id") == task_id), None)
            if task is not None:
                seen_sigs = {
                    entry.get("signature")
                    for entry in task.get("failure_signatures", [])
                    if entry.get("signature") and entry.get("countable") is not False
                }
                for sig in seen_sigs:
                    systemic_tally = breaker.update_systemic_tally(
                        systemic_tally, task_id, sig
                    )
                breaker_store.save(systemic_tally)
                if breaker.systemic_tripped(systemic_tally):
                    report = breaker.systemic_report(systemic_tally)
                    print(f"⛔ {report}")
                    stop_spawn = True
        teardown = teardown_worktree(repo_root, task_id)
        if not teardown["removed"]:
            obstruction_text = (
                _format_paths(teardown.get("obstructions", []))
                or teardown.get("reason", "unknown")
            )
            print(
                f"   ⚠️  Worktree teardown failed for {task_id}: {obstruction_text}"
            )
            teardown_leftovers.append(task_id)

    # Refuse at startup rather than seizing the queue and letting the incumbent
    # run discover it one failed write at a time. Acquired outside the try so a
    # refusal never reaches the finally that releases another run's lease.
    try:
        acquire_lease(queue_file, logger.run_id, force=getattr(args, "force", False))
    except LeaseHeldError as exc:
        print(f"⛔ {exc}")
        print(
            "   Another run owns this queue; starting now would leave that run "
            "unable to record its work. Wait for it to finish. If that run is "
            "dead, its lease is reclaimed automatically on the next attempt."
        )
        return 1

    try:
        while True:
            # Refresh stored state before each spawn pass.
            queue = backend.load()["queue"]

            # Spawn tasks while slots available
            spawned_this_cycle: set[str] = set()
            while len(running) < max_jobs and not stop_spawn and not _shutdown_requested:
                task = get_next_ready_task(queue)
                if not task:
                    break

                task_id = task["id"]
                if task_id in spawned_this_cycle:
                    # Defensive: stored state is stale and keeps returning the same task.
                    break

                # Transition the task to in_progress through the sole writer so
                # stored state reflects that it has been picked up.
                from_state = current_state(task) or "ready"
                aet_state_bin = str(_SCRIPT_DIR / "aet_state.py")
                result = subprocess.run(
                    [
                        sys.executable,
                        aet_state_bin,
                        "transition",
                        task_id,
                        from_state,
                        "in_progress",
                        queue_file,
                    ],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    print(
                        f"   ⚠️  Could not transition {task_id} to in_progress: {result.stderr.strip()}"
                    )
                    _mark_failed(backend, queue_file, task_id, from_state)
                    failures += 1
                    stop_spawn = True
                    break

                # Re-read queue after transition and record branch/worktree so the
                # stored state reflects in_progress and does not spawn the same task
                # again on the next loop iteration.
                try:
                    worktree_dir = create_worktree(
                        repo_root, task_id, base_branch=base_branch
                    )
                except WorktreeBlockedError as exc:
                    print(f"   {exc}")
                    _mark_failed(backend, queue_file, task_id, "in_progress")
                    failures += 1
                    stop_spawn = True
                    break
                env = os.environ.copy()
                env["AET_TASK_ID"] = task_id
                env["AET_PLAN_FILE"] = task.get("plan_file", "")
                env["AET_WORKTREE"] = worktree_dir
                env["AET_RUN_ID"] = logger.run_id
                env["AET_REPO_ROOT"] = repo_root
                env["AET_STAGE"] = task.get("stage") or ""
                env["AET_INTEGRATION_MODE"] = integration_mode

                # Store a repo-relative worktree path for portability under lock.
                # base_commit records where the branch started (ADR-064); without
                # it the task can never derive merged from branch ancestry.
                base_commit = resolve_base_commit(repo_root, task_id)
                with queue_lock(queue_file):
                    queue = backend.load()["queue"]
                    record_task_meta(
                        queue,
                        task_id,
                        os.path.relpath(worktree_dir, repo_root),
                        task_id,
                        base_commit=base_commit,
                    )
                    backend.save(queue)
                backend.push()

                # Build the orchestrator command for single-task mode.
                # Stall timeout is resolved from the selected CLI adapter inside
                # the child orchestrator (ADR-053); do not pass --stall-timeout.
                cmd = [
                    sys.executable,
                    __file__,
                    "--plan-file",
                    task.get("plan_file", ""),
                    "--repo-root",
                    repo_root,
                    "--cli-bin",
                    adapter.bin,
                    "--base",
                    integration.ref,
                    "--isolation",
                    args.isolation,
                    "--on-failure",
                    getattr(args, "on_failure", "triage"),
                ]

                proc = subprocess.Popen(cmd, env=env, start_new_session=True)
                running[task_id] = proc
                spawn_times[task_id] = time.monotonic()
                spawned_this_cycle.add(task_id)
                task_ids.append(task_id)
                print(f"▶️  Spawned {task.get('title', task_id)} (PID {proc.pid})")

                # Refresh stored state so the next spawn pass respects the branch we
                # just recorded and does not pick the same task again.
                queue = backend.load()["queue"]

            if not running:
                if stop_spawn or _shutdown_requested:
                    break
                if has_actionable_tasks(queue, running.keys()):
                    time.sleep(0.2)
                    continue
                # Nothing running and nothing that can still make progress on its
                # own (a ready/in_progress task). Whatever remains is stranded
                # until an external actor moves it, so exit with a leftover
                # report instead of spinning forever on the sleep.
                leftover_report.update(leftover_counts(queue))
                break

            # Poll for finished or timed-out processes
            now = time.monotonic()
            finished: list[tuple[str, int]] = []
            for task_id, proc in list(running.items()):
                ret = proc.poll()
                if ret is not None:
                    finished.append((task_id, ret))
                elif now - spawn_times[task_id] > task_timeout:
                    print(f"   ⏱️  {task_id} timed out after {args.task_timeout}s")
                    _terminate_process_group(proc, timeout=10)
                    finished.append((task_id, -9))

            for task_id, ret in finished:
                _cleanup_task(task_id, ret)

            # Heartbeat
            if now - last_heartbeat > heartbeat_interval:
                print(
                    f"   💓 Heartbeat: {len(running)} running, "
                    f"{successes} succeeded, {failures} failed"
                )
                last_heartbeat = now

            if _shutdown_requested:
                print("   ⚠️  Shutdown requested, stopping batch loop")
                break

            if not finished:
                time.sleep(0.2)

    finally:
        # Guarantee cleanup/summary even if the orchestrator crashes or is killed.
        for task_id, proc in list(running.items()):
            if proc.poll() is None:
                print(f"   ⚠️  Terminating leftover task {task_id}")
                _terminate_process_group(proc, timeout=10)
            _cleanup_task(task_id, -1)

        exit_code = 1 if failures > 0 else 0
        outcome = "success" if exit_code == 0 else "failure"
        _write_summary(outcome, exit_code)
        release_lease(queue_file, logger.run_id)

    return exit_code


def _find_queued_task(queue: list[dict], plan_file: str) -> dict | None:
    """Find a queued task that corresponds to ``plan_file``.

    Prefer an exact match on ``plan_file``. Fall back to matching the task
    ``id`` against the plan filename stem (with any ``-plan`` suffix removed).
    """
    plan_abs = os.path.abspath(plan_file)

    # First pass: exact path match (normalize both sides).
    for task in queue:
        task_plan = task.get("plan_file", "")
        if not task_plan:
            continue
        try:
            if os.path.abspath(task_plan) == plan_abs:
                return task
        except OSError:
            continue

    # Second pass: task id matches filename stem.
    stem = os.path.splitext(os.path.basename(plan_file))[0]
    task_id = stem.removesuffix("-plan")
    for task in queue:
        if task.get("id") == task_id:
            return task

    return None


# Errors that indicate broken code rather than an environmental failure.
# These are never swallowed by tolerant bookkeeping handlers: continuing after
# one would silently drop queue bookkeeping for the entire run.
_PROGRAMMING_ERRORS = (NameError, AttributeError, TypeError, ImportError)


def _record_run_one_in_queue(
    backend,
    queue_file: str,
    task_id: str,
    worktree: str,
    branch: str,
    repo_root: str,
    intake_skipped: list[str] | None = None,
) -> bool:
    """Transition a queued task to in-progress and record branch/worktree.

    Uses ``aet-state transition`` to keep the queue's sole-writer rule intact,
    then re-reads the queue through the backend and records worktree/branch
    metadata atomically via ``backend.save``. Environmental errors (lock
    contention, IO, queue data) are logged but not raised so that a queue
    bookkeeping failure does not block the underlying run. Programming errors
    (``_PROGRAMMING_ERRORS``) are re-raised — they mean the bookkeeping code
    itself is broken, and continuing would silently drop metadata.

    ``intake_skipped`` names the check ids a ``--skip-intake`` run bypassed. It
    is stamped on the record so the audit trail can answer whether a task
    passed intake; an empty bypass leaves the field off entirely, so its
    presence means exactly one thing.
    """
    try:
        queue = backend.load()["queue"]
        task = next((t for t in queue if t.get("id") == task_id), None)
        if not task:
            print(f"   ⚠️  Task {task_id} disappeared from queue; skipping bookkeeping")
            return False

        from_state = current_state(task)
        if from_state is None:
            from_state = "planned"

        aet_state_bin = str(_SCRIPT_DIR / "aet_state.py")
        result = subprocess.run(
            [
                sys.executable,
                aet_state_bin,
                "transition",
                task_id,
                from_state,
                "in_progress",
                queue_file,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"   ⚠️  Could not transition {task_id} to in_progress: {result.stderr.strip()}")
            return False

        # Re-read the latest queue under lock and record branch/worktree.
        base_commit = resolve_base_commit(repo_root, branch)
        with queue_lock(queue_file):
            queue = backend.load()["queue"]
            record_task_meta(queue, task_id, worktree, branch, base_commit=base_commit)
            if intake_skipped:
                recorded = next((t for t in queue if t.get("id") == task_id), None)
                if recorded is not None:
                    recorded["intake_skipped"] = sorted(set(intake_skipped))
            backend.save(queue)
        backend.push()
        print(f"   📝 Recorded {task_id} as in-progress (branch={branch}, worktree={worktree})")
        return True
    except _PROGRAMMING_ERRORS:
        raise
    except Exception as exc:
        print(f"   ⚠️  Queue bookkeeping failed for {task_id}: {exc}")
        return False


def _intake_findings(plan_file: str, repo_root: str, backend) -> list:
    """Unacked intake findings for ``plan_file``, judged as ``sprint add`` judges.

    Same suite, same corpus, same record-sourced r-trace coverage, same ack
    escape hatch. Answering differently here is what made intake advisory: a
    plan the board door refuses runs through ``run-one`` unchanged.

    Returns an empty list when validation cannot run at all, so a broken
    checkout does not become a refusal to work.
    """
    from aet import plan_validate

    root = Path(repo_root)
    plan_path = Path(plan_file)
    plans_dir = root / "docs" / "plans"
    try:
        all_plans = sorted(plans_dir.glob("*.md")) if plans_dir.is_dir() else []
        if plan_path not in all_plans:
            all_plans.append(plan_path)
        record = plan_validate.coverage_from_backend(backend, root)
        findings = plan_validate.validate(
            all_plans, repo_root=root, extra_coverage=record.coverage
        )
        texts = {p: p.read_text(errors="ignore") for p in all_plans if p.is_file()}
        findings = plan_validate.apply_acks(findings, texts)
    except (OSError, ValueError):
        return []
    return [f for f in findings if f.plan == plan_path and not f.acked]


def run_single(args: argparse.Namespace, adapter) -> int:
    """Run single-plan mode."""
    repo_root = args.repo_root
    plan_file = args.plan_file

    run_id = getattr(args, "run_id", None) or os.environ.get("AET_RUN_ID")
    logger = telemetry.RunLogger(repo_root, run_id=run_id)
    _write_telemetry_path(repo_root, logger.run_id, logger.run_dir)
    # Ensure every subprocess (aet-state calls and stage sessions) inherits this
    # run id so their queue mutations pass the lease check.
    os.environ["AET_RUN_ID"] = logger.run_id
    queue_file = os.path.join(repo_root, ".agents", "aet-queue")
    start_time = telemetry.iso_now()

    if not os.path.isabs(plan_file):
        plan_file = os.path.join(repo_root, plan_file)

    # When spawned by the batch orchestrator, the parent has already verified
    # base hygiene and will dirty the working tree by updating the queue file
    # between spawning tasks. Re-checking here would deadlock the pipeline.
    spawned_by_batch = bool(os.environ.get("AET_TASK_ID"))

    # Intake applies at every door onto the board, not only at `sprint add`.
    # A batch child's task already passed it on the way in, and re-judging a
    # plan mid-flight would fail a run for a PRD edited after promotion.
    skip_intake = bool(getattr(args, "skip_intake", False))
    intake_unacked: list = []
    if not spawned_by_batch:
        intake_backend = _make_backend(queue_file)
        try:
            intake_unacked = _intake_findings(plan_file, repo_root, intake_backend)
        finally:
            intake_backend.close()
    if intake_unacked and not skip_intake:
        print(
            f"⛔ Refusing to run {os.path.basename(plan_file)}: "
            "intake validation failed."
        )
        for finding in intake_unacked:
            print(f"  - {finding.check_id}: {finding.message}")
        print("  Fix the plan, or override a check that does not apply by adding")
        print("  a line to it:")
        print("    ⚠️ VALIDATE ACK: <check-id> — <reason>")
        print("  To run anyway and have the bypass recorded: --skip-intake")
        logger.write_last_run(
            telemetry.run_summary_record(
                run_id=logger.run_id,
                start_time=start_time,
                end_time=telemetry.iso_now(),
                tasks_spawned=0,
                tasks_succeeded=0,
                tasks_failed=1,
                outcome="failure",
                exit_code=1,
                task_ids=[],
                final_stage=None,
            )
        )
        return 1
    if intake_unacked:
        print(
            f"⚠️  Running {os.path.basename(plan_file)} with intake validation "
            f"skipped: {len(intake_unacked)} unacked finding(s)."
        )
        for finding in intake_unacked:
            print(f"  - {finding.check_id}: {finding.message}")

    # Resolve trunk and integration branch once per run so every consumer
    # agrees on the base (ADR-044). Batch children inherit the parent's
    # resolution via --base / AET_WORK_BASE_BRANCH if set, but still need the
    # local trunk/integration for aet-state calls made from this process.
    config = resolve_config(DEFAULT_CONFIG_PATH, repo_root=repo_root)
    trunk = resolve_trunk_branch(repo_root, config)
    integration = resolve_integration_branch(
        repo_root, config, cli_base=getattr(args, "base", None)
    )
    base_branch = resolve_base_ref(repo_root, integration.ref)

    # Check base hygiene before any worktree work — but only for top-level
    # run-one invocations. Batch children rely on the parent-level check.
    if not spawned_by_batch and not enforce_base_hygiene(repo_root, integration.ref, trunk.ref):
        end_time = telemetry.iso_now()
        logger.write_last_run(
            telemetry.run_summary_record(
                run_id=logger.run_id,
                start_time=start_time,
                end_time=end_time,
                tasks_spawned=0,
                tasks_succeeded=0,
                tasks_failed=1,
                outcome="failure",
                exit_code=1,
                task_ids=[],
                final_stage=None,
            )
        )
        print(f"   📁 Telemetry: {logger.run_dir}")
        return 1

    print("   📋 Plan durability is deferred to the PR (docs/plans/ only).")

    # Resolve the workflow once per task and thread it through process_task.
    # A missing or invalid workflow file fails the run loudly at task start;
    # the packaged default is the only fallback.
    try:
        plan_fm = plan_parser.parse_frontmatter(Path(plan_file))
    except OSError:
        plan_fm = {}
    workflow_name = plan_fm.get("workflow") or "software"
    try:
        wf = load_workflow(repo_root, workflow_name)
    except WorkflowError as exc:
        print(f"   ❌ {exc}")
        end_time = telemetry.iso_now()
        logger.write_last_run(
            telemetry.run_summary_record(
                run_id=logger.run_id,
                start_time=start_time,
                end_time=end_time,
                tasks_spawned=0,
                tasks_succeeded=0,
                tasks_failed=1,
                outcome="failure",
                exit_code=1,
                task_ids=[],
                final_stage=None,
            )
        )
        print(f"   📁 Telemetry: {logger.run_dir}")
        return 1

    # For a top-level run-one, declare that this run owns the queue so
    # out-of-band mutators refuse. Batch children share the parent's lease via
    # AET_RUN_ID and must not acquire/release their own.
    owns_lease = False
    if not spawned_by_batch:
        # Refuse at startup; see run_batch. Batch children share the parent's
        # lease via AET_RUN_ID and never reach this branch.
        try:
            acquire_lease(
                queue_file, logger.run_id, force=getattr(args, "force", False)
            )
        except LeaseHeldError as exc:
            print(f"⛔ {exc}")
            print(
                "   Another run owns this queue; starting now would leave that "
                "run unable to record its work. Wait for it to finish. If that "
                "run is dead, its lease is reclaimed automatically."
            )
            return 1
        owns_lease = True

    try:

        # Create a synthetic task. Prefer the batch-provided task ID/worktree so
        # parent and child agree on worktree/branch names (e.g. "*-plan" suffixes).
        base_name = os.path.splitext(os.path.basename(plan_file))[0]
        task_id = os.environ.get("AET_TASK_ID") or base_name.removesuffix("-plan")
        worktree_dir = os.environ.get("AET_WORKTREE")
        if worktree_dir and not os.path.isabs(worktree_dir):
            worktree_dir = os.path.join(repo_root, worktree_dir)

        # If this plan is tracked in the work queue and this is a top-level run-one
        # (not a child spawned by run_batch), transition the task to in-progress
        # and record branch/worktree so aet-state record-merge works after shipping.
        backend = _make_backend(queue_file)
        backend.fetch()
        queued_task = None
        if not spawned_by_batch:
            queue = backend.load()["queue"]
            queued_task = _find_queued_task(queue, plan_file)

        if queued_task and not spawned_by_batch:
            queued_task_id = queued_task.get("id", task_id)
            # Ensure the worktree/branch exist before recording them.
            try:
                worktree_dir = create_worktree(
                    repo_root, queued_task_id, base_branch=base_branch
                )
            except WorktreeBlockedError as exc:
                print(f"   {exc}")
                logger.write_last_run(
                    telemetry.run_summary_record(
                        run_id=logger.run_id,
                        start_time=start_time,
                        end_time=telemetry.iso_now(),
                        tasks_spawned=0,
                        tasks_succeeded=0,
                        tasks_failed=1,
                        outcome="failure",
                        exit_code=4,
                        task_ids=[queued_task_id],
                        final_stage=None,
                    )
                )
                print(f"   📁 Telemetry: {logger.run_dir}")
                return 4
            worktree_rel = os.path.relpath(worktree_dir, repo_root)
            _record_run_one_in_queue(
                backend,
                queue_file,
                queued_task_id,
                worktree_rel,
                queued_task_id,
                repo_root,
                intake_skipped=[f.check_id for f in intake_unacked],
            )
            task_id = queued_task_id

        # Prefer the real queued task record so failure signatures are
        # persisted on the ledger (nsr-03). Fall back to a synthetic record for
        # manual run-one invocations that are not tracked in the queue.
        queue = backend.load()["queue"]
        real_task = next((t for t in queue if t.get("id") == task_id), None)
        env_stage = os.environ.get("AET_STAGE") or None
        if real_task is not None:
            task = real_task
            task["plan_file"] = plan_file
            # Batch children pass AET_STAGE so a stale footer does not fool
            # process_task; prefer the env value over whatever is on record.
            if env_stage:
                task["stage"] = env_stage
        else:
            task = {
                "id": task_id,
                "title": task_id,
                "plan_file": plan_file,
                "stage": env_stage,
            }

        # Inherit the mode resolved once by a batch parent, or resolve it now
        # for a top-level run. This guarantees one mode per run.
        integration_mode = os.environ.get("AET_INTEGRATION_MODE")
        if integration_mode is None:
            integration_mode = resolve_integration_mode(
                DEFAULT_CONFIG_PATH, repo_root=repo_root
            )

        print(f"📁 Telemetry: {logger.run_dir}")
        success = False
        try:
            success = process_task(
                task,
                repo_root,
                adapter,
                args.isolation,
                logger=logger,
                worktree_dir=worktree_dir,
                workflow=wf,
                backend=backend,
                stall_timeout=None,
                base_branch=base_branch,
                integration_mode=integration_mode,
            )
            exit_code = 0 if success else 1
        except MissingPlanError as exc:
            print(f"   {exc}")
            success = False
            exit_code = 2
        except WorktreeBlockedError as exc:
            print(f"   {exc}")
            success = False
            exit_code = 4
        except IntegrationFailureError as exc:
            print(f"   {exc}")
            success = False
            exit_code = 3
        except LeaseRefusedError as exc:
            # Not a failure of the work: the commits are on the branch and the
            # verdicts are on disk. Abort without touching the task's recorded
            # state so it resumes once the lease clears.
            print(f"   ⛔ {exc}")
            print(
                f"   ↩️  Leaving {task_id} state untouched; re-run after the "
                f"owning run finishes."
            )
            success = False
            exit_code = LEASE_HELD_EXIT_CODE

        # Roll up per-task cost from this child's telemetry and persist it on the
        # queued task record. The batch parent later seals state, but cost must
        # be captured by the process that generated the stage records (nsr-07).
        if real_task is not None:
            queue = backend.load()["queue"]
            queue_task = next((t for t in queue if t.get("id") == task_id), None)
            if queue_task:
                tokens, usd = _task_usage_aggregates(logger, task_id)
                if tokens is not None or usd is not None:
                    queue_task["cost"] = {"tokens": tokens, "usd": usd}
                    _save_task_record(backend, queue)

        # For top-level run-one on a queued task, mirror run_batch and transition
        # the task to awaiting_merge on success so aet-state record-merge can run.
        # In single-pr mode process_task has already integrated the task locally
        # and transitioned it to merged, so skip the awaiting_merge step.
        if success and queued_task and not spawned_by_batch:
            try:
                queue = backend.load()["queue"]
                queue_task = next((t for t in queue if t.get("id") == task_id), None)
                if queue_task:
                    from_state = current_state(queue_task) or "in_progress"
                    if from_state == "merged":
                        print(f"   ✅ Task {task_id} merged locally (single-pr)")
                    else:
                        worktree_rel = queue_task.get("worktree")
                        if worktree_rel:
                            ok, msg = verify_branch_has_commits(
                                os.path.join(repo_root, worktree_rel)
                            )
                            if not ok:
                                print(f"   ❌ Task {task_id} succeeded but produced no commits: {msg}")
                                _mark_failed(backend, queue_file, task_id, from_state)
                                exit_code = 1
                            else:
                                tokens, usd = _task_usage_aggregates(logger, task_id)
                                if tokens is not None or usd is not None:
                                    queue_task["cost"] = {"tokens": tokens, "usd": usd}
                                    _save_task_record(backend, queue)
                                if _maybe_auto_merge(queue_task, queue_file, repo_root):
                                    pass  # perform_auto_merge prints success/failure.
                                else:
                                    aet_state_bin = str(_SCRIPT_DIR / "aet_state.py")
                                    result = subprocess.run(
                                        [
                                            sys.executable,
                                            aet_state_bin,
                                            "transition",
                                            task_id,
                                            from_state,
                                            "awaiting_merge",
                                            queue_file,
                                        ],
                                        capture_output=True,
                                        text=True,
                                    )
                                    if result.returncode == 0:
                                        print(f"   ✅ Task {task_id} awaiting merge")
                                    else:
                                        print(
                                            f"   ⚠️  Could not transition {task_id} to "
                                            f"awaiting_merge: {result.stderr.strip()}"
                                        )
            except Exception as exc:  # pragma: no cover - defensive logging
                print(f"   ⚠️  Could not mark {task_id} awaiting merge: {exc}")

        end_time = telemetry.iso_now()

        # Read the final stage from the synthetic task record.
        final_stage = task.get("stage") or read_plan_stage(plan_file) or wf.entry_stage

        total_tokens, total_cost_usd = _usage_aggregates(logger)
        logger.write_last_run(
            telemetry.run_summary_record(
                run_id=logger.run_id,
                start_time=start_time,
                end_time=end_time,
                tasks_spawned=1,
                tasks_succeeded=1 if success else 0,
                tasks_failed=0 if success else 1,
                outcome="success" if success else "failure",
                exit_code=exit_code,
                task_ids=[task_id],
                final_stage=final_stage,
                total_tokens=total_tokens,
                total_cost_usd=total_cost_usd,
            )
        )
        if not spawned_by_batch:
            logger.copy_work_history(os.path.join(repo_root, ".agents", "work-history.jsonl"))
        return exit_code
    finally:
        if owns_lease:
            release_lease(queue_file, logger.run_id)


def _announce_posture(posture: str) -> None:
    """Print posture notice once per run when in shadow mode."""
    if posture == SHADOW_POSTURE:
        print(
            "[posture] Shadow posture: no project-scope config found. "
            "refs/aet/* will not be pushed. "
            "Run `aet configure --scope team` to share this project across devices."
        )


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    adapter = resolve_cli_adapter(args.cli_bin)

    # Supervision defaults resolve from the active adapter (ADR-053). The
    # wall-clock backstop remains overridable via --task-timeout; when omitted
    # it defaults to the adapter's coarse ceiling.
    if args.task_timeout is None:
        args.task_timeout = int(adapter.wall_backstop)

    repo_root = args.repo_root
    run_id = args.run_id

    # Infer posture from the presence/absence of project-scope config and
    # announce it once per run. Shadow is the safe default: refs/aet/* are not
    # pushed and no projections run.
    posture = resolve_posture(DEFAULT_CONFIG_PATH, repo_root=repo_root)
    _announce_posture(posture)

    if run_id:
        _redirect_output(args.log_file)
        _write_run_metadata(repo_root, run_id)

    print(f"🤖 Orchestrator using {adapter.name} ({adapter.bin})")
    if run_id:
        print(f"   Run ID: {run_id}")

    exit_code = 1
    try:
        if args.queue_file:
            exit_code = run_batch(args, adapter)
        else:
            exit_code = run_single(args, adapter)
    finally:
        if run_id:
            _write_returncode(repo_root, run_id, exit_code)
    return exit_code


app = typer.Typer(
    name="orchestrator",
    help="AE Toolkit Unified Orchestrator",
)


def _isolation_choice(value: str) -> str:
    if value not in ("minimal", "standard", "full"):
        raise typer.BadParameter("must be one of: minimal, standard, full")
    return value


def _on_failure_choice(value: str) -> str:
    if value not in ("triage", "continue", "halt"):
        raise typer.BadParameter("must be one of: triage, continue, halt")
    return value


@app.callback(invoke_without_command=True)
def orchestrator_callback(
    ctx: typer.Context,
    queue_file: Optional[str] = typer.Option(
        None,
        "--queue-file",
        help="Path to queue anchor (batch mode).",
    ),
    plan_file: Optional[str] = typer.Option(
        None,
        "--plan-file",
        help="Path to a single plan.md (single-plan mode).",
    ),
    repo_root: str = typer.Option(
        os.getcwd(),
        "--repo-root",
        help="Repository root path.",
    ),
    cli_bin: Optional[str] = typer.Option(
        None,
        "--cli-bin",
        help=(
            "Agent CLI binary path. Defaults to the agent CLI that invoked aet; "
            "required when no agent CLI is detected."
        ),
    ),
    base: Optional[str] = typer.Option(
        None,
        "--base",
        help="Override the worktree base branch/ref (default: origin/main or AET_WORK_BASE_BRANCH).",
    ),
    isolation: str = typer.Option(
        "standard",
        "--isolation",
        help="Isolation level.",
        callback=_isolation_choice,
    ),
    max_jobs: int = typer.Option(
        4,
        "--max-jobs",
        help="Max parallel tasks (batch mode).",
    ),
    task_timeout: Optional[int] = typer.Option(
        None,
        "--task-timeout",
        help="Per-task wall-clock timeout in seconds (default: adapter wall backstop).",
    ),
    heartbeat_interval: int = typer.Option(
        60,
        "--heartbeat-interval",
        help="Seconds between heartbeat log lines (default: 60).",
    ),
    run_id: Optional[str] = typer.Option(
        None,
        "--run-id",
        help="Run identifier used for telemetry and run metadata.",
    ),
    log_file: Optional[str] = typer.Option(
        None,
        "--log-file",
        help="Redirect stdout/stderr to this file (detached-run mode).",
    ),
    on_failure: str = typer.Option(
        "triage",
        "--on-failure",
        help=(
            "What to do when a task fails in batch mode: triage (default) "
            "requeues transient failures; continue marks failed and keeps "
            "spawning; halt stops the shift on the first failure."
        ),
        callback=_on_failure_choice,
    ),
) -> None:
    """AE Toolkit Unified Orchestrator."""
    if queue_file is None and plan_file is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(2)
    if queue_file is not None and plan_file is not None:
        typer.echo("error: --queue-file and --plan-file are mutually exclusive", err=True)
        raise typer.Exit(2)

    argv: list[str] = []
    if queue_file is not None:
        argv.extend(["--queue-file", queue_file])
    if plan_file is not None:
        argv.extend(["--plan-file", plan_file])
    argv.extend(["--repo-root", repo_root])
    if cli_bin is not None:
        argv.extend(["--cli-bin", cli_bin])
    if base is not None:
        argv.extend(["--base", base])
    argv.extend(["--isolation", isolation])
    argv.extend(["--max-jobs", str(max_jobs)])
    if task_timeout is not None:
        argv.extend(["--task-timeout", str(task_timeout)])
    argv.extend(["--heartbeat-interval", str(heartbeat_interval)])
    if run_id is not None:
        argv.extend(["--run-id", run_id])
    if log_file is not None:
        argv.extend(["--log-file", log_file])
    argv.extend(["--on-failure", on_failure])

    raise typer.Exit(main(argv))


if __name__ == "__main__":
    app()
