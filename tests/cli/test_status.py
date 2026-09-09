"""Unit tests for `aet status` circuit breaker visibility and last-run health."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from aet import breaker, telemetry
from aet.cli import status
from tests.state._helpers import init_git_repo, seed_git_queue


class TestStatusCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_root = Path(self._tmp.name) / "repo"
        init_git_repo(self.repo_root)

        self.queue_path, self.history_path = seed_git_queue(
            self.repo_root,
            [
                {
                    "id": "t1",
                    "state": "ready",
                    "title": "task one",
                    "branch": "t1",
                }
            ],
        )
        self.plans_dir = self.repo_root / "docs" / "plans"
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self._cwd = os.getcwd()
        os.chdir(self.repo_root)
        self.addCleanup(os.chdir, self._cwd)

    def _status_output(self, json_output: bool = False) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            status._run(
                str(self.queue_path),
                str(self.history_path),
                self.plans_dir,
                json_output,
            )
        return buf.getvalue()

    def test_status_shows_no_breaker_warning_when_healthy(self):
        output = self._status_output()
        self.assertNotIn("CIRCUIT BREAKER TRIPPED", output)
        self.assertNotIn("Systemic circuit breaker", output)

    def test_status_shows_breaker_warning_when_tripped(self):
        breaker_store = breaker.BreakerStore(self.repo_root)
        tally = {
            "sig_timeout": {"t1", "t2", "t3"},
        }
        breaker_store.save(tally)

        output = self._status_output()
        self.assertIn("CIRCUIT BREAKER TRIPPED", output)
        self.assertIn("sig_timeout", output)
        self.assertIn("3 tasks", output)
        self.assertIn("aet breaker reset", output)

    def test_status_json_projection_breaker_healthy(self):
        output = self._status_output(json_output=True)
        data = json.loads(output)
        self.assertIn("circuit_breaker", data)
        self.assertFalse(data["circuit_breaker"]["tripped"])
        self.assertIsNone(data["circuit_breaker"]["signature"])
        self.assertEqual(data["circuit_breaker"]["affected_tasks"], [])

    def test_status_json_projection_breaker_tripped(self):
        breaker_store = breaker.BreakerStore(self.repo_root)
        tally = {
            "sig_timeout": {"t1", "t2", "t3"},
        }
        breaker_store.save(tally)

        output = self._status_output(json_output=True)
        data = json.loads(output)
        self.assertIn("circuit_breaker", data)
        self.assertTrue(data["circuit_breaker"]["tripped"])
        self.assertEqual(data["circuit_breaker"]["signature"], "sig_timeout")
        self.assertEqual(sorted(data["circuit_breaker"]["affected_tasks"]), ["t1", "t2", "t3"])
        self.assertEqual(data["circuit_breaker"]["count"], 3)
        self.assertEqual(data["circuit_breaker"]["remedy"], "aet breaker reset")


class TestStatusLastRunHealth(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_root = Path(self._tmp.name) / "repo"
        init_git_repo(self.repo_root)

        self.queue_path, self.history_path = seed_git_queue(
            self.repo_root,
            [
                {
                    "id": "t1",
                    "state": "ready",
                    "title": "task one",
                    "branch": "t1",
                }
            ],
        )
        self.plans_dir = self.repo_root / "docs" / "plans"
        self.plans_dir.mkdir(parents=True, exist_ok=True)

        self.telemetry_dir = Path(self._tmp.name) / "telemetry"
        self._orig_telemetry_env = os.environ.get("AET_TELEMETRY_ARCHIVE_DIR")
        os.environ["AET_TELEMETRY_ARCHIVE_DIR"] = str(self.telemetry_dir)
        self.addCleanup(self._cleanup_telemetry_env)

        self._cwd = os.getcwd()
        os.chdir(self.repo_root)
        self.addCleanup(os.chdir, self._cwd)

    def _cleanup_telemetry_env(self):
        if self._orig_telemetry_env is None:
            os.environ.pop("AET_TELEMETRY_ARCHIVE_DIR", None)
        else:
            os.environ["AET_TELEMETRY_ARCHIVE_DIR"] = self._orig_telemetry_env

    def _status_output(self, json_output: bool = False) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            status._run(
                str(self.queue_path),
                str(self.history_path),
                self.plans_dir,
                json_output,
            )
        return buf.getvalue()

    def test_status_no_last_run_when_telemetry_empty(self):
        output = self._status_output()
        self.assertIn("No active detached runs.", output)
        self.assertNotIn("Previous run failed", output)

        json_out = self._status_output(json_output=True)
        data = json.loads(json_out)
        self.assertIsNone(data.get("last_run"))

    def test_status_shows_previous_run_failure_when_telemetry_has_failure(self):
        logger = telemetry.RunLogger(self.repo_root, run_id="run-failed-123")
        start = "2026-09-08T12:00:00Z"
        end = "2026-09-08T12:05:00Z"
        summary = telemetry.run_summary_record(
            run_id="run-failed-123",
            start_time=start,
            end_time=end,
            tasks_spawned=1,
            tasks_succeeded=0,
            tasks_failed=1,
            outcome="failure",
            exit_code=1,
            task_ids=["t1"],
        )
        logger.write_last_run(summary)

        output = self._status_output()
        self.assertIn("No active detached runs.", output)
        self.assertIn("Previous run failed", output)
        self.assertIn("run-failed-123", output)
        self.assertIn("Exit code: 1", output)

        json_out = self._status_output(json_output=True)
        data = json.loads(json_out)
        self.assertIsNotNone(data.get("last_run"))
        self.assertEqual(data["last_run"]["run_id"], "run-failed-123")
        self.assertEqual(data["last_run"]["outcome"], "failure")
        self.assertEqual(data["last_run"]["exit_code"], 1)

    def test_status_previous_run_success_not_reported_as_failure(self):
        logger = telemetry.RunLogger(self.repo_root, run_id="run-success-456")
        start = "2026-09-08T12:00:00Z"
        end = "2026-09-08T12:05:00Z"
        summary = telemetry.run_summary_record(
            run_id="run-success-456",
            start_time=start,
            end_time=end,
            tasks_spawned=1,
            tasks_succeeded=1,
            tasks_failed=0,
            outcome="success",
            exit_code=0,
            task_ids=["t1"],
        )
        logger.write_last_run(summary)

        output = self._status_output()
        self.assertIn("No active detached runs.", output)
        self.assertNotIn("Previous run failed", output)

        json_out = self._status_output(json_output=True)
        data = json.loads(json_out)
        self.assertIsNotNone(data.get("last_run"))
        self.assertEqual(data["last_run"]["outcome"], "success")
        self.assertEqual(data["last_run"]["exit_code"], 0)

    def test_status_extracts_error_summary_from_stage_records(self):
        logger = telemetry.RunLogger(self.repo_root, run_id="run-diag-789")
        start = "2026-09-08T12:00:00Z"
        end = "2026-09-08T12:05:00Z"

        stg = telemetry.stage_record(
            run_id="run-diag-789",
            task_id="t1",
            plan_file="docs/plans/t1.md",
            stage="implemented",
            agent_cli="gemini",
            isolation_level="standard",
            start_time=start,
            end_time=end,
            exit_code=1,
            failure_class="syntax_error",
            output_excerpt="SyntaxError: invalid syntax in foo.py",
        )
        logger.append_record(stg, "t1")

        summary = telemetry.run_summary_record(
            run_id="run-diag-789",
            start_time=start,
            end_time=end,
            tasks_spawned=1,
            tasks_succeeded=0,
            tasks_failed=1,
            outcome="failure",
            exit_code=1,
            task_ids=["t1"],
        )
        logger.write_last_run(summary)

        output = self._status_output()
        self.assertIn("Previous run failed", output)
        self.assertIn("run-diag-789", output)

        json_out = self._status_output(json_output=True)
        data = json.loads(json_out)
        self.assertIsNotNone(data.get("last_run"))
        self.assertIn("syntax", data["last_run"]["summary"].lower())


if __name__ == "__main__":
    unittest.main()
