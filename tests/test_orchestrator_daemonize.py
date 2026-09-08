"""Tests for the orchestrator's detached-run mode (nc-06-run-daemonization)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from aet import telemetry
from aet.cli_adapter import CLIAdapter

_FAKE_ADAPTER = CLIAdapter(
    name="test",
    bin="echo",
    prompt_flag="-p",
    workdir_flag=None,
    headless_flag=None,
)

_ORCHESTRATOR_BIN = Path(__file__).parents[1] / "src" / "aet" / "cli" / "orchestrator.py"
_orchestrator_loader = importlib.machinery.SourceFileLoader(
    "orchestrator_daemonize", str(_ORCHESTRATOR_BIN)
)
_spec = importlib.util.spec_from_loader("orchestrator_daemonize", _orchestrator_loader)
orchestrator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orchestrator)

_CLI_MAIN_PY = Path(__file__).parents[1] / "src" / "aet" / "cli" / "main.py"
_cli_main_loader = importlib.machinery.SourceFileLoader("aet_cli_main_daemonize", str(_CLI_MAIN_PY))
_cli_main_spec = importlib.util.spec_from_loader("aet_cli_main_daemonize", _cli_main_loader)
cli_main = importlib.util.module_from_spec(_cli_main_spec)
_cli_main_spec.loader.exec_module(cli_main)


def _start_child_runner(run_dir: Path, returncode: int, delay: float = 0.2) -> subprocess.Popen:
    """Start a real process that writes ``returncode`` after ``delay`` seconds."""
    script = f"""
import os
import time
from pathlib import Path
run_dir = Path(os.environ["AET_TEST_RUN_DIR"])
time.sleep({delay})
(run_dir / "returncode").write_text(str({returncode}), encoding="utf-8")
"""
    env = {**os.environ, "AET_TEST_RUN_DIR": str(run_dir)}
    return subprocess.Popen([sys.executable, "-c", script], env=env)


class TestRunPaths(unittest.TestCase):
    def test_runs_dir_is_under_agents(self):
        with tempfile.TemporaryDirectory() as repo_root:
            self.assertEqual(
                orchestrator._runs_dir(repo_root),
                Path(repo_root) / ".agents" / "runs",
            )

    def test_run_dir_is_named_by_run_id(self):
        with tempfile.TemporaryDirectory() as repo_root:
            self.assertEqual(
                orchestrator._run_dir(repo_root, "run-abc"),
                Path(repo_root) / ".agents" / "runs" / "run-abc",
            )


class TestRunMetadata(unittest.TestCase):
    def test_write_run_metadata_creates_pid_and_started_files(self):
        with tempfile.TemporaryDirectory() as repo_root:
            run_id = "run-test-metadata"
            orchestrator._write_run_metadata(repo_root, run_id)
            rdir = orchestrator._run_dir(repo_root, run_id)
            self.assertTrue(rdir.is_dir())
            self.assertEqual((rdir / "pid").read_text(encoding="utf-8"), str(os.getpid()))
            self.assertTrue((rdir / "started").read_text(encoding="utf-8"))

    def test_write_run_metadata_is_best_effort_on_bad_path(self):
        # A non-existent parent deep under a file should not raise.
        with tempfile.TemporaryDirectory() as repo_root:
            bad_path = os.path.join(repo_root, "not-a-dir", "runs")
            with patch.object(orchestrator.Path, "mkdir", side_effect=OSError("boom")):
                # _write_run_metadata prints a warning and swallows the error.
                orchestrator._write_run_metadata(bad_path, "run-x")


class TestOutputRedirection(unittest.TestCase):
    def test_redirect_output_appends_to_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_file = os.path.join(tmp, "output.log")
            Path(log_file).write_text("existing\n", encoding="utf-8")
            old_stdout_fd = os.dup(sys.stdout.fileno())
            old_stderr_fd = os.dup(sys.stderr.fileno())
            try:
                orchestrator._redirect_output(log_file)
                print("after redirection")
                sys.stderr.write("stderr line\n")
                sys.stdout.flush()
                sys.stderr.flush()
            finally:
                os.dup2(old_stdout_fd, sys.stdout.fileno())
                os.dup2(old_stderr_fd, sys.stderr.fileno())
                os.close(old_stdout_fd)
                os.close(old_stderr_fd)
                if hasattr(sys, "_aet_run_log"):
                    del sys._aet_run_log
            content = Path(log_file).read_text(encoding="utf-8")
            self.assertIn("existing", content)
            self.assertIn("after redirection", content)
            self.assertIn("stderr line", content)

    def test_redirect_output_noop_when_log_file_absent(self):
        old_stdout_fd = os.dup(sys.stdout.fileno())
        old_stderr_fd = os.dup(sys.stderr.fileno())
        try:
            orchestrator._redirect_output(None)
            self.assertEqual(os.fstat(sys.stdout.fileno()).st_ino, os.fstat(old_stdout_fd).st_ino)
            self.assertEqual(os.fstat(sys.stderr.fileno()).st_ino, os.fstat(old_stderr_fd).st_ino)
        finally:
            os.close(old_stdout_fd)
            os.close(old_stderr_fd)


class TestArgumentParser(unittest.TestCase):
    def test_parser_accepts_run_id_and_log_file(self):
        args = orchestrator.parse_args(
            [
                "--plan-file",
                "docs/plans/x.md",
                "--run-id",
                "run-123",
                "--log-file",
                "/tmp/run.log",
            ]
        )
        self.assertEqual(args.run_id, "run-123")
        self.assertEqual(args.log_file, "/tmp/run.log")


class TestMainUsesRunId(unittest.TestCase):
    def test_main_redirects_output_and_writes_metadata_when_run_id_given(self):
        with tempfile.TemporaryDirectory() as repo_root:
            plan_file = Path(repo_root, "docs", "plans", "demo.md")
            plan_file.parent.mkdir(parents=True, exist_ok=True)
            plan_file.write_text(
                "---\nid: demo\n---\n\n# Demo\n\n_Stage: implemented_\n",
                encoding="utf-8",
            )
            run_id = "run-main-test"
            log_file = os.path.join(repo_root, ".agents", "runs", run_id, "output.log")

            with patch.object(
                orchestrator, "resolve_cli_adapter", return_value=_FAKE_ADAPTER
            ):
                with patch.object(
                    orchestrator, "run_single", return_value=0
                ) as mock_run:
                    with patch.object(
                        orchestrator, "_redirect_output"
                    ) as mock_redirect:
                        with patch.object(
                            orchestrator, "_write_run_metadata"
                        ) as mock_metadata:
                            with patch.dict(
                                os.environ,
                                {"AET_EXECUTION_MODE": "unattended"},
                                clear=False,
                            ):
                                rc = orchestrator.main(
                                    [
                                        "--plan-file",
                                        str(plan_file),
                                        "--repo-root",
                                        repo_root,
                                        "--run-id",
                                        run_id,
                                        "--log-file",
                                        log_file,
                                        "--cli-bin",
                                        "echo",
                                    ]
                                )

            self.assertEqual(rc, 0)
            mock_run.assert_called_once()
            mock_redirect.assert_called_once_with(log_file)
            mock_metadata.assert_called_once_with(repo_root, run_id)


class TestRunLoggerInheritsRunId(unittest.TestCase):
    def test_run_single_uses_args_run_id(self):
        with tempfile.TemporaryDirectory() as archive_dir:
            with tempfile.TemporaryDirectory() as repo_root:
                # git-refs backend requires the queue to live inside a git repository.
                subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
                subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
                subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_root, check=True)

                plan_file = Path(repo_root, "docs", "plans", "demo.md")
                plan_file.parent.mkdir(parents=True, exist_ok=True)
                plan_file.write_text(
                    "---\nid: demo\n---\n\n# Demo\n\n_Stage: implemented_\n",
                    encoding="utf-8",
                )
                args = orchestrator.parse_args(
                    [
                        "--plan-file",
                        str(plan_file),
                        "--repo-root",
                        repo_root,
                        "--run-id",
                        "run-inherited",
                        "--cli-bin",
                        "echo",
                    ]
                )
                with patch.dict(
                    os.environ,
                    {"AET_EXECUTION_MODE": "unattended", "AET_TELEMETRY_ARCHIVE_DIR": archive_dir},
                    clear=True,
                ):
                    with patch.object(orchestrator, "process_task", return_value=True):
                        orchestrator.run_single(args, None)

                log_file = Path(archive_dir)
                run_dirs = list(log_file.rglob("run-inherited"))
                self.assertTrue(run_dirs, "telemetry run dir should use the supplied run_id")


class TestMainWritesReturncode(unittest.TestCase):
    def test_main_persists_returncode_for_detached_run(self):
        with tempfile.TemporaryDirectory() as repo_root:
            with patch.object(
                orchestrator, "resolve_cli_adapter", return_value=_FAKE_ADAPTER
            ):
                with patch.object(
                    orchestrator, "run_batch", return_value=42
                ) as mock_run:
                    rc = orchestrator.main(
                        [
                            "--queue-file",
                            os.path.join(repo_root, ".agents", "aet-queue"),
                            "--repo-root",
                            repo_root,
                            "--run-id",
                            "run-returncode",
                        ]
                    )

            self.assertEqual(rc, 42)
            mock_run.assert_called_once()
            rc_file = (
                Path(repo_root) / ".agents" / "runs" / "run-returncode" / "returncode"
            )
            self.assertTrue(rc_file.is_file())
            self.assertEqual(rc_file.read_text(encoding="utf-8"), "42")


class TestDetachedSpawnReturnsPromptly(unittest.TestCase):
    """Batch `run` never blocks on the detached child process (rid-01)."""

    def test_run_returns_without_waiting_for_child(self):
        proc = MagicMock()
        proc.pid = 4321

        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                # Dispatch resolves the adapter before spawning; pin it so this
                # test does not depend on which agent CLI runs the suite.
                with patch.dict(os.environ, {"AET_CLI_BIN": "claude"}):
                    with patch.object(cli_main.subprocess, "Popen", return_value=proc):
                        rc = cli_main.app(["run"], standalone_mode=False)
            finally:
                os.chdir(old_cwd)

        self.assertEqual(rc, 0)
        proc.wait.assert_not_called()
        proc.communicate.assert_not_called()


class TestFollowerWaitsSilently(unittest.TestCase):
    """The non-streaming follower returns the run's exit code without echoing logs."""

    def test_follow_completed_run_returns_rc_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / ".agents" / "runs" / "run-done"
            run_dir.mkdir(parents=True)
            (run_dir / "output.log").write_text("hello log\n", encoding="utf-8")
            (run_dir / "pid").write_text("12345", encoding="utf-8")
            (run_dir / "returncode").write_text("7", encoding="utf-8")

            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with patch.object(cli_main.typer, "echo") as echo_mock:
                    rc = cli_main.app(["run", "--follow", "run-done"], standalone_mode=False)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(rc, 7)
            self.assertNotIn("hello log\n", [call.args[0] for call in echo_mock.call_args_list])

    def test_follow_live_run_waits_for_returncode(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / ".agents" / "runs" / "run-live"
            run_dir.mkdir(parents=True)
            (run_dir / "output.log").write_text("live log\n", encoding="utf-8")
            child = _start_child_runner(run_dir, 13, delay=0.2)
            try:
                (run_dir / "pid").write_text(str(child.pid), encoding="utf-8")
                old_cwd = os.getcwd()
                try:
                    os.chdir(tmp)
                    started = time.monotonic()
                    with patch.object(cli_main.typer, "echo") as echo_mock:
                        rc = cli_main.app(["run", "--follow", "run-live"], standalone_mode=False)
                    elapsed = time.monotonic() - started
                finally:
                    os.chdir(old_cwd)
            finally:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()

            self.assertEqual(rc, 13)
            self.assertGreaterEqual(elapsed, 0.15)
            self.assertNotIn("live log\n", [call.args[0] for call in echo_mock.call_args_list])

    def test_follow_missing_pid_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / ".agents" / "runs" / "run-no-pid"
            run_dir.mkdir(parents=True)
            (run_dir / "output.log").write_text("orphaned log\n", encoding="utf-8")

            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with patch.object(cli_main.typer, "echo") as echo_mock:
                    rc = cli_main.app(["run", "--follow", "run-no-pid"], standalone_mode=False)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(rc, 1)
            self.assertNotIn("orphaned log\n", [call.args[0] for call in echo_mock.call_args_list])
            diagnostics = " ".join(str(call.args[0]) for call in echo_mock.call_args_list if call.kwargs.get("err"))
            self.assertIn("no process", diagnostics)

    def test_follow_unparseable_pid_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / ".agents" / "runs" / "run-bad-pid"
            run_dir.mkdir(parents=True)
            (run_dir / "pid").write_text("not-a-number", encoding="utf-8")

            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                rc = cli_main.app(["run", "--follow", "run-bad-pid"], standalone_mode=False)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(rc, 1)


def _stage_record(
    run_id: str,
    task_id: str,
    stage: str,
    exit_code: int,
    *,
    duration_seconds: float = 5.0,
    output_excerpt: str | None = None,
    actual_stages: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "stage",
        "run_id": run_id,
        "task_id": task_id,
        "plan_file": "docs/plans/x.md",
        "stage": stage,
        "actual_stages": actual_stages or [stage],
        "start_time": "2026-07-27T00:00:00Z",
        "end_time": "2026-07-27T00:00:05Z",
        "duration_seconds": duration_seconds,
        "exit_code": exit_code,
        "result": "success" if exit_code == 0 else "failure",
        "output_excerpt": output_excerpt,
    }


class TestCompletionReport(unittest.TestCase):
    def _archive_run_dir(
        self,
        archive_dir: Path,
        run_id: str,
        project_slug: str,
        records: list[dict[str, Any]],
        output_log: str = "",
        local_run_root: Path | None = None,
    ) -> Path:
        date = "2026-07-27"
        run_dir = archive_dir / project_slug / date / run_id
        run_dir.mkdir(parents=True)
        # Records are grouped by task_id so the follower walks them like real telemetry.
        by_task: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_task.setdefault(record["task_id"], []).append(record)
        for task_id, task_records in by_task.items():
            jsonl = "\n".join(json.dumps(r) for r in task_records) + "\n"
            (run_dir / f"{task_id}.jsonl").write_text(jsonl, encoding="utf-8")
        (run_dir / "output.log").write_text(output_log, encoding="utf-8")
        if local_run_root is not None:
            local_run_dir = local_run_root / ".agents" / "runs" / run_id
            local_run_dir.mkdir(parents=True, exist_ok=True)
            (local_run_dir / "telemetry_dir").write_text(str(run_dir), encoding="utf-8")
        return run_dir

    def test_report_line_count_is_independent_of_log_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = Path(tmp) / "archive"
            project_slug = "test-project"
            run_id = "run-size-test"
            large_run_id = "run-large-log"
            local_root = Path(tmp) / "repo"
            small_records = [
                _stage_record(run_id, "t-1", "plan-approved", 0, duration_seconds=1.2),
                _stage_record(run_id, "t-1", "implemented", 0, duration_seconds=2.3),
            ]
            large_records = [
                _stage_record(large_run_id, "t-1", "plan-approved", 0, duration_seconds=1.2),
                _stage_record(large_run_id, "t-1", "implemented", 0, duration_seconds=2.3),
            ]
            self._archive_run_dir(
                archive_dir,
                run_id,
                project_slug,
                small_records,
                output_log="small\n",
                local_run_root=local_root,
            )
            self._archive_run_dir(
                archive_dir,
                large_run_id,
                project_slug,
                large_records,
                output_log="big line\n" * 10000,
                local_run_root=local_root,
            )

            old_cwd = os.getcwd()
            try:
                os.chdir(local_root)
                small_report = cli_main._completion_report_lines(run_id, 0)
                large_report = cli_main._completion_report_lines(large_run_id, 0)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(len(small_report), len(large_report))
            self.assertIn("Result: success (exit 0)", small_report)
            report_text = "\n".join(small_report)
            self.assertIn("plan-approved: success", report_text)
            self.assertIn("implemented: success", report_text)

    def test_failure_report_includes_bounded_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = Path(tmp) / "archive"
            project_slug = "test-project"
            run_id = "run-fail-test"
            local_root = Path(tmp) / "repo"
            long_excerpt = "\n".join(f"line {i}" for i in range(50))
            records = [
                _stage_record(run_id, "t-1", "plan-approved", 0),
                _stage_record(
                    run_id,
                    "t-1",
                    "qa-complete",
                    1,
                    output_excerpt=long_excerpt,
                ),
            ]
            self._archive_run_dir(
                archive_dir, run_id, project_slug, records, local_run_root=local_root
            )

            old_cwd = os.getcwd()
            try:
                os.chdir(local_root)
                report = cli_main._completion_report_lines(run_id, 1)
            finally:
                os.chdir(old_cwd)

            self.assertIn("Result: failure (exit 1)", report)
            cap = telemetry.COMPLETION_REPORT_EXCERPT_LINES
            self.assertIn(f"--- Output excerpt (last {cap} lines) ---", report)
            # The excerpt is capped at the configured line count.
            excerpt_start = report.index(f"--- Output excerpt (last {cap} lines) ---") + 1
            excerpt_end = report.index("---", excerpt_start)
            excerpt_lines = report[excerpt_start:excerpt_end]
            self.assertEqual(len(excerpt_lines), cap)
            self.assertEqual(excerpt_lines[0], f"line {50 - cap}")
            self.assertEqual(excerpt_lines[-1], "line 49")


if __name__ == "__main__":
    unittest.main()
