"""Tests for the ``aet run`` / ``aet run-one`` dispatcher forwarding surface."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.cli._helpers import run_typer

aet = importlib.import_module("aet.cli.main")


class TestRunBaseForwarding:
    """``--base`` is forwarded to the orchestrator exactly as passed."""

    def test_run_forwards_base_to_orchestrator(self) -> None:
        with patch.object(aet, "_validate_preflight"):
            with patch.object(aet, "_spawn_detached") as spawn:
                spawn.return_value = 0
                result = run_typer(aet.app, ["run", "--base", "feat/x"])

        assert result.exit_code == 0, result.output
        argv = spawn.call_args[0][0]
        assert "--base" in argv
        assert argv[argv.index("--base") + 1] == "feat/x"


class TestRunOneBaseForwarding:
    """``--base`` is forwarded for single-plan runs too."""

    @pytest.fixture
    def tmp_cwd(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        (tmp_path / "docs" / "plans" / "example.md").write_text(
            "---\nid: example\nsize: S\n---\n\n# Example\n", encoding="utf-8"
        )
        return tmp_path

    def test_run_one_forwards_base_to_orchestrator(self, tmp_cwd: Path) -> None:
        with patch.object(aet, "_spawn_detached") as spawn:
            spawn.return_value = 0
            with patch.object(aet, "_wait_for_run", return_value=0):
                result = run_typer(
                    aet.app, ["run-one", "docs/plans/example.md", "--base", "feat/x"], cwd=str(tmp_cwd)
                )

        assert result.exit_code == 0, result.output
        argv = spawn.call_args[0][0]
        assert "--base" in argv
        assert argv[argv.index("--base") + 1] == "feat/x"


class TestRunOnePlanResolution:
    """``aet run-one`` accepts a bare task id and resolves it like ``aet ship`` (R-10)."""

    @pytest.fixture
    def tmp_cwd(self, tmp_path: Path, monkeypatch):
        """Run assertions from ``tmp_path`` so relative paths resolve there."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        (tmp_path / "docs" / "plans" / "rid-01.md").write_text(
            "---\nid: rid-01\n---\n", encoding="utf-8"
        )
        return tmp_path

    def test_run_one_resolves_bare_task_id(self, tmp_cwd: Path) -> None:
        with patch.object(aet, "_spawn_detached") as spawn:
            spawn.return_value = 0
            with patch.object(aet, "_wait_for_run", return_value=0):
                result = run_typer(aet.app, ["run-one", "rid-01"], cwd=str(tmp_cwd))

        assert result.exit_code == 0, result.output
        argv = spawn.call_args[0][0]
        plan_idx = argv.index("--plan-file")
        assert argv[plan_idx + 1] == "docs/plans/rid-01.md"

    def test_run_one_resolves_md_path_identically(self, tmp_cwd: Path) -> None:
        with patch.object(aet, "_spawn_detached") as spawn:
            spawn.return_value = 0
            with patch.object(aet, "_wait_for_run", return_value=0):
                result = run_typer(
                    aet.app, ["run-one", "docs/plans/rid-01.md"], cwd=str(tmp_cwd)
                )

        assert result.exit_code == 0, result.output
        argv = spawn.call_args[0][0]
        plan_idx = argv.index("--plan-file")
        assert argv[plan_idx + 1] == "docs/plans/rid-01.md"

    def test_run_one_rejects_missing_id_naming_both_forms(self, tmp_cwd: Path) -> None:
        with patch.object(aet, "_spawn_detached") as spawn:
            spawn.return_value = 0
            result = run_typer(aet.app, ["run-one", "no-such-id"], cwd=str(tmp_cwd))

        assert result.exit_code == 1, result.output
        assert "no-such-id" in result.output
        assert ".md" in result.output
        spawn.assert_not_called()
