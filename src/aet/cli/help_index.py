"""Flat, single-hop help index for the top-level ``aet --help`` surface.

The tree walk is intentionally shared with ``aet.cli.docs``: any change to the
command shape is reflected in both ``docs/CLI.md`` and the live help index.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import click
import typer
import typer.core as typer_core
import typer.main as typer_main

if TYPE_CHECKING:
    pass


SECTIONS: dict[str, str] = {
    # Plan work
    "plan": "Plan work",
    "plans": "Plan work",
    "sprint": "Plan work",
    "epic": "Plan work",
    "backlog": "Plan work",
    "docs": "Plan work",
    # Run work
    "run": "Run work",
    "run-one": "Run work",
    "next": "Run work",
    "status": "Run work",
    "state": "Run work",
    "queue": "Run work",
    "breaker": "Run work",
    # Ship work
    "ship": "Ship work",
    "gate": "Ship work",
    "desk": "Ship work",
    "size": "Ship work",
    # Inspect & learn
    "report": "Inspect & learn",
    "performance-report": "Inspect & learn",
    "metrics": "Inspect & learn",
    "retro": "Inspect & learn",
    "mine-learnings": "Inspect & learn",
    "learnings": "Inspect & learn",
    "handoff": "Inspect & learn",
    "context": "Inspect & learn",
    # Set up & maintain
    "setup": "Set up & maintain",
    "configure": "Set up & maintain",
    "hooks": "Set up & maintain",
    "harness-guard": "Set up & maintain",
    "panel": "Set up & maintain",
    "reconcile": "Set up & maintain",
    "validate-workflows": "Set up & maintain",
    "release-prep": "Set up & maintain",
}

_SECTION_ORDER = (
    "Plan work",
    "Run work",
    "Ship work",
    "Inspect & learn",
    "Set up & maintain",
)


@dataclass(frozen=True)
class LeafCommand:
    """One runnable leaf command in the Typer tree."""

    path: tuple[str, ...]
    help: str
    args: tuple[str, ...]

    @property
    def name(self) -> str:
        """Return the command name without the ``aet`` prefix."""
        return " ".join(self.path[1:])

    @property
    def invocation(self) -> str:
        """Return the full runnable invocation including ``aet``."""
        return " ".join(self.path)

    @property
    def example(self) -> str:
        """Return a runnable example with placeholder tokens for required args."""
        parts = list(self.path)
        parts.extend(f"<{arg}>" for arg in self.args)
        return " ".join(parts)


def _is_group(cmd: click.Command) -> bool:
    return isinstance(cmd, (click.Group, typer_core.TyperGroup))


def _has_subcommands(cmd: click.Command) -> bool:
    return _is_group(cmd) and bool(getattr(cmd, "commands", {}))


def _command_help(cmd: click.Command) -> str:
    """Return the one-line help text for *cmd*."""
    text: str | None = cmd.help
    if not text and cmd.callback is not None:
        text = cmd.callback.__doc__
    if text:
        return text.strip().splitlines()[0].strip()
    return ""


def _required_arguments(cmd: click.Command) -> tuple[str, ...]:
    """Return required positional argument names for *cmd*, excluding options."""
    args: list[str] = []
    for param in cmd.params or []:
        is_argument = isinstance(param, (click.Argument, typer_core.TyperArgument))
        if is_argument and param.required:
            name = param.name
            if not name and param.opts:
                name = param.opts[0]
            if name:
                args.append(name)
    return tuple(args)


def _walk_commands(
    click_group: click.Group,
    prefix: tuple[str, ...],
) -> Iterator[tuple[tuple[str, ...], click.Command]]:
    """Yield (path, command) for every command reachable from *click_group*.

    This is the same traversal used by ``aet docs generate``; it lives here so
    both surfaces share one definition of the tree.
    """
    ctx = click.Context(click_group)
    for name in click_group.list_commands(ctx):
        cmd = click_group.get_command(ctx, name)
        if cmd is None:
            continue
        path = (*prefix, name)
        yield path, cmd
        if _is_group(cmd):
            yield from _walk_commands(cmd, path)


def walk_leaf_commands(
    typer_app: typer.Typer,
    prefix: tuple[str, ...] = ("aet",),
) -> Iterator[LeafCommand]:
    """Yield every runnable leaf command reachable from *typer_app*."""
    click_group = typer_main.get_group(typer_app)
    for path, cmd in _walk_commands(click_group, prefix):
        if _has_subcommands(cmd):
            continue
        yield LeafCommand(
            path=path,
            help=_command_help(cmd),
            args=_required_arguments(cmd),
        )


def resolve_section(path: Sequence[str]) -> str:
    """Return the presentation section for a command *path*.

    The section is determined by the top-level name (the element immediately
    after ``aet``). An unmapped top-level name raises ``ValueError`` so that
    newly-added commands fail loudly rather than vanishing from the index.
    """
    if len(path) < 2:
        raise ValueError(f"Command path too short: {path!r}")
    top = path[1]
    section = SECTIONS.get(top)
    if section is None:
        raise ValueError(f"Unmapped top-level command: {top}")
    return section


def _group_by_section(
    commands: Sequence[LeafCommand],
) -> dict[str, list[LeafCommand]]:
    sections: dict[str, list[LeafCommand]] = {}
    for cmd in commands:
        section = resolve_section(cmd.path)
        sections.setdefault(section, []).append(cmd)
    return sections


def _render_plain(commands: Sequence[LeafCommand]) -> str:
    """Render the flat index as plain text with no box-drawing characters."""
    sections = _group_by_section(commands)
    lines = [
        "Usage: aet [OPTIONS] COMMAND [ARGS]...",
        "",
        "Agentic Engineering Toolkit CLI",
        "",
        "Options:",
        "  --version          Show the version and exit.",
        "  --help             Show this help message and exit.",
        "",
        "Commands:",
    ]
    for section in _SECTION_ORDER:
        if section not in sections:
            continue
        lines.append("")
        lines.append(section)
        for cmd in sections[section]:
            parts = [cmd.name]
            if cmd.args:
                parts.extend(f"<{arg}>" for arg in cmd.args)
            if cmd.help:
                parts.append(f"— {cmd.help}")
            lines.append("  " + " ".join(parts))
    lines.append("")
    return "\n".join(lines)


def _render_rich(commands: Sequence[LeafCommand]) -> None:
    """Render the flat index with Rich panels/tables for interactive TTYs."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print("Usage: aet [OPTIONS] COMMAND [ARGS]...", style="bold")
    console.print("")
    console.print("Agentic Engineering Toolkit CLI")
    console.print("")

    options = Table.grid(padding=(0, 2))
    options.add_column(style="cyan", justify="left")
    options.add_column()
    options.add_row("--version", "Show the version and exit.")
    options.add_row("--help", "Show this help message and exit.")
    console.print("Options")
    console.print(options)
    console.print("")
    console.print("Commands")

    sections = _group_by_section(commands)
    for section in _SECTION_ORDER:
        if section not in sections:
            continue
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan", justify="left")
        table.add_column()
        for cmd in sections[section]:
            invocation = cmd.name
            if cmd.args:
                invocation += " " + " ".join(f"<{arg}>" for arg in cmd.args)
            table.add_row(invocation, cmd.help)
        console.print("")
        console.print(section)
        console.print(table)
    console.print("")


def render_help_index(typer_app: typer.Typer) -> None:
    """Print the flat help index for *typer_app* to stdout."""
    commands = list(walk_leaf_commands(typer_app))
    if sys.stdout.isatty():
        _render_rich(commands)
    else:
        sys.stdout.write(_render_plain(commands))
