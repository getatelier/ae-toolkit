"""Tests for the consolidated Typer CLI dispatcher (src/aet/cli/main.py).

The legacy ``SUBCOMMANDS`` table and os.exec forwarding are gone. These tests
invoke the single Typer ``app`` directly via ``typer.testing.CliRunner`` and
verify that commands route to the correct noun groups and top-level handlers.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.cli._helpers import git, run_typer

# Import the module object (not the ``main`` function exposed by ``aet.cli``).
aet = importlib.import_module("aet.cli.main")


class TestAetGroupRouting(unittest.TestCase):
    """Top-level commands and noun groups resolve and expose their help."""

    def test_status_routes_to_status_command(self):
        result = run_typer(aet.app, ["status", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Show work queue status", result.output)

    def test_state_routes_to_state_group(self):
        result = run_typer(aet.app, ["state", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("audit", result.output)

    def test_sprint_routes_to_sprint_group(self):
        result = run_typer(aet.app, ["sprint", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("add", result.output)

    def test_backlog_routes_to_backlog_group(self):
        result = run_typer(aet.app, ["backlog", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("add", result.output)

    def test_reconcile_routes_to_reconcile_command(self):
        result = run_typer(aet.app, ["reconcile", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Reconcile", result.output)

    def test_ship_routes_to_ship_group(self):
        result = run_typer(aet.app, ["ship", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("open", result.output)
        self.assertIn("record-merge", result.output)

    def test_retro_routes_to_retro_command(self):
        result = run_typer(aet.app, ["retro", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("retro", result.output.lower())

    def test_configure_routes_to_command(self):
        result = run_typer(aet.app, ["configure", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("integration-mode", result.output.lower())
        self.assertNotIn("task-backend", result.output.lower())

    def test_gate_routes_to_gate_group(self):
        result = run_typer(aet.app, ["gate", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("submit", result.output)
        self.assertIn("review", result.output)

    def test_queue_group_exposes_sync(self):
        """`aet queue` is the new home for the retired `aet sync` command."""
        result = run_typer(aet.app, ["queue", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("sync", result.output)

    def test_plans_group_exposes_lint(self):
        result = run_typer(aet.app, ["plans", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("lint", result.output)


class TestRunMapping(unittest.TestCase):
    """run/run-one map user flags to the documented orchestrator argv."""

    def _expected_run_argv(self, *extra):
        return [sys.executable, str(aet._orchestrator_path()), *extra]

    def _capture_spawn(self, argv, run_id="run-detached-abc"):
        """Run ``app`` with detached Popen captured; return (rc, cmd, kwargs)."""
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            mock = MagicMock()
            mock.pid = 12345
            return mock

        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with patch.object(aet.subprocess, "Popen", side_effect=fake_popen):
                    with patch.object(aet, "_generate_run_id", return_value=run_id):
                        with patch.object(aet, "_wait_for_run", return_value=0):
                            rc = aet.app(argv, standalone_mode=False)
            finally:
                os.chdir(old_cwd)
        return rc, captured.get("cmd"), captured.get("kwargs")

    def test_run_rejects_foreground_flag(self):
        """`aet run --foreground` is rejected as an unknown option."""
        # Guard the exec/spawn paths so a regression to the old behavior
        # cannot replace or outlive this test process.
        with patch.object(aet.os, "execvp", side_effect=SystemExit(0)):
            with patch.object(aet.subprocess, "Popen"):
                result = run_typer(aet.app, ["run", "--foreground"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("No such option", result.output)

    def test_run_one_rejects_foreground_flag(self):
        """`aet run-one --foreground <plan>` is rejected as an unknown option."""
        with patch.object(aet.os, "execvp", side_effect=SystemExit(0)):
            with patch.object(aet.subprocess, "Popen"):
                result = run_typer(aet.app, ["run-one", "docs/plans/x.md", "--foreground"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("No such option", result.output)

    def test_run_rejects_tuning_flags(self):
        """`aet run` rejects --isolation and --stall-timeout; --max-jobs is retained."""
        for flag_args in (["--isolation", "full"], ["--stall-timeout", "60"]):
            with self.subTest(flag=flag_args[0]):
                with patch.object(aet.subprocess, "Popen"):
                    result = run_typer(aet.app, ["run", *flag_args])
                self.assertEqual(result.exit_code, 2)
                self.assertIn("No such option", result.output)

    def test_run_one_rejects_tuning_flags(self):
        """`aet run-one` rejects --max-jobs, --isolation, and --stall-timeout."""
        for flag_args in (["--max-jobs", "2"], ["--isolation", "full"], ["--stall-timeout", "60"]):
            with self.subTest(flag=flag_args[0]):
                with patch.object(aet.subprocess, "Popen"):
                    result = run_typer(aet.app, ["run-one", "docs/plans/x.md", *flag_args])
                self.assertEqual(result.exit_code, 2)
                self.assertIn("No such option", result.output)

    def test_run_forwards_retained_flags_detached(self):
        """`aet run --base/--on-failure/--task-timeout/--cli-bin/--max-jobs` forwards all five."""
        rc, cmd, _ = self._capture_spawn(
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
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(Path(cmd[0]), Path(sys.executable))
        self.assertEqual(cmd[1], str(aet._orchestrator_path()))
        self.assertIn("--queue-file", cmd)
        for flag, value in (
            ("--base", "feat/x"),
            ("--on-failure", "halt"),
            ("--task-timeout", "900"),
            ("--cli-bin", "/bin/kimi"),
            ("--max-jobs", "2"),
        ):
            self.assertIn(flag, cmd)
            self.assertEqual(cmd[cmd.index(flag) + 1], value)
        self.assertEqual(cmd[cmd.index("--isolation") + 1], "standard")
        self.assertNotIn("--stall-timeout", cmd)

    def test_run_one_forwards_retained_flags_detached(self):
        """`aet run-one <plan> <flags>` maps the plan positional and forwards flags."""
        rc, cmd, _ = self._capture_spawn(
            ["run-one", "docs/plans/FEAT-001.md", "--on-failure", "halt", "--cli-bin", "/bin/kimi"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(cmd[1], str(aet._orchestrator_path()))
        self.assertIn("--plan-file", cmd)
        self.assertIn("docs/plans/FEAT-001.md", cmd)
        self.assertIn("--on-failure", cmd)
        self.assertIn("--cli-bin", cmd)
        self.assertNotIn("--stall-timeout", cmd)

    def test_run_one_without_plan_exits_2(self):
        """`aet run-one` without a plan file exits 2 without spawning."""
        result = run_typer(aet.app, ["run-one"])
        self.assertEqual(result.exit_code, 2)

    def test_run_spawns_detached_by_default(self):
        """`aet run` with no flags spawns the orchestrator detached."""
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            mock = MagicMock()
            mock.pid = 12345
            return mock

        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with patch.dict(os.environ, {"AET_CLI_BIN": "claude"}):
                    with patch.object(
                        aet.subprocess, "Popen", side_effect=fake_popen
                    ) as popen_mock:
                        with patch.object(
                            aet, "_generate_run_id", return_value="run-detached-abc"
                        ):
                            rc = aet.app(["run"], standalone_mode=False)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(rc, 0)
            popen_mock.assert_called_once()
            self.assertEqual(captured["kwargs"]["start_new_session"], True)
            self.assertIn("--run-id", captured["cmd"])
            self.assertIn("run-detached-abc", captured["cmd"])
            self.assertIn("--log-file", captured["cmd"])
            # The adapter is resolved in-session and pinned for the detached
            # child, which is reparented away from the calling agent.
            self.assertEqual(captured["cmd"][captured["cmd"].index("--cli-bin") + 1], "claude")


class TestAetErrorPaths(unittest.TestCase):
    """Unknown subcommands and missing arguments fail with clear errors."""

    def test_unknown_subcommand_exits_2(self):
        """An unknown subcommand exits 2 with a Typer error."""
        result = run_typer(aet.app, ["nope"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("No such command", result.output)

    def test_no_subcommand_exits_2_with_usage(self):
        """Bare ``aet`` prints usage and exits 2."""
        result = run_typer(aet.app, [])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Usage:", result.output)


class TestAetIntegration(unittest.TestCase):
    """Subprocess integration: the real dispatcher reaches the target handler."""

    def test_status_via_real_subprocess(self):
        """``aet status`` runs the real status handler against a temp queue."""
        with tempfile.TemporaryDirectory() as tmp:
            git(["init"], tmp)
            git(["config", "user.email", "test@example.com"], tmp)
            git(["config", "user.name", "Test"], tmp)
            queue_file = Path(tmp) / ".agents" / "aet-queue"
            queue_file.parent.mkdir()
            history_file = Path(tmp) / ".agents" / "work-history.jsonl"
            plans_dir = Path(tmp) / "plans"
            plans_dir.mkdir()
            env = {**os.environ}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aet.cli.main",
                    "status",
                    "--queue-file",
                    str(queue_file),
                    "--history-file",
                    str(history_file),
                    "--plans-dir",
                    str(plans_dir),
                ],
                capture_output=True,
                text=True,
                cwd=tmp,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


class TestPackageEntryPoint(unittest.TestCase):
    """The installed console script resolves to the same Typer interface."""

    def test_aet_cli_re_exports_main_and_app(self):
        """aet.cli re-exports the dispatcher entry point and Typer app."""
        import aet.cli
        main_module = importlib.import_module("aet.cli.main")

        self.assertTrue(callable(aet.cli.main))
        self.assertIs(aet.cli.app, main_module.app)

    def test_aet_cli_subprocess_entry_point_runs_dispatcher(self):
        """The module runs as ``python -m aet.cli.main`` and prints usage."""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parents[2] / "src")
        result = subprocess.run(
            [sys.executable, "-m", "aet.cli.main"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Usage:", result.stdout + result.stderr)
        self.assertIn("Agentic Engineering Toolkit", result.stdout + result.stderr)

    def test_module_invocation_propagates_subcommand_exit_code(self):
        """``python -m`` dispatches a real subcommand and returns its status.

        Dropping the ``__main__`` block leaves the module importable and exits
        0 without dispatching, so a caller checking only "did it crash" sees a
        pass. ``make validate`` gates on ``python -m aet.cli.main plans lint``
        (Makefile), so a silent 0 disables that gate. Assert on a non-zero
        status that only a real dispatch can produce.
        """
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parents[2] / "src")
        result = subprocess.run(
            [sys.executable, "-m", "aet.cli.main", "no-such-command"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("No such command", result.stdout + result.stderr)

    def test_console_script_dispatches(self):
        """The installed ``aet`` console script is a working entry point.

        ADR-041 makes this the only supported way to invoke the tool, but the
        packaging test only asserts the entry point is *declared*. Execute it.
        """
        console_script = Path(sys.executable).parent / "aet"
        self.assertTrue(
            console_script.exists(), f"console script missing at {console_script}"
        )
        result = subprocess.run(
            [str(console_script), "no-such-command"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("No such command", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
