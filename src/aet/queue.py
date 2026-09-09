"""Queue JSON read/write operations."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock

from aet import plan_size
from aet.liveness import is_run_alive

# Tracks whether a queue file was read as a dict wrapper and, if so, its
# non-task metadata so write_queue can preserve the envelope.
_queue_wrappers: dict[str, dict[str, Any] | None] = {}

# Reentrant file-lock state keyed by absolute queue path. These are kept at
# module scope so nested ``queue_lock`` contexts in the same process reuse the
# same FileLock instance and therefore the same advisory lock.
_lock_instances: dict[str, FileLock] = {}
_lock_counters: dict[str, int] = {}


class QueueIntegrityError(Exception):
    """Raised when a stamped queue's content hash no longer matches its tasks.

    This indicates the queue file was modified outside ``aet-state`` (for
    example hand-edited JSON). Mutating callers must fail closed; read-only
    callers may warn and continue.
    """


class LeaseHeldError(Exception):
    """Raised when a live run lease is held by a different run."""

    def __init__(self, run_id: str | None) -> None:
        self.run_id = run_id
        super().__init__(
            f"queue is owned by run {run_id!r}; re-run after the batch "
            f"finishes or pass --force to override"
        )


def _canonical_tasks_dump(tasks: list[dict[str, Any]]) -> str:
    """Return a stable serialization of the tasks list for hashing."""
    return json.dumps(tasks, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _content_hash(tasks: list[dict[str, Any]]) -> str:
    """sha256 over the canonical tasks dump."""
    return hashlib.sha256(_canonical_tasks_dump(tasks).encode("utf-8")).hexdigest()


@contextmanager
def queue_lock(queue_file: str) -> Iterator[None]:
    """Acquire an exclusive advisory lock on a sidecar ``<queue_file>.lock``.

    The lock is blocking and reentrant within the same process. It protects
    the read-modify-write cycles in ``aet-state`` so concurrent children (for
    example the aet-work orchestrator's batch mode) cannot interleave queue
    updates and lose writes.
    """
    queue_abs = os.path.abspath(queue_file)
    lock_path = f"{queue_abs}.lock"
    lock_dir = os.path.dirname(lock_path)
    if lock_dir:
        try:
            os.makedirs(lock_dir, exist_ok=True)
        except OSError:
            # The queue directory may not be writable or even exist (e.g.
            # tests using fake paths). Fall back to a deterministic temp
            # lock file so locking still works within the same process tree.
            digest = hashlib.sha256(queue_abs.encode()).hexdigest()[:16]
            lock_path = os.path.join(tempfile.gettempdir(), f"aet-queue-lock-{digest}.lock")

    key = queue_abs

    if key not in _lock_instances:
        _lock_instances[key] = FileLock(lock_path)
        _lock_counters[key] = 0

    if _lock_counters[key] == 0:
        try:
            _lock_instances[key].acquire()
        except Exception:
            del _lock_instances[key]
            del _lock_counters[key]
            raise

    _lock_counters[key] += 1
    try:
        yield
    finally:
        _lock_counters[key] -= 1
        if _lock_counters[key] == 0:
            try:
                _lock_instances[key].release()
            finally:
                del _lock_instances[key]
                del _lock_counters[key]


# ---------------------------------------------------------------------------
# Run lease (mutation guard)
# ---------------------------------------------------------------------------

LEASE_FILENAME = "work-queue.lease"

# Distinct exit code for "the queue is owned by another run", so a caller can
# tell a refusal to write from a failure of the work itself. A refusal says
# nothing about whether the work succeeded.
LEASE_HELD_EXIT_CODE = 75


def lease_path(queue_file: str) -> str:
    """Return the lease sidecar path for a given queue file."""
    queue_abs = os.path.abspath(queue_file)
    return os.path.join(os.path.dirname(queue_abs), LEASE_FILENAME)


def read_lease(queue_file: str) -> dict[str, Any] | None:
    """Read the lease JSON, or ``None`` if it is missing or malformed."""
    path = lease_path(queue_file)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def acquire_lease(
    queue_file: str, run_id: str, force: bool = False
) -> dict[str, Any]:
    """Declare that ``run_id`` owns the queue by writing the lease sidecar.

    The lease records ``run_id``, the acquiring ``pid``, and ``started_at``.
    Acquisition is serialized under ``queue_lock`` and written atomically so a
    concurrent orchestrator cannot observe a partial lease.

    Ownership is checked before it is claimed: a live lease held by another run
    raises ``LeaseHeldError`` rather than being overwritten. Seizing a live
    lease leaves the incumbent run able to do work but unable to record any of
    it, which is worse than refusing to start. ``force`` overrides the check
    (a stale lease whose PID is dead is reclaimed either way).
    """
    path = lease_path(queue_file)
    if not force:
        check_lease(queue_file)
    lease = {
        "run_id": run_id,
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    with queue_lock(queue_file):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(path) or ".", prefix=".lease-tmp-"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(lease, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise
    return lease


def release_lease(queue_file: str, run_id: str) -> None:
    """Release the lease if it is currently held by ``run_id``.

    A lease held by a different run is left untouched so a crashing or
    misrouted run cannot delete another orchestrator's ownership marker.
    """
    path = lease_path(queue_file)
    with queue_lock(queue_file):
        current = read_lease(queue_file)
        if current is None:
            return
        if current.get("run_id") != run_id:
            return
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def check_lease(queue_file: str) -> None:
    """Refuse mutation when a live lease is held by a different run.

    Rules:
      - no lease                         -> allowed
      - lease whose owning run is not live -> stale: reclaim with a warning, allowed
      - live lease, caller's AET_RUN_ID matches ``run_id`` -> allowed
      - live lease, otherwise            -> raise ``LeaseHeldError``
    """
    lease = read_lease(queue_file)
    if lease is None:
        return

    run_id = lease.get("run_id")
    pid = lease.get("pid")
    started_at = lease.get("started_at")

    queue_dir = os.path.dirname(os.path.abspath(queue_file))
    run_dir = os.path.join(queue_dir, "runs", str(run_id)) if run_id else None

    if not is_run_alive(run_dir=run_dir, pid=pid, started=started_at):
        print(
            f"⚠️  Reclaiming stale run lease left by run {run_id!r} "
            f"(pid {pid} is no longer alive).",
            file=sys.stderr,
        )
        try:
            os.unlink(lease_path(queue_file))
        except FileNotFoundError:
            pass
        return

    caller = os.environ.get("AET_RUN_ID")
    if caller is not None and caller == run_id:
        return

    raise LeaseHeldError(run_id)


def lease_guard(queue_file: str, force: bool = False) -> bool:
    """Check the run lease for a mutating entry point.

    Returns ``True`` when the mutation may proceed. When a live lease is held
    by a different run, a refusal is printed (``force`` false) or an override
    warning is printed (``force`` true) and the matching boolean is returned.
    """
    try:
        check_lease(queue_file)
    except LeaseHeldError as exc:
        if force:
            print(
                f"⚠️  --force overriding run lease held by run {exc.run_id}; "
                f"mutating the queue during a live batch can corrupt it.",
                file=sys.stderr,
            )
            return True
        print(
            f"⛔ Refusing to mutate the queue: owned by run {exc.run_id}. "
            f"Re-run after the batch finishes, or pass --force to override.",
            file=sys.stderr,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Forward-only deterministic state model (ADR-011)
# ---------------------------------------------------------------------------

STATES = {
    "planned",
    "ready",
    "blocked",
    "in_progress",
    "awaiting_merge",
    "merged",
    "abandoned",
    "failed",
    "quarantined",
}

TERMINAL_STATES = {"merged", "abandoned"}

# Legal transitions for the recorded-forward lifecycle.  ``None`` is the
# pre-intake state used only during initial sync.  ``abandoned`` is a terminal
# human-initiated transition allowed from every non-terminal state.
LEGAL_TRANSITIONS: dict[str | None, set[str]] = {
    None: {"planned"},
    # ``run-one`` may start a queued task directly from ``planned`` when the
    # user explicitly selects a plan, bypassing the normal ``ready`` step.
    "planned": {"blocked", "ready", "in_progress", "abandoned"},
    "blocked": {"ready", "abandoned"},
    "ready": {"in_progress", "failed", "abandoned"},
    "in_progress": {"in_progress", "awaiting_merge", "failed", "quarantined", "abandoned"},
    "awaiting_merge": {"merged", "abandoned"},
    "merged": set(),
    "abandoned": set(),
    "failed": {"in_progress", "ready", "blocked", "quarantined", "abandoned"},
    "quarantined": {"ready", "abandoned"},
}

# Legacy status -> canonical state mapping used only on read. New code and
# new queue files must use ``state`` exclusively.
_LEGACY_STATUS_TO_STATE: dict[str | None, str] = {
    None: "planned",
    "planned": "planned",
    "unblocked": "ready",
    "in-progress": "in_progress",
    "blocked": "blocked",
    "done": "awaiting_merge",
    "awaiting_merge": "awaiting_merge",
    "merge_verified": "merged",
    "merged": "merged",
    "abandoned": "abandoned",
    "failed": "failed",
}


def _normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    """Normalize a legacy task record to the canonical ``state`` vocabulary.

    If the task only carries a legacy ``status`` key, derive ``state`` from
    the private literal mapping and remove ``status``. Modern records that
    already have ``state`` are returned with ``status`` stripped.

    The returned dict is the same object, mutated in place.
    """
    state = task.get("state")
    status = task.pop("status", None)
    if state is None and status is not None:
        task["state"] = _LEGACY_STATUS_TO_STATE.get(status, status)
    return task


def current_state(task: dict[str, Any]) -> str | None:
    """Return the task's recorded canonical state.

    Returns ``None`` only when ``state`` is not set (pre-intake).
    """
    return task.get("state")


def append_history(
    task: dict[str, Any],
    frm: str | None,
    to: str,
    by: str,
    evidence: dict[str, Any] | None = None,
) -> None:
    """Append a transition entry to the task's append-only history."""
    entry: dict[str, Any] = {
        "from": frm,
        "to": to,
        "at": datetime.now(timezone.utc).isoformat(),
        "by": by,
    }
    if evidence:
        entry["evidence"] = evidence
    task.setdefault("history", []).append(entry)


def pending_blockers(task: dict[str, Any]) -> int:
    """Return the number of blockers still pending for this task.

    If the counter has not been initialized, derive it from ``blocked_by``.
    """
    pb = task.get("pending_blockers")
    if pb is not None:
        return pb
    return len(task.get("blocked_by", []))


def build_blocks(queue: list[dict[str, Any]]) -> None:
    """Recompute ``blocks`` as the inverse of ``blocked_by`` for the whole queue."""
    task_by_id = {t["id"]: t for t in queue if t.get("id")}
    for task in queue:
        task["blocks"] = []
    for task in queue:
        for blocker in task.get("blocked_by", []):
            if blocker in task_by_id:
                task_by_id[blocker].setdefault("blocks", []).append(task["id"])


def read_queue(queue_file: str, verify: bool = True) -> list[dict[str, Any]]:
    """Read the queue from JSON and normalize legacy records.

    Supports both flat list and dict-wrapper formats (e.g.
    {"source_prd": "...", "tasks": [...], "queue_updated_at": "..."}).
    Wrapper metadata is stored so write_queue can restore it.

    When the wrapper carries a ``content_hash`` stamp (written by
    ``write_queue``) and ``verify`` is true, the tasks are re-hashed and
    compared against the stamp; a mismatch raises ``QueueIntegrityError`` so
    mutating callers fail closed on state the system did not write. Read-only
    callers may pass ``verify=False`` to warn and continue instead.

    Legacy ``status``-only records are upgraded in memory to the canonical
    ``state`` vocabulary; the ``status`` key is dropped.
    """
    _queue_wrappers.pop(queue_file, None)
    if not os.path.exists(queue_file):
        return []
    with open(queue_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        if verify and "content_hash" in data:
            stored_hash = data.get("content_hash")
            tasks_for_hash = data.get("tasks", [])
            if _content_hash(tasks_for_hash) != stored_hash:
                raise QueueIntegrityError(
                    "queue modified outside aet state — run `aet state audit` "
                    "to inspect, `aet state heal --apply` to repair"
                )
        _queue_wrappers[queue_file] = {k: v for k, v in data.items() if k != "tasks"}
        tasks = data.get("tasks", [])
    else:
        _queue_wrappers[queue_file] = None
        tasks = data
    return [_normalize_task(task) for task in tasks]


def write_queue(
    queue_file: str, queue: list[dict[str, Any]], wrapper: dict[str, Any] | None = None
) -> None:
    """Write the queue back to JSON, preserving any wrapper metadata.

    If ``wrapper`` is supplied, its keys are merged into the stored wrapper
    (e.g. to update ``source_prd`` or ``queue_updated_at``).

    The legacy ``status`` key is never written. Any task that still carries
    one has it stripped before serialization.

    The write is atomic: data is serialized to a temporary file in the same
    directory and then renamed into place. This prevents concurrent readers
    from seeing a partially-written or truncated file.

    Wrapper writes (queues that carry metadata) are stamped with a monotonic
    ``revision`` and a ``content_hash`` over the canonical tasks dump so
    readers can detect edits made outside ``aet-state``. Flat-list queues are
    left unstamped for backward compatibility.
    """
    queue_dir = os.path.dirname(queue_file)
    os.makedirs(queue_dir, exist_ok=True)
    stored = _queue_wrappers.pop(queue_file, None)
    was_dict_wrapper = stored is not None
    merged = {**stored} if stored else {}
    if wrapper:
        merged.update(wrapper)

    cleaned = []
    for task in queue:
        copy = dict(task)
        copy.pop("status", None)
        cleaned.append(copy)

    if merged or was_dict_wrapper:
        # Tamper-evident envelope: a monotonic revision plus a content hash
        # over the canonical tasks dump. Readers fail closed when a stamped
        # queue no longer matches its tasks (see read_queue).
        prev_revision = merged.get("revision")
        if not isinstance(prev_revision, int):
            prev_revision = 0
        merged["revision"] = prev_revision + 1
        merged["content_hash"] = _content_hash(cleaned)
        data = {**merged, "tasks": cleaned}
    else:
        data = cleaned

    fd, tmp_path = tempfile.mkstemp(dir=queue_dir, prefix=".queue-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, queue_file)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def get_next_unblocked(queue: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the first stored-ready task."""
    for task in queue:
        if current_state(task) == "ready":
            return task
    return None


def has_pending_tasks(queue: list[dict[str, Any]]) -> bool:
    """Check if any tasks are not in a terminal state."""
    terminal = {"merged", "abandoned"}
    for task in queue:
        state = current_state(task)
        if state is not None and state not in terminal:
            return True
    return False


def resolve_base_commit(repo_root: str, branch: str | None) -> str | None:
    """Return the commit ``branch`` was created at, or None when unresolvable.

    ADR-064 decision 1: a branch's origin is recorded when the branch is
    created, not reconstructed later. Ancestry cannot tell an undiverged
    branch from a merged one after the fact, so this value is what makes the
    two distinguishable.
    """
    if not branch:
        return None
    result = subprocess.run(
        ["git", "-C", repo_root, "rev-parse", branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def record_task_meta(
    queue: list[dict[str, Any]],
    task_id: str,
    worktree: str | None,
    branch: str | None,
    base_commit: str | None = None,
    integration_branch: str | None = None,
) -> None:
    """Record worktree, branch, and branch-origin metadata for a task.

    ``base_commit`` is the commit the branch was created at (ADR-064). It is
    written once, at branch creation; a task whose record lacks it can never
    derive ``merged`` from branch ancestry, so every branch-creation path must
    supply it.

    ``integration_branch`` is the target branch the task was created to integrate
    into (ADR-075 / ned-02). Written once at branch creation in single-pr mode.
    """
    for task in queue:
        if task.get("id") == task_id:
            task["worktree"] = worktree
            task["branch"] = branch
            # Written once, at branch creation. A task re-recorded after it has
            # committed would otherwise stamp its current tip as its origin,
            # erasing the very divergence the field exists to prove.
            if base_commit and not task.get("base_commit"):
                task["base_commit"] = base_commit
            if integration_branch and not task.get("integration_branch"):
                task["integration_branch"] = integration_branch



# ---------------------------------------------------------------------------
# Settled history helpers (append-only JSONL)
# ---------------------------------------------------------------------------

HISTORY_TERMINAL_STATES = {"merged", "abandoned"}


def read_history(history_file: str) -> list[dict[str, Any]]:
    """Read all settled task records from the append-only JSONL history log."""
    if not os.path.exists(history_file):
        return []
    tasks: list[dict[str, Any]] = []
    with open(history_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tasks.append(json.loads(line))
    return tasks


def append_history_record(history_file: str, task: dict[str, Any]) -> None:
    """Append a settled task record to the append-only JSONL history log.

    The record is extended with ``delivered_size``: a first-parent diff-stat
    anchored on the task's ``merge_commit``, paired with the plan's declared
    ``size`` label. Measurement failures are recorded with a reason and never
    raise, so telemetry collection cannot block a task from settling.
    """
    os.makedirs(os.path.dirname(history_file), exist_ok=True)
    record = {**task, "settled_at": datetime.now(timezone.utc).isoformat()}

    from aet import divergence, plan_parser  # local import avoids a cycle with plan_parser

    repo_root = Path(history_file).parent.parent
    # After R-19 the rendered spec travels with the task record, so the declared
    # size is read from the record itself. Pre-R-19 records fall back to the
    # plan file on disk.
    routing_data = plan_parser.task_routing_data(task, repo_root=repo_root)
    declared_size: str | None = routing_data.get("size")

    size_info = plan_size.delivered_size(repo_root, task.get("merge_commit"))
    record["delivered_size"] = {**size_info, "declared_size": declared_size}

    div_info = divergence.compute_divergence(
        repo_root, task.get("merge_commit"), spec=task.get("spec"), task=task
    )
    record["divergence"] = div_info

    with open(history_file, "a", encoding="utf-8") as f:
        json.dump(record, f)
        f.write("\n")


def seal_terminal(queue_file: str, history_file: str, task_id: str) -> dict[str, Any]:
    """Move a terminal task from the live queue to the settled history log.

    Reads the live queue, removes the task identified by ``task_id``, appends
    the full task record (including its transition history) to
    ``history_file`` as one JSONL line, and writes the reduced live queue back.

    Raises ``ValueError`` if the task is not present in the live queue.

    This helper does **not** promote dependents; the caller must already have
    updated the forward frontier before sealing.

    The seal is performed under ``queue_lock`` so concurrent callers cannot
    race on the queue file.
    """
    with queue_lock(queue_file):
        queue = read_queue(queue_file)
        task = next((t for t in queue if t.get("id") == task_id), None)
        if task is None:
            raise ValueError(f"Task {task_id} not found in live queue {queue_file}")

        live = [t for t in queue if t.get("id") != task_id]
        append_history_record(history_file, task)
        write_queue(queue_file, live)
    return task
