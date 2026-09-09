"""aet-work status — Show the current state of the work queue.

Reads the stored state and reports counts, next tasks, failed tasks, and
worktree health.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from aet import (
    breaker,  # noqa: E402
    telemetry,  # noqa: E402
)
from aet.backends.factory import create_backend  # noqa: E402
from aet.liveness import is_run_alive  # noqa: E402
from aet.plan_parser import parse_frontmatter  # noqa: E402
from aet.project_id import derive_project_slug  # noqa: E402
from aet.queue import (  # noqa: E402
    QueueIntegrityError,
    current_state,
    pending_blockers,
)


def _display_category(task: dict) -> str:
    """Return the canonical state for summary counting."""
    return current_state(task) or "unknown"


def _declared_size(task: dict) -> str:
    """Return the plan's declared S/M/L size, or '—' when unavailable."""
    spec = task.get("spec")
    if isinstance(spec, dict):
        data = spec.get("frontmatter", {})
    else:
        plan_file = task.get("plan_file")
        if not plan_file:
            return "—"
        try:
            data = parse_frontmatter(Path(plan_file))
        except OSError:
            return "—"
    size = data.get("size")
    return size if size in {"S", "M", "L"} else "—"


def _render_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Render a markdown table with columns padded for terminal readability."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells: list[str]) -> str:
        padded = (cell.ljust(width) for cell, width in zip(cells, widths))
        return "| " + " | ".join(padded) + " |"

    separator = "| " + " | ".join("-" * w for w in widths) + " |"
    return [fmt(headers), separator, *(fmt(row) for row in rows)]


def _active_runs(runs_dir: Path) -> list[dict]:
    """List detached runs under ``runs_dir`` whose process is still alive."""
    runs: list[dict] = []
    if not runs_dir.is_dir():
        return runs
    for entry in sorted(runs_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not is_run_alive(entry):
            continue
        pid_file = entry / "pid"
        started_file = entry / "started"
        if not pid_file.is_file():
            continue
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            continue
        started = ""
        if started_file.is_file():
            try:
                started = started_file.read_text(encoding="utf-8").strip()
            except OSError:
                started = ""
        runs.append({"id": entry.name, "pid": pid, "started": started})
    return runs


def _queue_updated_at(backend) -> str | None:
    """Return the wrapper's queue_updated_at from the backend envelope, else None."""
    envelope = getattr(backend, "_envelope", {})
    if isinstance(envelope, dict):
        return envelope.get("queue_updated_at")
    return None


def _circuit_breaker_status(repo_root: Path) -> dict:
    """Inspect refs/aet/breaker and return structured circuit breaker status."""
    breaker_store = breaker.BreakerStore(repo_root)
    tally = breaker_store.load()
    tripped_sig = breaker.systemic_tripped(tally)
    if tripped_sig is not None:
        affected = sorted(tally.get(tripped_sig, set()))
        return {
            "tripped": True,
            "signature": tripped_sig,
            "affected_tasks": affected,
            "count": len(affected),
            "affected_task_count": len(affected),
            "remedy": "aet breaker reset",
        }
    return {
        "tripped": False,
        "signature": None,
        "affected_tasks": [],
        "count": 0,
        "affected_task_count": 0,
        "remedy": None,
    }


def _latest_run_summary(repo_root: Path) -> dict | None:
    """Find and return the latest run telemetry summary for repo_root, if any."""
    archive_root = telemetry.archive_dir()
    slug = derive_project_slug(repo_root)
    project_dir = archive_root / slug
    if not project_dir.is_dir():
        return None

    candidates: list[tuple[str, Path, dict]] = []
    for run_dir, date_segment, run_id in telemetry._iter_project_run_dirs(project_dir):
        summary_path = run_dir / "last-run.json"
        summary = None
        if summary_path.is_file():
            summary = telemetry.read_run_summary(summary_path)
        if summary is None:
            records = []
            for jsonl_path in run_dir.glob("*.jsonl"):
                records.extend(telemetry.read_jsonl(jsonl_path))
            summaries = [r for r in records if r.get("type") == "run_summary"]
            if summaries:
                summary = summaries[-1]

        if summary is not None:
            timestamp = (
                summary.get("end_time")
                or summary.get("start_time")
                or f"{date_segment}T00:00:00Z"
            )
            candidates.append((timestamp, run_dir, summary))

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: (x[0], x[1].stat().st_mtime if x[1].exists() else 0),
        reverse=True,
    )
    _, run_dir, summary = candidates[0]

    run_id = summary.get("run_id", run_dir.name)
    outcome = summary.get("outcome", "unknown")
    exit_code = summary.get("exit_code")
    tasks_failed = summary.get("tasks_failed", 0)
    tasks_succeeded = summary.get("tasks_succeeded", 0)
    start_time = summary.get("start_time")
    end_time = summary.get("end_time")

    error_summary = None
    if (
        outcome == "failure"
        or (exit_code is not None and exit_code != 0)
        or tasks_failed > 0
    ):
        stage_records = []
        for jsonl_path in sorted(run_dir.glob("*.jsonl")):
            for rec in telemetry.read_jsonl(jsonl_path):
                if rec.get("type") in ("stage", "triage") and (
                    rec.get("result") == "failure"
                    or rec.get("outcome") in ("failure", "quarantined")
                ):
                    stage_records.append(rec)

        reasons = []
        for rec in stage_records:
            if rec.get("output_excerpt"):
                reasons.append(rec["output_excerpt"].strip())
            elif rec.get("failure_class"):
                stage_name = rec.get("stage") or "stage"
                reasons.append(
                    f"Stage '{stage_name}' failed with {rec['failure_class']}"
                )
            elif rec.get("reason"):
                reasons.append(rec["reason"])

        if reasons:
            error_summary = "; ".join(reasons)
        else:
            code_str = f" with exit code {exit_code}" if exit_code is not None else ""
            fail_count_str = f" ({tasks_failed} failed task(s))" if tasks_failed else ""
            error_summary = f"Run terminated{code_str}{fail_count_str}"

    return {
        "run_id": run_id,
        "outcome": outcome,
        "exit_code": exit_code,
        "summary": error_summary,
        "start_time": start_time,
        "end_time": end_time,
        "tasks_failed": tasks_failed,
        "tasks_succeeded": tasks_succeeded,
    }


def _json_projection(
    queue: list[dict],
    backend,
    runs_dir: Path,
    breaker_info: dict | None = None,
    last_run_info: dict | None = None,
) -> dict:
    """Build the machine-readable status projection (minimal v1 schema)."""
    counts: dict[str, int] = {}
    for task in queue:
        category = _display_category(task)
        counts[category] = counts.get(category, 0) + 1
    return {
        "queue_updated_at": _queue_updated_at(backend),
        "active_runs": _active_runs(runs_dir),
        "circuit_breaker": breaker_info
        if breaker_info is not None
        else {
            "tripped": False,
            "signature": None,
            "affected_tasks": [],
            "count": 0,
            "affected_task_count": 0,
            "remedy": None,
        },
        "last_run": last_run_info,
        "summary": counts,
        "tasks": [
            {
                "id": task.get("id"),
                "state": current_state(task),
                "size": _declared_size(task),
                "stage": task.get("stage"),
                "blocked_by": task.get("blocked_by", []),
                "blocks": task.get("blocks", []),
                "pending_blockers": pending_blockers(task),
                "plan_file": task.get("plan_file"),
            }
            for task in queue
        ],
    }


def _run(
    queue_file: str,
    history_file: str,
    plans_dir: Path,
    json_output: bool,
) -> int:
    config_path = str(Path(queue_file).with_name("aet-config.json"))
    backend = create_backend(
        config_path=config_path, queue_file=queue_file, history_file=history_file
    )
    backend.fetch()
    try:
        data = backend.load()
        queue = data["queue"]
    except QueueIntegrityError as exc:
        print(
            f"⚠️  {exc}; read-only status continues with unverified data.",
            file=sys.stderr,
        )
        # Recover through the backend abstraction, not the JSON reader: the
        # git-refs backend keeps no aet-queue, so read_queue would
        # return an empty list and hide the very tasks status must surface.
        queue = backend.load(verify=False)["queue"]
    runs_dir = Path.cwd() / ".agents" / "runs"
    repo_root = Path(queue_file).resolve().parent.parent
    breaker_info = _circuit_breaker_status(repo_root)
    last_run_info = _latest_run_summary(repo_root)

    if json_output:
        print(
            json.dumps(
                _json_projection(
                    queue, backend, runs_dir, breaker_info, last_run_info
                ),
                indent=2,
            )
        )
        return 0

    if breaker_info["tripped"]:
        sig = breaker_info["signature"]
        count = breaker_info["affected_task_count"]
        tasks_list = breaker_info["affected_tasks"]
        tasks_detail = f" ({', '.join(tasks_list)})" if tasks_list else ""
        print("\n⚠️  CIRCUIT BREAKER TRIPPED")
        print(
            f"  Systemic circuit breaker is active for signature '{sig}' ({count} tasks affected{tasks_detail})."
        )
        print("  Remedy: Inspect errors and run `aet breaker reset` to clear.\n")

    counts = {
        "planned": 0,
        "ready": 0,
        "blocked": 0,
        "in_progress": 0,
        "awaiting_merge": 0,
        "failed": 0,
    }
    for task in queue:
        category = _display_category(task)
        if category in counts:
            counts[category] += 1

    non_zero = {state: count for state, count in counts.items() if count}
    if non_zero:
        print("\nQueue summary:")
        for state, count in non_zero.items():
            print(f"  {state}: {count}")
    else:
        print("\nQueue is empty.")

    active_runs = _active_runs(runs_dir)
    if active_runs:
        print("\nActive detached runs:")
        for run in active_runs:
            started = f" (started {run['started']})" if run["started"] else ""
            print(f"  - {run['id']} (PID {run['pid']}){started}")
    else:
        print("\nNo active detached runs.")
        if last_run_info and (
            last_run_info.get("outcome") == "failure"
            or (
                last_run_info.get("exit_code") is not None
                and last_run_info.get("exit_code") != 0
            )
            or last_run_info.get("tasks_failed", 0) > 0
        ):
            print("\nPrevious run failed:")
            print(f"  - Run ID: {last_run_info['run_id']}")
            if last_run_info.get("exit_code") is not None:
                print(f"  - Exit code: {last_run_info['exit_code']}")
            if last_run_info.get("outcome"):
                print(f"  - Outcome: {last_run_info['outcome']}")
            if last_run_info.get("summary"):
                print(f"  - Summary: {last_run_info['summary']}")

    terminal = {"merged", "abandoned"}
    active_ids = {t.get("id") for t in queue}
    rows = []
    for task in queue:
        if current_state(task) in terminal:
            continue
        deps = [
            "-".join(b.split("-")[:2])
            for b in task.get("blocked_by", [])
            if b in active_ids
        ]
        rows.append(
            [
                task.get("id", ""),
                current_state(task) or "unknown",
                _declared_size(task),
                ", ".join(deps) or "—",
            ]
        )
    if rows:
        print()
        for line in _render_table(["ID", "State", "Size", "Depends on"], rows):
            print(line)
    else:
        print("\nNo active tasks.")

    ready = [t for t in queue if current_state(t) == "ready"]
    if ready:
        print("\nNext ready tasks:")
        for task in ready[:3]:
            print(f"  - {task.get('id')} — {task.get('title')} → {task.get('plan_file')}")
    else:
        print("\nNo ready tasks.")

    failed = [t for t in queue if current_state(t) == "failed"]
    if failed:
        print("\nFailed tasks:")
        for task in failed:
            print(f"  - {task.get('id')} — {task.get('title')}")
    else:
        print("\nNo failed tasks.")

    # Worktree paths are recorded relative to the repo root, so they must be
    # resolved against it and not against the current directory — otherwise
    # `aet status` run from inside a worktree reports every worktree as stale.
    stale_worktrees = []
    for task in queue:
        worktree = task.get("worktree")
        if worktree and not (repo_root / worktree).is_dir():
            stale_worktrees.append((task.get("id"), worktree))
    if stale_worktrees:
        print("\nWorktree validation:")
        for task_id, worktree in stale_worktrees:
            print(
                f"  ⚠️ Stale worktree: {task_id} → {worktree} does not exist."
            )
    else:
        print("\nAll registered worktrees are present.")

    return 0


app = typer.Typer(invoke_without_command=True)


@app.callback()
def status(
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
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print a machine-readable JSON projection instead of the human report",
    ),
) -> None:
    """Show work queue status."""
    rc = _run(queue_file, history_file, plans_dir, json_output)
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
