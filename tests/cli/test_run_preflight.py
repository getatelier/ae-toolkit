"""Tests for synchronous preflight validation and startup handshake in ``aet run`` / ``aet run-one``."""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer

from aet import breaker
from aet.backends.git_refs_backend import GitRefsBackend
from aet.queue import QueueIntegrityError
from tests.cli._helpers import run_typer

aet = importlib.import_module("aet.cli.main")


def _git_init(root: Path) -> None:
    """Initialize a bare-bones git repo in root."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Tester")):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)


@pytest.fixture
def repo_env(tmp_path: Path, monkeypatch):
    """Create a temporary git repo with valid aet queue and config."""
    monkeypatch.chdir(tmp_path)
    _git_init(tmp_path)
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    queue_file = agents_dir / "aet-queue"
    history_file = agents_dir / "work-history.jsonl"
    backend = GitRefsBackend(queue_file=str(queue_file), history_file=str(history_file), repo_root=str(tmp_path))
    backend.save([])
    return tmp_path


class TestSynchronousPreflightBreaker:
    """Systemic circuit breaker trips stop `aet run` and `aet run-one` before spawning."""

    def test_run_fails_fast_when_breaker_tripped(self, repo_env: Path) -> None:
        store = breaker.BreakerStore(repo_env)
        # 3 tasks with the same failure signature => systemic breaker tripped
        tally = {"sig-fail-timeout": {"task-1", "task-2", "task-3"}}
        store.save(tally)

        with patch.object(aet, "_spawn_detached") as spawn:
            result = run_typer(aet.app, ["run"], cwd=str(repo_env))

        assert result.exit_code == 1, result.output
        assert "systemic breaker" in result.output
        spawn.assert_not_called()

    def test_run_one_fails_fast_when_breaker_tripped(self, repo_env: Path) -> None:
        store = breaker.BreakerStore(repo_env)
        tally = {"sig-fail-crash": {"task-1", "task-2", "task-3"}}
        store.save(tally)

        plans_dir = repo_env / "docs" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan = plans_dir / "test-task.md"
        plan.write_text(
            "---\nid: test-task\nsize: S\n---\n\n# Test Task\n\n## Task List\n\n1. Do work\n",
            encoding="utf-8",
        )

        with patch.object(aet, "_spawn_detached") as spawn:
            result = run_typer(aet.app, ["run-one", "test-task"], cwd=str(repo_env))

        assert result.exit_code == 1, result.output
        assert "systemic breaker" in result.output
        spawn.assert_not_called()


class TestSynchronousPreflightQueueIntegrity:
    """Corrupted queue fails `aet run` synchronously before spawning."""

    def test_run_fails_fast_on_queue_integrity_error(self, repo_env: Path) -> None:
        with patch(
            "aet.backends.git_refs_backend.GitRefsBackend.load",
            side_effect=QueueIntegrityError("Corrupted queue ref"),
        ):
            with patch.object(aet, "_spawn_detached") as spawn:
                result = run_typer(aet.app, ["run"], cwd=str(repo_env))

        assert result.exit_code == 1, result.output
        assert "Corrupted queue ref" in result.output or "⛔" in result.output
        spawn.assert_not_called()


class TestSynchronousPreflightCliBinary:
    """Missing or unresolvable agent CLI binary fails preflight before spawning."""

    def test_run_fails_fast_when_cli_bin_unresolvable(self, repo_env: Path) -> None:
        with patch.object(aet, "_spawn_detached") as spawn:
            result = run_typer(aet.app, ["run", "--cli-bin", "nonexistent-agent-binary-xyz"], cwd=str(repo_env))

        assert result.exit_code == 1, result.output
        spawn.assert_not_called()


class TestSynchronousPreflightPlanValidation:
    """Missing or invalid plan fails `aet run-one` synchronously before spawning."""

    def test_run_one_fails_fast_on_missing_plan(self, repo_env: Path) -> None:
        with patch.object(aet, "_spawn_detached") as spawn:
            result = run_typer(aet.app, ["run-one", "missing-plan-id"], cwd=str(repo_env))

        assert result.exit_code == 1, result.output
        spawn.assert_not_called()

    def test_run_one_fails_fast_on_invalid_plan_spec(self, repo_env: Path) -> None:
        plans_dir = repo_env / "docs" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan = plans_dir / "invalid-plan.md"
        # File with empty/invalid content
        plan.write_text("not a markdown with frontmatter", encoding="utf-8")

        with patch.object(aet, "_spawn_detached") as spawn:
            result = run_typer(aet.app, ["run-one", "invalid-plan"], cwd=str(repo_env))

        assert result.exit_code == 1, result.output
        spawn.assert_not_called()


class TestSpawnDetachedHandshake:
    """`_spawn_detached` checks child process vitality before reporting success."""

    def test_spawn_detached_catches_immediate_child_exit(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        run_id = "test-run-fail"

        # Mock Popen returning a process that already terminated (exit code 1)
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(typer.Exit) as exc_info:
                aet._spawn_detached(["--max-jobs", "4"], run_id)

            assert exc_info.value.exit_code == 1

        pid_file = tmp_path / ".agents" / "runs" / run_id / "pid"
        assert not pid_file.is_file()

    def test_spawn_detached_succeeds_when_child_remains_alive(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        run_id = "test-run-ok"

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None  # Process is alive

        with patch("subprocess.Popen", return_value=mock_proc):
            rc = aet._spawn_detached(["--max-jobs", "4"], run_id)

            assert rc == 0

        pid_file = tmp_path / ".agents" / "runs" / run_id / "pid"
        assert pid_file.is_file()
        assert pid_file.read_text(encoding="utf-8").strip() == "12345"
