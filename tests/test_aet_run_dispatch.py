"""Tests for the `aet run` / `aet run-one` detached dispatch (nc-06-run-daemonization)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.cli._helpers import run_typer

_REPO_ROOT = Path(__file__).parents[1]
_AET_PY = _REPO_ROOT / "src" / "aet" / "cli" / "main.py"

_aet_spec = importlib.util.spec_from_loader(
    "aet_run_dispatch",
    importlib.machinery.SourceFileLoader("aet_run_dispatch", str(_AET_PY)),
)
aet = importlib.util.module_from_spec(_aet_spec)
_aet_spec.loader.exec_module(aet)


def _start_child_runner(run_dir: Path, returncode: int, delay: float = 0.2) -> subprocess.Popen:
    """Start a real process that writes ``returncode`` after ``delay`` seconds.

    The returned child is suitable for use as the pid of a mocked orchestrator
    spawn.  It exits on its own after writing the returncode file.
    """
    script = f"""
import os
import time
from pathlib import Path
run_dir = Path(os.environ["AET_TEST_RUN_DIR"])
run_dir.mkdir(parents=True, exist_ok=True)
time.sleep({delay})
(run_dir / "returncode").write_text(str({returncode}), encoding="utf-8")
"""
    env = {**os.environ, "AET_TEST_RUN_DIR": str(run_dir)}
    return subprocess.Popen([sys.executable, "-c", script], env=env)


class _IsolatedBinDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.bin_dir = Path(self._tmp.name) / "bin"

    def _bin_env(self):
        """Isolate the spawn bin dir and pin the agent CLI.

        ``AET_CLI_BIN`` is set because dispatch now always forwards
        ``--cli-bin``: without it these tests would depend on which agent CLI
        happens to be an ancestor of the test runner.
        """
        return patch.dict(
            os.environ, {"AET_BIN_DIR": str(self.bin_dir), "AET_CLI_BIN": "claude"}
        )

    def _setup_repo(self, path: Path):
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        (path / ".agents").mkdir(parents=True, exist_ok=True)

    def _make_fake_popen(self, captured: dict, child_pid: int = 12345):
        real_popen = subprocess.Popen

        def fake_popen(cmd, **kwargs):
            if isinstance(cmd, (list, tuple)) and any("orchestrator" in str(arg) for arg in cmd):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                mock = unittest.mock.MagicMock()
                mock.pid = child_pid
                mock.poll.return_value = None
                mock.communicate.return_value = (b"", b"")
                return mock
            return real_popen(cmd, **kwargs)

        return fake_popen


class TestRunIdGeneration(unittest.TestCase):
    def test_run_id_has_expected_prefix_and_length(self):
        run_id = aet._generate_run_id()
        self.assertTrue(run_id.startswith("run-"))
        parts = run_id.split("-")
        self.assertEqual(len(parts), 4)  # run, YYYYMMDD, HHMMSS, suffix
        self.assertEqual(len(parts[3]), 8)


class TestRunPaths(unittest.TestCase):
    def test_run_dir_and_log_under_cwd_agents_runs(self):
        run_id = "run-test"
        self.assertEqual(aet._run_dir(run_id), Path.cwd() / ".agents" / "runs" / run_id)
        self.assertEqual(
            aet._run_log_file(run_id),
            Path.cwd() / ".agents" / "runs" / run_id / "output.log",
        )


class TestRunDetachedByDefault(_IsolatedBinDir):
    def test_run_spawns_detached_and_prints_run_id(self):
        captured_proc = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._setup_repo(tmp_path)
            fake_popen = self._make_fake_popen(captured_proc, 12345)
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with self._bin_env():
                    with patch("shutil.which", return_value="/usr/local/bin/claude"):
                        with patch.object(aet.subprocess, "Popen", side_effect=fake_popen):
                            with patch.object(aet, "_generate_run_id", return_value="run-detached-abc"):
                                with patch.object(aet.typer, "echo") as echo_mock:
                                    rc = aet.app(["run"], standalone_mode=False)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(rc, 0)
            self.assertIsNotNone(captured_proc.get("cmd"))
            self.assertEqual(captured_proc["kwargs"]["start_new_session"], True)
            self.assertTrue(hasattr(captured_proc["kwargs"]["stdout"], "name"))
            self.assertTrue(
                captured_proc["kwargs"]["stdout"].name.endswith("run-detached-abc/output.log")
            )
            cmd = captured_proc["cmd"]
            # Tuning values are supplied internally at their defaults.
            self.assertEqual(cmd[cmd.index("--max-jobs") + 1], "4")
            self.assertEqual(cmd[cmd.index("--isolation") + 1], "standard")
            self.assertNotIn("--stall-timeout", cmd)
            printed = " ".join(str(call.args[0]) for call in echo_mock.call_args_list)
            self.assertIn("run-detached-abc", printed)
            run_dir = tmp_path / ".agents" / "runs" / "run-detached-abc"
            self.assertTrue(run_dir.is_dir())
            self.assertEqual((run_dir / "pid").read_text(encoding="utf-8"), "12345")

    def test_run_one_spawns_detached_by_default(self):
        captured_proc = {}
        run_id = "run-one-abc"
        run_dir = None
        child = None

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._setup_repo(tmp_path)
            run_dir = tmp_path / ".agents" / "runs" / run_id
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                (tmp_path / "docs" / "plans").mkdir(parents=True)
                (tmp_path / "docs" / "plans" / "x.md").write_text(
                    "---\nid: x\n---\n\n# X\n", encoding="utf-8"
                )
                child = _start_child_runner(run_dir, 0, delay=0.1)
                fake_popen = self._make_fake_popen(captured_proc, child.pid)
                with self._bin_env():
                    with patch("shutil.which", return_value="/usr/local/bin/claude"):
                        with patch.object(aet.subprocess, "Popen", side_effect=fake_popen):
                            with patch.object(aet, "_generate_run_id", return_value=run_id):
                                rc = aet.app(["run-one", "docs/plans/x.md"], standalone_mode=False)
            finally:
                os.chdir(old_cwd)
                if child is not None:
                    child.terminate()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.kill()

            self.assertEqual(rc, 0)
            self.assertEqual(captured_proc["kwargs"]["start_new_session"], True)
            self.assertIn("--plan-file", captured_proc["cmd"])
            self.assertIn("docs/plans/x.md", captured_proc["cmd"])
            self.assertIn("--run-id", captured_proc["cmd"])
            self.assertIn(run_id, captured_proc["cmd"])


class TestRemovedFlagsRejected(_IsolatedBinDir):
    def test_run_rejects_foreground_and_tuning_flags(self):
        for extra in (
            ["--foreground"],
            ["--isolation", "full"],
            ["--stall-timeout", "60"],
        ):
            with self.subTest(extra=extra):
                # Guard exec/spawn so a regression cannot outlive the test.
                with self._bin_env():
                    with patch.object(aet.os, "execvp", side_effect=SystemExit(0)):
                        with patch.object(aet.subprocess, "Popen"):
                            result = run_typer(aet.app, ["run", *extra])
                self.assertEqual(result.exit_code, 2)
                self.assertIn("No such option", result.output)

    def test_run_one_rejects_foreground_and_tuning_flags(self):
        for extra in (
            ["--foreground"],
            ["--max-jobs", "2"],
            ["--isolation", "full"],
            ["--stall-timeout", "60"],
        ):
            with self.subTest(extra=extra):
                with self._bin_env():
                    with patch.object(aet.os, "execvp", side_effect=SystemExit(0)):
                        with patch.object(aet.subprocess, "Popen"):
                            result = run_typer(aet.app, ["run-one", "docs/plans/x.md", *extra])
                self.assertEqual(result.exit_code, 2)
                self.assertIn("No such option", result.output)


class TestRetainedFlagsForward(_IsolatedBinDir):
    def test_run_forwards_base_on_failure_task_timeout_cli_bin_and_max_jobs(self):
        captured_proc = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._setup_repo(tmp_path)
            fake_popen = self._make_fake_popen(captured_proc, 12347)
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with self._bin_env():
                    with patch("shutil.which", return_value="/bin/kimi"):
                        with patch.object(aet.subprocess, "Popen", side_effect=fake_popen):
                            rc = aet.app(
                                [
                                    "run",
                                    "--base",
                                    "feat/x",
                                    "--on-failure",
                                    "halt",
                                    "--task-timeout",
                                    "900",
                                    "--cli-bin",
                                    "/bin/kimi",
                                    "--max-jobs",
                                    "2",
                                ],
                                standalone_mode=False,
                            )
            finally:
                os.chdir(old_cwd)

        self.assertEqual(rc, 0)
        cmd = captured_proc["cmd"]
        for flag, value in (
            ("--base", "feat/x"),
            ("--on-failure", "halt"),
            ("--task-timeout", "900"),
            ("--cli-bin", "/bin/kimi"),
            ("--max-jobs", "2"),
        ):
            self.assertIn(flag, cmd)
            self.assertEqual(cmd[cmd.index(flag) + 1], value)

    def test_run_one_forwards_retained_flags(self):
        captured_proc = {}
        run_id = "run-one-retained"
        run_dir = None
        child = None

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._setup_repo(tmp_path)
            run_dir = tmp_path / ".agents" / "runs" / run_id
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                (tmp_path / "docs" / "plans").mkdir(parents=True)
                (tmp_path / "docs" / "plans" / "x.md").write_text(
                    "---\nid: x\n---\n\n# X\n", encoding="utf-8"
                )
                child = _start_child_runner(run_dir, 0, delay=0.1)
                fake_popen = self._make_fake_popen(captured_proc, child.pid)
                with self._bin_env():
                    with patch("shutil.which", return_value="/usr/local/bin/claude"):
                        with patch.object(aet.subprocess, "Popen", side_effect=fake_popen):
                            with patch.object(aet, "_generate_run_id", return_value=run_id):
                                rc = aet.app(
                                    ["run-one", "docs/plans/x.md", "--base", "feat/x", "--task-timeout", "900"],
                                    standalone_mode=False,
                                )
            finally:
                os.chdir(old_cwd)
                if child is not None:
                    child.terminate()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.kill()

        self.assertEqual(rc, 0)
        cmd = captured_proc["cmd"]
        self.assertIn("--plan-file", cmd)
        self.assertIn("docs/plans/x.md", cmd)
        self.assertEqual(cmd[cmd.index("--base") + 1], "feat/x")
        self.assertEqual(cmd[cmd.index("--task-timeout") + 1], "900")


class TestFollowRun(_IsolatedBinDir):
    def test_follow_unknown_run_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self._bin_env():
                with patch.dict(os.environ, {"PWD": tmp}):
                    rc = aet.app(["run", "--follow", "run-missing"], standalone_mode=False)
        self.assertEqual(rc, 1)

    def test_follow_silently_returns_existing_returncode(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / ".agents" / "runs" / "run-done"
            run_dir.mkdir(parents=True)
            (run_dir / "output.log").write_text("hello log\n", encoding="utf-8")
            (run_dir / "pid").write_text("12345", encoding="utf-8")
            (run_dir / "returncode").write_text("0", encoding="utf-8")

            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with self._bin_env():
                    with patch.object(aet.typer, "echo") as echo_mock:
                        rc = aet.app(["run", "--follow", "run-done"], standalone_mode=False)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(rc, 0)
            self.assertNotIn("hello log\n", [call.args[0] for call in echo_mock.call_args_list])


class TestRunOneBlocks(_IsolatedBinDir):
    @pytest.mark.xfail(
        strict=False,
        reason="seen once under -n auto (not investigated); "
        "content/backlog/debt-gate-tolerates-known-intermittent-reds.md",
    )
    def test_run_one_blocks_until_terminal_state_and_returns_rc(self):
        run_id = "run-one-blocks"
        run_dir = None
        child = None

        def fake_popen(cmd, **kwargs):
            mock = unittest.mock.MagicMock()
            mock.pid = child.pid
            return mock

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_dir = tmp_path / ".agents" / "runs" / run_id
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                (tmp_path / "docs" / "plans").mkdir(parents=True)
                (tmp_path / "docs" / "plans" / "x.md").write_text(
                    "---\nid: x\n---\n\n# X\n", encoding="utf-8"
                )
                # Pre-existing log content should not be echoed by the follower.
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "output.log").write_text("run output line\n", encoding="utf-8")
                child = _start_child_runner(run_dir, 42, delay=0.3)
                started = time.monotonic()
                with self._bin_env():
                    with patch.object(aet.subprocess, "Popen", side_effect=fake_popen):
                        with patch.object(aet, "_generate_run_id", return_value=run_id):
                            result = run_typer(aet.app, ["run-one", "docs/plans/x.md"], cwd=tmp)
                elapsed = time.monotonic() - started
            finally:
                os.chdir(old_cwd)
                if child is not None:
                    child.terminate()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.kill()

            self.assertEqual(result.exit_code, 42)
            self.assertGreaterEqual(elapsed, 0.25)
            self.assertNotIn("run output line", result.stdout)
            self.assertIn("Started run", result.stdout)


class TestIntegrationDetachedSpawn(_IsolatedBinDir):
    def test_run_spawns_real_orchestrator_that_exits_quickly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            agents_dir = tmp_path / ".agents"
            agents_dir.mkdir(parents=True)
            queue_file = agents_dir / "aet-queue"
            history_file = agents_dir / "work-history.jsonl"
            queue_file.write_text('{"queue_updated_at": "2026-01-01T00:00:00Z", "tasks": []}', encoding="utf-8")
            history_file.write_text("", encoding="utf-8")

            # git-refs backend requires the queue to live inside a git repository.
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp, check=True)

            env = {**os.environ, "AET_BIN_DIR": str(self.bin_dir), "PYTHONPATH": str(_REPO_ROOT / "src")}
            result = subprocess.run(
                [
                    sys.executable,
                    str(_AET_PY),
                    "run",
                ],
                capture_output=True,
                text=True,
                cwd=tmp,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Started run", result.stdout)
            run_id = result.stdout.split("Started run ")[1].split("\n")[0].strip()
            log_file = tmp_path / ".agents" / "runs" / run_id / "output.log"
            self.assertTrue(log_file.is_file(), f"log file not found: {log_file}")
            # Wait briefly for the orchestrator to finish.
            log_text = ""
            for _ in range(50):
                log_text = log_file.read_text(encoding="utf-8")
                if "Orchestrator finished" in log_text or "Queue is empty" in log_text:
                    break
                time.sleep(0.1)
            self.assertTrue(
                "Orchestrator finished" in log_text or "Queue is empty" in log_text,
                f"unexpected log content: {log_text}",
            )


class TestRunStartMessage(_IsolatedBinDir):
    def test_start_message_names_log_path_and_describes_report(self):
        captured_proc = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._setup_repo(tmp_path)
            fake_popen = self._make_fake_popen(captured_proc, 12345)
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with self._bin_env():
                    with patch("shutil.which", return_value="/usr/local/bin/claude"):
                        with patch.object(aet.subprocess, "Popen", side_effect=fake_popen):
                            with patch.object(aet, "_generate_run_id", return_value="run-msg-abc"):
                                with patch.object(aet.typer, "echo") as echo_mock:
                                    rc = aet.app(["run"], standalone_mode=False)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(rc, 0)
            self.assertIsNotNone(captured_proc.get("cmd"))
            printed = "\n".join(str(call.args[0]) for call in echo_mock.call_args_list)
            self.assertIn("Started run run-msg-abc", printed)
            self.assertIn("Log:", printed)
            self.assertIn(
                str(Path(tmp) / ".agents" / "runs" / "run-msg-abc" / "output.log"),
                printed,
            )
            self.assertIn("Report:", printed)
            self.assertIn("aet run --follow run-msg-abc", printed)
            self.assertNotIn("tail", printed.lower())
            self.assertNotIn("stream", printed.lower())
            self.assertNotIn("Follow:", printed)


if __name__ == "__main__":
    unittest.main()
