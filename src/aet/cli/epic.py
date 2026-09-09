"""aet epic — Active epic declaration and inspection commands.

``aet epic set <branch>`` declares an active epic in the queue envelope.
``aet epic show`` displays the active epic declaration.
``aet epic clear`` clears the active epic declaration.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import typer

from aet.backends.factory import create_backend
from aet.project_id import resolve_repo_root

app = typer.Typer(help="Active epic declaration and inspection.")


def _branch_resolves(repo_root: Path, branch: str) -> bool:
    """Check if branch exists locally or on origin."""
    local_ref = f"refs/heads/{branch}"
    remote_ref = f"refs/remotes/origin/{branch}"
    for ref in (local_ref, remote_ref):
        res = subprocess.run(
            ["git", "-C", str(repo_root), "show-ref", "--quiet", "--verify", ref],
            capture_output=True,
        )
        if res.returncode == 0:
            return True
    return False


@app.command("set")
def set_epic_cmd(
    branch: str = typer.Argument(..., help="Integration branch for the epic."),
    title: Optional[str] = typer.Option(None, "--title", help="Human-readable epic title."),
    body_file: Optional[str] = typer.Option(
        None, "--body-file", help="Path to markdown body file describing the epic."
    ),
    create: bool = typer.Option(
        False, "--create", help="Declare the epic before creating its branch."
    ),
    config: str = typer.Option(
        ".agents/aet-config.json", "--config", help="Path to AET configuration file."
    ),
    queue_file: str = typer.Option(
        ".agents/aet-queue", "--queue-file", help="Path to queue anchor."
    ),
    history_file: str = typer.Option(
        ".agents/work-history.jsonl", "--history-file", help="Path to work history."
    ),
) -> None:
    """Declare the active epic in the queue envelope."""
    repo_root = resolve_repo_root()

    if not _branch_resolves(repo_root, branch) and not create:
        typer.echo(
            f"⛔ Branch '{branch}' does not exist locally or on origin. Pass --create to declare it before creating.",
            err=True,
        )
        raise typer.Exit(1)

    if body_file:
        bf_path = Path(body_file)
        if not bf_path.is_absolute():
            bf_path = repo_root / bf_path
        if not bf_path.is_file():
            typer.echo(f"⛔ Body file not found: {body_file}", err=True)
            raise typer.Exit(1)

    queue_path = str(repo_root / queue_file) if not Path(queue_file).is_absolute() else queue_file
    history_path = str(repo_root / history_file) if not Path(history_file).is_absolute() else history_file
    config_full = str(repo_root / config) if not Path(config).is_absolute() else config

    backend = create_backend(
        config_path=config_full,
        queue_file=queue_path,
        history_file=history_path,
    )
    try:
        backend.set_epic(branch=branch, title=title, body_file=body_file)
    except Exception as exc:
        backend.close()
        typer.echo(f"⛔ {exc}", err=True)
        raise typer.Exit(1) from exc
    backend.close()
    typer.echo(f"✓ Active epic set to branch '{branch}'.")


@app.command("show")
def show(
    config: str = typer.Option(
        ".agents/aet-config.json", "--config", help="Path to AET configuration file."
    ),
    queue_file: str = typer.Option(
        ".agents/aet-queue", "--queue-file", help="Path to queue anchor."
    ),
    history_file: str = typer.Option(
        ".agents/work-history.jsonl", "--history-file", help="Path to work history."
    ),
) -> None:
    """Show the active epic declaration."""
    repo_root = resolve_repo_root()
    queue_path = str(repo_root / queue_file) if not Path(queue_file).is_absolute() else queue_file
    history_path = str(repo_root / history_file) if not Path(history_file).is_absolute() else history_file
    config_full = str(repo_root / config) if not Path(config).is_absolute() else config

    backend = create_backend(
        config_path=config_full,
        queue_file=queue_path,
        history_file=history_path,
    )
    try:
        epic = backend.read_epic()
    finally:
        backend.close()

    if not epic or not epic.get("branch"):
        typer.echo("No active epic.")
        return

    typer.echo("Active epic:")
    typer.echo(f"  branch: {epic.get('branch')}")
    if epic.get("title"):
        typer.echo(f"  title: {epic.get('title')}")
    if epic.get("body_file"):
        typer.echo(f"  body_file: {epic.get('body_file')}")
    if epic.get("set_at"):
        typer.echo(f"  set_at: {epic.get('set_at')}")


@app.command("clear")
def clear(
    config: str = typer.Option(
        ".agents/aet-config.json", "--config", help="Path to AET configuration file."
    ),
    queue_file: str = typer.Option(
        ".agents/aet-queue", "--queue-file", help="Path to queue anchor."
    ),
    history_file: str = typer.Option(
        ".agents/work-history.jsonl", "--history-file", help="Path to work history."
    ),
) -> None:
    """Clear the active epic declaration."""
    repo_root = resolve_repo_root()
    queue_path = str(repo_root / queue_file) if not Path(queue_file).is_absolute() else queue_file
    history_path = str(repo_root / history_file) if not Path(history_file).is_absolute() else history_file
    config_full = str(repo_root / config) if not Path(config).is_absolute() else config

    backend = create_backend(
        config_path=config_full,
        queue_file=queue_path,
        history_file=history_path,
    )
    try:
        backend.clear_epic()
    finally:
        backend.close()
    typer.echo("✓ Cleared active epic declaration.")
