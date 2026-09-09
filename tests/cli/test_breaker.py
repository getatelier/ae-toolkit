"""Unit tests for `aet breaker` CLI commands (`show` and `reset`)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from aet import breaker
from aet.cli.breaker import app
from tests.state._helpers import init_git_repo


class TestBreakerShow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_root = Path(self._tmp.name) / "repo"
        init_git_repo(self.repo_root)
        self.runner = CliRunner()
        self._cwd = os.getcwd()
        os.chdir(self.repo_root)
        self.addCleanup(os.chdir, self._cwd)

    def test_show_clear_human_output(self):
        result = self.runner.invoke(app, ["show"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Circuit breaker is clear", result.output)
        self.assertNotIn("CIRCUIT BREAKER TRIPPED", result.output)

    def test_show_tracked_healthy_human_output(self):
        store = breaker.BreakerStore(self.repo_root)
        store.save({"sig_timeout": {"t1", "t2"}})

        result = self.runner.invoke(app, ["show"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("sig_timeout", result.output)
        self.assertIn("2", result.output)
        self.assertNotIn("CIRCUIT BREAKER TRIPPED", result.output)

    def test_show_tripped_human_output(self):
        store = breaker.BreakerStore(self.repo_root)
        store.save({"sig_timeout": {"t1", "t2", "t3"}})

        result = self.runner.invoke(app, ["show"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("CIRCUIT BREAKER TRIPPED", result.output)
        self.assertIn("sig_timeout", result.output)
        self.assertIn("3 tasks", result.output)
        self.assertIn("aet breaker reset", result.output)

    def test_show_json_clear(self):
        result = self.runner.invoke(app, ["show", "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output)
        self.assertFalse(data["tripped"])
        self.assertIsNone(data["tripped_signature"])
        self.assertEqual(data["threshold"], breaker.SYSTEMIC_BREAKER_THRESHOLD)
        self.assertEqual(data["signatures"], [])

    def test_show_json_tracked_healthy(self):
        store = breaker.BreakerStore(self.repo_root)
        store.save({"sig_test": {"t1", "t2"}})

        result = self.runner.invoke(app, ["show", "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output)
        self.assertFalse(data["tripped"])
        self.assertIsNone(data["tripped_signature"])
        self.assertEqual(len(data["signatures"]), 1)
        sig_info = data["signatures"][0]
        self.assertEqual(sig_info["signature"], "sig_test")
        self.assertEqual(sig_info["count"], 2)
        self.assertEqual(sorted(sig_info["tasks"]), ["t1", "t2"])
        self.assertFalse(sig_info["tripped"])

    def test_show_json_tripped(self):
        store = breaker.BreakerStore(self.repo_root)
        store.save({"sig_err": {"t1", "t2", "t3"}})

        result = self.runner.invoke(app, ["show", "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output)
        self.assertTrue(data["tripped"])
        self.assertEqual(data["tripped_signature"], "sig_err")
        self.assertEqual(len(data["signatures"]), 1)
        sig_info = data["signatures"][0]
        self.assertEqual(sig_info["signature"], "sig_err")
        self.assertEqual(sig_info["count"], 3)
        self.assertEqual(sorted(sig_info["tasks"]), ["t1", "t2", "t3"])
        self.assertTrue(sig_info["tripped"])


class TestBreakerReset(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_root = Path(self._tmp.name) / "repo"
        init_git_repo(self.repo_root)
        self.runner = CliRunner()
        self._cwd = os.getcwd()
        os.chdir(self.repo_root)
        self.addCleanup(os.chdir, self._cwd)

    def test_reset_with_force_flag_clears_tripped_breaker(self):
        store = breaker.BreakerStore(self.repo_root)
        store.save({"sig_fail": {"t1", "t2", "t3"}})
        self.assertIsNotNone(breaker.systemic_tripped(store.load()))

        result = self.runner.invoke(app, ["reset", "--force"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Circuit breaker reset", result.output)
        self.assertEqual(store.load(), {})

    def test_reset_with_yes_flag(self):
        store = breaker.BreakerStore(self.repo_root)
        store.save({"sig_fail": {"t1", "t2", "t3"}})

        result = self.runner.invoke(app, ["reset", "-y"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Circuit breaker reset", result.output)
        self.assertEqual(store.load(), {})

    def test_reset_when_already_clear(self):
        store = breaker.BreakerStore(self.repo_root)
        self.assertEqual(store.load(), {})

        result = self.runner.invoke(app, ["reset", "--force"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("already clear", result.output)

    def test_reset_interactive_confirmed(self):
        store = breaker.BreakerStore(self.repo_root)
        store.save({"sig_fail": {"t1", "t2", "t3"}})

        result = self.runner.invoke(app, ["reset"], input="y\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Circuit breaker reset", result.output)
        self.assertEqual(store.load(), {})

    def test_reset_interactive_aborted(self):
        store = breaker.BreakerStore(self.repo_root)
        store.save({"sig_fail": {"t1", "t2", "t3"}})

        result = self.runner.invoke(app, ["reset"], input="n\n")
        self.assertNotEqual(result.exit_code, 0)
        # Breaker should still have data
        self.assertIn("sig_fail", store.load())
