#!/usr/bin/env python3
"""aet docs — documentation governance commands."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click
import typer
import typer.core as typer_core
import typer.main as typer_main

from aet import docs_lint
from aet.cli.help_index import _walk_commands

AUTO_GENERATED_HEADER = (
    "<!-- AUTO-GENERATED: do not edit manually — run `aet docs generate` to refresh. -->"
)


def _repo_root_from(path: Path) -> Path:
    """Resolve the repository root via git, falling back to layout heuristics."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path.parent if path.is_file() else path,
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        if path.name == ".agents" and path.parent.is_dir():
            return path.parent
        return path


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def _render_default(default: object) -> str:
    """Render a default value with the user's home collapsed to ``~``.

    Defaults derived from ``Path.home()`` — the telemetry archive root, for
    one — otherwise bake the generating machine's home directory into the
    committed reference. The generated file must be identical on every
    machine, or the drift guard passes only for whoever last regenerated it.
    """
    text = str(default)
    home = str(Path.home())
    if text == home:
        return "~"
    if text.startswith(home + os.sep):
        return "~" + text[len(home) :]
    return text


def _format_option(param: click.Parameter) -> str:
    """Format a click parameter as a markdown list item."""
    name = param.opts[0] if param.opts else param.name
    parts = [f"`{name}`"]
    if param.type.name not in ("STRING", "TEXT"):
        parts.append(f"*{param.type.name}*")
    if param.help:
        parts.append(f"— {param.help}")
    if param.default is not None and not param.required:
        parts.append(f"(default: `{_render_default(param.default)}`)")
    if param.required:
        parts.append("(required)")
    return " ".join(parts)


def _format_command(path: tuple[str, ...], cmd: click.Command) -> list[str]:
    """Render a single command as markdown lines."""
    invocation = " ".join(path)
    lines = [f"## `{invocation}`", ""]
    if cmd.help:
        lines.append(cmd.help)
        lines.append("")
    if cmd.params:
        lines.append("### Options")
        lines.append("")
        for param in cmd.params:
            lines.append(f"- {_format_option(param)}")
        lines.append("")
    if isinstance(cmd, (click.Group, typer_core.TyperGroup)) and cmd.commands:
        lines.append("### Subcommands")
        lines.append("")
        for subname in sorted(cmd.commands):
            subcmd = cmd.commands[subname]
            help_text = (subcmd.help or "").split("\n")[0]
            if help_text:
                lines.append(f"- `{subname}`: {help_text}")
            else:
                lines.append(f"- `{subname}`")
        lines.append("")
    return lines


def generate_cli_reference(typer_app: typer.Typer, output: Path) -> None:
    """Generate the CLI reference markdown file from *typer_app* to *output*."""
    click_group = typer_main.get_group(typer_app)
    lines = [
        AUTO_GENERATED_HEADER,
        "",
        "# AE Toolkit CLI Reference",
        "",
    ]
    for path, cmd in _walk_commands(click_group, ("aet",)):
        lines.extend(_format_command(path, cmd))
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def cmd_lint(args: argparse.Namespace) -> int:
    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = _repo_root_from(Path.cwd())

    if args.rules:
        rules_file = Path(args.rules).resolve()
    else:
        rules_file = repo_root / ".agents" / "doc-rules.yaml"

    if not rules_file.exists():
        return _fail(f"rules file not found: {rules_file}")

    severity = getattr(args, "severity", "error") or "error"
    violations = docs_lint.lint_docs(rules_file, repo_root, min_severity=severity)
    if violations:
        for path, message in violations:
            print(f"{path}: {message}", file=sys.stderr)
        return 1

    print("✓ docs lint passed")
    return 0


app = typer.Typer()


@app.command("lint")
def lint(
    rules: Optional[str] = typer.Option(
        None,
        "--rules",
        help="Rules file (default: .agents/doc-rules.yaml under repo root)",
    ),
    repo_root: Optional[str] = typer.Option(
        None,
        "--repo-root",
        help="Repository root (default: git root or current directory)",
    ),
    severity: str = typer.Option(
        "error",
        "--severity",
        help="Minimum severity to enforce: 'error' (default) or 'warning'.",
    ),
) -> None:
    """Lint documentation against declarative rules."""
    args = argparse.Namespace(rules=rules, repo_root=repo_root, severity=severity)
    rc = cmd_lint(args)
    raise typer.Exit(rc)


@app.command("generate")
def generate(
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        help="Output file path (default: docs/CLI.md under repo root).",
    ),
) -> None:
    """Generate the CLI reference markdown file."""
    from aet.cli.main import app as main_app

    repo_root = _repo_root_from(Path.cwd())
    if output is None:
        output = repo_root / "docs" / "CLI.md"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    generate_cli_reference(main_app, output)
    print(f"✓ Generated {output}")


if __name__ == "__main__":
    app()
