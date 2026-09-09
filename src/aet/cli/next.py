"""aet-work next — Pick the next stored-ready task.

Reads stored state and transitions the first topological ready task to
in_progress. Queue membership is the explicit sprint-add record; the queue
itself is the authority.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer

_SCRIPT_DIR = Path(__file__).resolve().parent
from aet.backends.factory import (  # noqa: E402
    create_backend,
    resolve_config,
    resolve_integration_mode,
)
from aet.branch_ref import (  # noqa: E402
    resolve_integration_branch_for_task,
)
from aet.queue import (  # noqa: E402
    QueueIntegrityError,
    current_state,
    record_task_meta,
    resolve_base_commit,
)


def derive_queue(queue: list[dict]) -> list[dict]:
    """Return only tasks that are executable on this machine.

    Queue membership is the explicit sprint-add record. A task whose plan file
    has disappeared but whose record carries a portable spec (R-19) is still
    pickable because the spec renders the working file on demand.
    """
    derived: list[dict] = []
    for task in queue:
        if isinstance(task.get("spec"), dict):
            derived.append(task)
            continue
        pf = task.get("plan_file")
        if pf and Path(pf).is_file():
            derived.append(task)
    return derived


def topological_sort(tasks: list[dict]) -> list[dict]:
    """Return tasks sorted so blockers appear before their dependents."""
    by_id = {t.get("id"): t for t in tasks if t.get("id")}
    visited: set[str] = set()
    ordered: list[dict] = []

    def visit(task_id: str) -> None:
        if task_id in visited or task_id not in by_id:
            return
        visited.add(task_id)
        for blocker in by_id[task_id].get("blocked_by", []):
            visit(blocker)
        ordered.append(by_id[task_id])

    for task in tasks:
        visit(task.get("id", ""))

    return ordered


def pick_next_ready(queue: list[dict]) -> dict | None:
    """Return the first stored-ready task in topological order."""
    ordered = topological_sort(queue)
    for task in ordered:
        if current_state(task) == "ready":
            return task
    return None


def transition_task(backend, task: dict) -> bool:
    """Transition a task to in_progress and record branch/worktree metadata."""
    task_id = task.get("id", "")
    from_state = current_state(task) or "ready"
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT_DIR / "aet_state.py"),
            "transition",
            task_id,
            from_state,
            "in_progress",
            backend.queue_file,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return False

    data = backend.load()
    queue = data["queue"]
    branch = task_id
    worktree = f".worktrees/{task_id}"
    repo_root = getattr(backend, "repo_root", None) or "."
    config_path = os.path.join(repo_root, ".agents", "aet-config.json")
    config = resolve_config(config_path, repo_root=repo_root)
    try:
        integration_mode = resolve_integration_mode(config_path, repo_root=repo_root)
    except Exception:
        integration_mode = "pr-per-task"
    task_integration_branch = None
    if integration_mode == "single-pr":
        task_ref = resolve_integration_branch_for_task(
            repo_root, config, task, integration_mode, backend=backend
        )
        task_integration_branch = task_ref.ref

    record_task_meta(
        queue,
        task_id,
        worktree,
        branch,
        base_commit=resolve_base_commit(".", branch),
        integration_branch=task_integration_branch,
    )
    backend.save(queue)
    return True



def _run(
    queue_file: str,
    history_file: str,
    plans_dir: Path,
) -> int:
    config_path = str(Path(queue_file).with_name("aet-config.json"))
    backend = create_backend(
        config_path=config_path,
        queue_file=queue_file,
        history_file=history_file,
    )
    backend.fetch()
    try:
        data = backend.load()
    except QueueIntegrityError as exc:
        # Mutating command: fail closed with a one-line refusal, not a
        # traceback. The error message names the recovery path (ADR-024).
        print(f"⛔ {exc}", file=sys.stderr)
        return 1
    queue = data["queue"]

    derived_queue = derive_queue(queue)
    task = pick_next_ready(derived_queue)

    if not task:
        print("No ready tasks available.")
        return 0

    task_id = task.get("id", "")
    print(f"Next task: {task_id}")
    print(f"  Title: {task.get('title', '')}")
    print(f"  Plan: {task.get('plan_file', '')}")

    if not transition_task(backend, task):
        return 1

    print(f"Transitioned {task_id} to in-progress.")
    return 0


app = typer.Typer(invoke_without_command=True)


@app.callback()
def next_cmd(
    queue_file: str = typer.Option(
        ".agents/aet-queue",
        "--queue-file",
        help="Path to queue anchor",
    ),
    history_file: str = typer.Option(
        ".agents/work-history.jsonl",
        "--history-file",
        help="Path to work-history.jsonl",
    ),
    plans_dir: Path = typer.Option(
        Path("docs/plans"),
        "--plans-dir",
        help="Directory containing atomic plan markdown files",
    ),
) -> None:
    """Pick the next ready task."""
    rc = _run(queue_file, history_file, plans_dir)
    raise typer.Exit(rc)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        return app(argv, standalone_mode=False)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0


if __name__ == "__main__":
    app()
