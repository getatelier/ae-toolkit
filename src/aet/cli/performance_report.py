"""aet performance-report — Cost, tokens and time per PRD for one project.

Run inside a project. The command resolves the repository, finds that
project's telemetry in the archive, groups its plans by the PRD that owns each
slice prefix, and prints a markdown report. ``--json`` writes the same data
set in full, including one row per stage session.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

_SCRIPT_DIR = Path(__file__).resolve().parent
from aet import perf_report, telemetry  # noqa: E402
from aet.project_id import derive_project_slug, resolve_repo_root  # noqa: E402

app = typer.Typer(invoke_without_command=True)


@app.callback()
def performance_report(
    project: str | None = typer.Option(
        None,
        "--project",
        help="Archive project directory (defaults to the current repository)",
    ),
    worktree: str | None = typer.Option(
        None,
        "--worktree",
        help="Limit to one worktree label (default: every worktree of the project)",
    ),
    prds: Path | None = typer.Option(
        None,
        "--prds",
        help="PRD directory (default: docs/prds under the repository root)",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Only include stages starting at or after this ISO-8601 timestamp",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Write markdown here instead of stdout",
    ),
    json_out: Path | None = typer.Option(
        None,
        "--json",
        help="Write the full JSON payload here",
    ),
) -> None:
    """Report cost, tokens and stage time per PRD."""
    repo_root = resolve_repo_root()
    if project is None:
        project = perf_report.project_dir_name(derive_project_slug(repo_root))
    prd_dir = prds if prds is not None else repo_root / perf_report.DEFAULT_PRD_DIR
    archive = telemetry.archive_dir()

    try:
        stages = perf_report.read_stages(archive, project, worktree, since)
    except perf_report.NoTelemetryError as exc:
        typer.echo(f"aet performance-report: {exc}", err=True)
        raise typer.Exit(1) from exc

    payload = perf_report.build_payload(
        stages, project, archive, prd_dir, worktree=worktree, since=since
    )

    if json_out is not None:
        json_out.write_text(json.dumps(payload, indent=2) + "\n")
        typer.echo(f"wrote {json_out}", err=True)

    markdown = perf_report.render_markdown(payload)
    if out is not None:
        out.write_text(markdown)
        typer.echo(f"wrote {out}", err=True)
    elif json_out is None:
        typer.echo(markdown, nl=False)

    raise typer.Exit(0)


def main(argv: list[str] | None = None) -> int:
    try:
        return app(argv or [], standalone_mode=False)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0


if __name__ == "__main__":
    app()
