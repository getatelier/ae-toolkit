"""``aet breaker`` — Circuit breaker inspection and reset commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from aet import breaker
from aet.project_id import resolve_repo_root

app = typer.Typer(help="Circuit breaker inspection and reset.")


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


@app.command("show")
def show(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON representation.",
    ),
    repo_root: Optional[Path] = typer.Option(
        None,
        "--repo-root",
        help="Repository root (defaults to git root or current working directory).",
    ),
) -> None:
    """Show circuit breaker tracked failure signatures and trip status."""
    resolved_root = repo_root or resolve_repo_root(Path.cwd()) or Path.cwd()
    store = breaker.BreakerStore(resolved_root)
    tally = store.load()
    tripped_sig = breaker.systemic_tripped(tally)
    is_tripped = tripped_sig is not None

    signatures_data = []
    for sig in sorted(tally.keys()):
        tasks = sorted(tally[sig])
        signatures_data.append({
            "signature": sig,
            "count": len(tasks),
            "tasks": tasks,
            "tripped": len(tasks) >= breaker.SYSTEMIC_BREAKER_THRESHOLD,
        })

    if json_output:
        payload = {
            "tripped": is_tripped,
            "tripped_signature": tripped_sig,
            "threshold": breaker.SYSTEMIC_BREAKER_THRESHOLD,
            "signatures": signatures_data,
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    if is_tripped:
        affected = sorted(tally.get(tripped_sig, set()))
        tasks_str = f" ({len(affected)} tasks: {', '.join(affected)})"
        typer.echo("⚠️ CIRCUIT BREAKER TRIPPED")
        typer.echo(
            f"  Systemic circuit breaker is active for signature '{tripped_sig}'{tasks_str}."
        )
        typer.echo("  Remedy: Inspect errors and run `aet breaker reset` to clear.\n")

    if not signatures_data:
        typer.echo("Circuit breaker is clear (0 failure signatures tracked).")
        return

    headers = ["Signature", "Task Count", "Affected Tasks", "Tripped"]
    rows = []
    for s in signatures_data:
        rows.append([
            s["signature"],
            str(s["count"]),
            ", ".join(s["tasks"]),
            "YES" if s["tripped"] else "NO",
        ])
    for line in _render_table(headers, rows):
        typer.echo(line)


@app.command("reset")
def reset(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        "--yes",
        "-y",
        help="Reset without interactive confirmation.",
    ),
    repo_root: Optional[Path] = typer.Option(
        None,
        "--repo-root",
        help="Repository root (defaults to git root or current working directory).",
    ),
) -> None:
    """Reset circuit breaker and clear refs/aet/breaker."""
    resolved_root = repo_root or resolve_repo_root(Path.cwd()) or Path.cwd()
    store = breaker.BreakerStore(resolved_root)

    if not force:
        confirmed = typer.confirm(
            "Reset circuit breaker and clear all failure signatures?",
            default=True,
        )
        if not confirmed:
            raise typer.Abort()

    cleared = store.clear()
    if cleared:
        typer.echo("✓ Circuit breaker reset (cleared refs/aet/breaker).")
    else:
        typer.echo("Circuit breaker was already clear (no refs/aet/breaker found).")
