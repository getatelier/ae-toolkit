"""Tests for noun-scoped command groups and the retired top-level ``add``."""

from __future__ import annotations

import importlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from aet.backends.factory import create_backend
from tests.cli._helpers import git, make_plan, run_typer

# Module objects (not the functions re-exported by ``aet.cli``).
sprint = importlib.import_module("aet.cli.sprint")
backlog = importlib.import_module("aet.cli.backlog")
aet = importlib.import_module("aet.cli.main")


class TestSprintAdd(unittest.TestCase):
    def _queue_paths(self, tmp_path: Path):
        """Return queue and history paths inside a git-backed repo."""
        queue_file = str(tmp_path / ".agents" / "aet-queue")
        history_file = str(tmp_path / ".agents" / "work-history.jsonl")
        return queue_file, history_file

    def test_sprint_add_promotes_without_committing(self):
        """sprint add sets status: queued and adds the task without committing."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            git(["init"], tmp)
            git(["config", "user.email", "test@example.com"], tmp)
            git(["config", "user.name", "Test"], tmp)

            plans_dir = tmp_path / "docs" / "plans"
            plans_dir.mkdir(parents=True)
            prds_dir = tmp_path / "docs" / "prds"
            prds_dir.mkdir(parents=True)
            (prds_dir / "default-prd.md").write_text(
                "# Default PRD\n\n## Requirements\n- **R-1**: default requirement\n",
                encoding="utf-8",
            )
            plan = make_plan(plans_dir, "feat-001.md")
            git(["add", "-A"], tmp)
            git(["commit", "-m", "initial"], tmp)

            queue_file, history_file = self._queue_paths(tmp_path)

            mock_projections = MagicMock()

            with patch.object(sprint, "resolve_projections", return_value=mock_projections):
                with patch.object(sprint, "resolve_config", return_value={}):
                    result = run_typer(
                        aet.app,
                        [
                            "sprint",
                            "add",
                            str(plan),
                            "--queue-file",
                            queue_file,
                            "--history-file",
                            history_file,
                            "--plans-dir",
                            str(plans_dir),
                        ],
                        cwd=tmp,
                    )

            self.assertEqual(result.exit_code, 0, result.output + result.stderr)
            self.assertIn("queued without publishing", result.output)

            # Plan file is not mutated with status; footer pipeline stage is preserved.
            plan_text = plan.read_text(encoding="utf-8")
            self.assertNotIn("status:", plan_text)
            self.assertIn("_Stage: plan-approved_", plan_text)

            # No intake commit is made for plan paths (ADR-054).
            log = subprocess.run(
                ["git", "log", "--format=%s"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(log.stdout.strip(), "initial")

            # Task added to queue as ready.
            queue = create_backend(
                queue_file=queue_file, history_file=history_file
            ).load()["queue"]
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["id"], "feat-001")
            self.assertEqual(queue[0]["state"], "ready")
            self.assertNotIn("status", queue[0])

            # Projection notified.
            mock_projections.on_add.assert_called_once()
            args, kwargs = mock_projections.on_add.call_args
            self.assertEqual(args[0]["id"], "feat-001")
            self.assertTrue(kwargs.get("is_new"))

    def test_sprint_add_blocked_plan_computes_state(self):
        """sprint add parks a plan with pending blockers as blocked."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            git(["init"], tmp)
            git(["config", "user.email", "test@example.com"], tmp)
            git(["config", "user.name", "Test"], tmp)

            plans_dir = tmp_path / "docs" / "plans"
            plans_dir.mkdir(parents=True)
            prds_dir = tmp_path / "docs" / "prds"
            prds_dir.mkdir(parents=True)
            (prds_dir / "default-prd.md").write_text(
                "# Default PRD\n\n## Requirements\n- **R-1**: default requirement\n",
                encoding="utf-8",
            )
            blocker = make_plan(plans_dir, "feat-000.md")
            plan = make_plan(plans_dir, "feat-001.md", blocked_by=["feat-000"])
            git(["add", "-A"], tmp)
            git(["commit", "-m", "initial"], tmp)

            queue_file, history_file = self._queue_paths(tmp_path)

            mock_projections = MagicMock()

            with patch.object(sprint, "resolve_projections", return_value=mock_projections):
                with patch.object(sprint, "resolve_config", return_value={}):
                    self.assertEqual(
                        run_typer(
                            aet.app,
                            [
                                "sprint",
"add",
                                str(blocker),
                                "--queue-file",
                                queue_file,
                                "--history-file",
                                history_file,
                                "--plans-dir",
                                str(plans_dir),
                            ],
                            cwd=tmp,
                        ).exit_code,
                        0,
                    )
                    self.assertEqual(
                        run_typer(
                            aet.app,
                            [
                                "sprint",
"add",
                                str(plan),
                                "--queue-file",
                                queue_file,
                                "--history-file",
                                history_file,
                                "--plans-dir",
                                str(plans_dir),
                            ],
                            cwd=tmp,
                        ).exit_code,
                        0,
                    )

            queue = create_backend(
                queue_file=queue_file, history_file=history_file
            ).load()["queue"]
            tasks = {t["id"]: t for t in queue}
            self.assertEqual(tasks["feat-001"]["state"], "blocked")
            self.assertEqual(tasks["feat-001"]["pending_blockers"], 1)

    def test_sprint_add_unknown_id_fails_closed(self):
        """sprint add exits non-zero when the plan file or task ID is unknown."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            git(["init"], tmp)
            git(["config", "user.email", "test@example.com"], tmp)
            git(["config", "user.name", "Test"], tmp)
            plans_dir = tmp_path / "docs" / "plans"
            plans_dir.mkdir(parents=True)
            queue_file, history_file = self._queue_paths(tmp_path)

            result = run_typer(
                aet.app,
                [
                    "sprint",
                    "add",
                    "nonexistent",
                    "--queue-file",
                    queue_file,
                    "--history-file",
                    history_file,
                    "--plans-dir",
                    str(plans_dir),
                ],
                cwd=tmp,
            )

            self.assertEqual(result.exit_code, 1)
            self.assertIn("No plan found", result.stderr)
            queue = create_backend(
                queue_file=queue_file, history_file=history_file
            ).load()["queue"]
            self.assertEqual(len(queue), 0)

    def test_sprint_add_refuses_settled_plan(self):
        """sprint add refuses to promote a task already settled in history."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            git(["init"], tmp)
            git(["config", "user.email", "test@example.com"], tmp)
            git(["config", "user.name", "Test"], tmp)

            plans_dir = tmp_path / "docs" / "plans"
            plans_dir.mkdir(parents=True)
            prds_dir = tmp_path / "docs" / "prds"
            prds_dir.mkdir(parents=True)
            (prds_dir / "default-prd.md").write_text(
                "# Default PRD\n\n## Requirements\n- **R-1**: default requirement\n",
                encoding="utf-8",
            )
            plan = make_plan(plans_dir, "feat-002.md")
            git(["add", "-A"], tmp)
            git(["commit", "-m", "initial"], tmp)

            queue_file, history_file = self._queue_paths(tmp_path)
            Path(history_file).parent.mkdir(parents=True, exist_ok=True)
            Path(history_file).write_text(
                json.dumps({"id": "feat-002", "state": "merged"}) + "\n",
                encoding="utf-8",
            )

            result = run_typer(
                aet.app,
                [
                    "sprint",
                    "add",
                    str(plan),
                    "--queue-file",
                    queue_file,
                    "--history-file",
                    history_file,
                    "--plans-dir",
                    str(plans_dir),
                ],
                cwd=tmp,
            )

            self.assertEqual(result.exit_code, 1)
            self.assertIn("already settled", result.stderr)
            queue = create_backend(
                queue_file=queue_file, history_file=history_file
            ).load()["queue"]
            self.assertEqual(len(queue), 0)

    def test_sprint_add_accepts_untracked_plan(self):
        """Untracked plans are the normal intake path (ADR-054)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            git(["init"], tmp)
            git(["config", "user.email", "test@example.com"], tmp)
            git(["config", "user.name", "Test"], tmp)

            plans_dir = tmp_path / "docs" / "plans"
            plans_dir.mkdir(parents=True)
            prds_dir = tmp_path / "docs" / "prds"
            prds_dir.mkdir(parents=True)
            (prds_dir / "default-prd.md").write_text(
                "# Default PRD\n\n## Requirements\n- **R-1**: default requirement\n",
                encoding="utf-8",
            )
            plan = make_plan(plans_dir, "feat-003.md")
            queue_file, history_file = self._queue_paths(tmp_path)

            result = run_typer(
                aet.app,
                [
                    "sprint",
                    "add",
                    str(plan),
                    "--queue-file",
                    queue_file,
                    "--history-file",
                    history_file,
                    "--plans-dir",
                    str(plans_dir),
                ],
                cwd=tmp,
            )

            self.assertEqual(result.exit_code, 0, result.output + result.stderr)
            self.assertIn("queued without publishing", result.output)
            queue = create_backend(
                queue_file=queue_file, history_file=history_file
            ).load()["queue"]
            self.assertEqual(len(queue), 1)


class TestBacklogGroup(unittest.TestCase):
    def test_backlog_group_registered(self):
        """The backlog Typer app parses ``add`` and resolves unknown plans."""
        with tempfile.TemporaryDirectory() as tmp:
            plans_dir = Path(tmp) / "docs" / "plans"
            plans_dir.mkdir(parents=True)
            result = run_typer(
                aet.app,
                ["backlog", "add", "feat-001", "--plans-dir", str(plans_dir)],
                cwd=tmp,
            )
            self.assertEqual(result.exit_code, 1)
            self.assertIn("No plan found", result.stderr)


class TestTopLevelAddRetired(unittest.TestCase):
    def test_top_level_add_is_unknown_subcommand(self):
        """Bare ``aet add`` no longer resolves through the dispatcher."""
        result = run_typer(aet.app, ["add", "docs/plans/x.md"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("No such command", result.output)


class TestNounGroups(unittest.TestCase):
    """Every noun-scoped group registered on the main app routes correctly."""

    _NOUN_GROUPS = [
        "state",
        "backlog",
        "desk",
        "docs",
        "epic",
        "gate",
        "handoff",
        "hooks",
        "learnings",
        "plan",
        "plans",
        "queue",
        "setup",
        "ship",
        "size",
        "sprint",
    ]

    def test_noun_groups_exist(self):
        registered = {g.name for g in aet.app.registered_groups}
        for name in self._NOUN_GROUPS:
            self.assertIn(name, registered)

    def test_each_noun_group_renders_help(self):
        for name in self._NOUN_GROUPS:
            with self.subTest(group=name):
                result = run_typer(aet.app, [name, "--help"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn("Usage:", result.output)


if __name__ == "__main__":
    unittest.main()
