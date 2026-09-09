"""Tests for `aet epic` CLI command group."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from aet.backends.factory import create_backend
from aet.cli.main import app
from tests.cli._helpers import git, run_typer


class TestEpicCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        git(["init"], self.repo)
        git(["config", "user.email", "test@example.com"], self.repo)
        git(["config", "user.name", "Test User"], self.repo)
        (self.repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
        git(["add", "README.md"], self.repo)
        git(["commit", "-m", "initial"], self.repo)
        git(["branch", "-M", "main"], self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_then_show_reports_branch_and_title(self):
        """R-2: aet epic set writes declaration and aet epic show displays it."""
        # Create a branch so it resolves
        git(["branch", "feature/epic-1"], self.repo)

        result = run_typer(
            app,
            ["epic", "set", "feature/epic-1", "--title", "My Epic Title"],
            cwd=self.repo,
        )
        self.assertEqual(result.exit_code, 0, result.output + result.stderr)

        show_res = run_typer(app, ["epic", "show"], cwd=self.repo)
        self.assertEqual(show_res.exit_code, 0, show_res.output + show_res.stderr)
        self.assertIn("feature/epic-1", show_res.output)
        self.assertIn("My Epic Title", show_res.output)
        self.assertIn("set_at", show_res.output)

    def test_clear_reports_no_active_epic(self):
        """R-2: aet epic clear clears declaration and aet epic show reports no active epic."""
        git(["branch", "feature/epic-1"], self.repo)

        run_typer(app, ["epic", "set", "feature/epic-1"], cwd=self.repo)
        clear_res = run_typer(app, ["epic", "clear"], cwd=self.repo)
        self.assertEqual(clear_res.exit_code, 0, clear_res.output + clear_res.stderr)

        show_res = run_typer(app, ["epic", "show"], cwd=self.repo)
        self.assertEqual(show_res.exit_code, 0, show_res.output + show_res.stderr)
        self.assertIn("No active epic", show_res.output)

    def test_set_rejects_a_missing_body_file(self):
        """R-1: set rejects a missing body file."""
        git(["branch", "feature/epic-1"], self.repo)

        result = run_typer(
            app,
            ["epic", "set", "feature/epic-1", "--body-file", "nonexistent.md"],
            cwd=self.repo,
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("nonexistent.md", result.output + result.stderr)

    def test_unknown_branch_is_refused_without_create(self):
        """R-18: set on unknown branch exits non-zero naming --create and writes no declaration."""
        result = run_typer(
            app,
            ["epic", "set", "unknown-branch"],
            cwd=self.repo,
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--create", result.output + result.stderr)

        # Ensure no declaration was written
        backend = create_backend(
            queue_file=str(self.repo / ".agents" / "aet-queue"),
            history_file=str(self.repo / ".agents" / "work-history.jsonl"),
        )
        self.assertIsNone(backend.read_epic())
        backend.close()

    def test_create_declares_without_creating_a_branch(self):
        """R-18: with --create, writes declaration and creates no branch."""
        result = run_typer(
            app,
            ["epic", "set", "new-epic-branch", "--create", "--title", "New Epic"],
            cwd=self.repo,
        )
        self.assertEqual(result.exit_code, 0, result.output + result.stderr)

        # Declaration is written
        backend = create_backend(
            queue_file=str(self.repo / ".agents" / "aet-queue"),
            history_file=str(self.repo / ".agents" / "work-history.jsonl"),
        )
        epic = backend.read_epic()
        self.assertIsNotNone(epic)
        self.assertEqual(epic["branch"], "new-epic-branch")
        self.assertEqual(epic["title"], "New Epic")
        backend.close()

        # Branch was NOT created
        check_branch = subprocess.run(
            ["git", "-C", str(self.repo), "show-ref", "--verify", "refs/heads/new-epic-branch"],
            capture_output=True,
        )
        self.assertNotEqual(check_branch.returncode, 0)


if __name__ == "__main__":
    unittest.main()
