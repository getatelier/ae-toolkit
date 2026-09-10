"""Tests for the generated CLI reference (``aet docs generate``)."""

from __future__ import annotations

from pathlib import Path

from aet.cli.docs import (
    AUTO_GENERATED_HEADER,
    _render_default,
    generate_cli_reference,
)
from aet.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_CLI_MD = REPO_ROOT / "docs" / "CLI.md"

_NOUN_GROUPS = [
    "state",
    "backlog",
    "desk",
    "docs",
    "epic",
    "gate",
    "hooks",
    "plan",
    "plans",
    "queue",
    "setup",
    "ship",
    "size",
    "sprint",
]

_TOP_LEVEL_COMMANDS = [
    "configure",
    "harness-guard",
    "metrics",
    "mine-learnings",
    "next",
    "panel",
    "performance-report",
    "reconcile",
    "release-prep",
    "report",
    "retro",
    "status",
    "validate-workflows",
]


def _generate(tmp_path: Path) -> str:
    output = tmp_path / "CLI.md"
    generate_cli_reference(app, output)
    return output.read_text(encoding="utf-8")


def test_generator_includes_auto_generated_marker(tmp_path: Path) -> None:
    text = _generate(tmp_path)
    assert AUTO_GENERATED_HEADER in text


def test_generator_includes_all_noun_groups(tmp_path: Path) -> None:
    text = _generate(tmp_path)
    for name in _NOUN_GROUPS:
        assert f"## `aet {name}`" in text, f"missing noun group: {name}"


def test_generator_includes_all_top_level_commands(tmp_path: Path) -> None:
    text = _generate(tmp_path)
    for name in _TOP_LEVEL_COMMANDS:
        assert f"## `aet {name}`" in text, f"missing top-level command: {name}"


def test_generator_includes_run_and_run_one(tmp_path: Path) -> None:
    text = _generate(tmp_path)
    assert "## `aet run`" in text
    assert "## `aet run-one`" in text


def test_generator_includes_help_text(tmp_path: Path) -> None:
    text = _generate(tmp_path)
    assert "Run the orchestrator in batch mode." in text
    assert "Run the orchestrator for a single plan." in text
    assert "Documentation linting and syncing." in text


def test_generator_includes_subcommands(tmp_path: Path) -> None:
    text = _generate(tmp_path)
    assert "## `aet docs generate`" in text
    assert "## `aet docs lint`" in text


def test_generator_output_is_machine_independent(tmp_path: Path) -> None:
    """No generated default may contain the generating machine's home path.

    Defaults built from ``Path.home()`` (the telemetry archive root) used to be
    rendered absolute, so the committed file carried one contributor's home and
    the drift guard below could only pass on their machine.
    """
    text = _generate(tmp_path)
    assert str(Path.home()) not in text
    assert "(default: `~/.aet/telemetry`)" in text


def test_render_default_collapses_home_prefix() -> None:
    assert _render_default(Path.home() / ".aet" / "telemetry") == str(
        Path("~/.aet/telemetry")
    )
    assert _render_default(Path.home()) == "~"
    assert _render_default(Path("/etc/hosts")) == "/etc/hosts"
    assert _render_default(7) == "7"


def test_generator_drift_guard_matches_committed_file(tmp_path: Path) -> None:
    """Regenerated content must equal the committed docs/CLI.md."""
    output = tmp_path / "CLI.md"
    generate_cli_reference(app, output)
    assert COMMITTED_CLI_MD.exists(), "committed docs/CLI.md not found"
    assert output.read_bytes() == COMMITTED_CLI_MD.read_bytes(), (
        "docs/CLI.md is out of sync with the command tree — run `aet docs generate`"
    )
