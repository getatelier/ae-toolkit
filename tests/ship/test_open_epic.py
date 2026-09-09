"""Tests for `aet ship open-epic` (ned-03)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aet.backends.factory import create_backend
from aet.cli import ship
from aet.cli.main import app
from aet.ledger import Ledger
from tests.cli._helpers import git, run_typer


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-q"], path)
    git(["config", "user.email", "test@example.com"], path)
    git(["config", "user.name", "Test User"], path)
    (path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (path / ".gitignore").write_text(".agents/\n", encoding="utf-8")
    git(["add", "."], path)
    git(["commit", "-q", "-m", "initial"], path)
    git(["branch", "-M", "main"], path)
    git(["remote", "add", "origin", str(path)], path)
    git(["push", "-u", "origin", "main"], path)
    git(["remote", "set-head", "origin", "main"], path)
    return path


class TestOpenEpic(unittest.TestCase):
    """Behavior tests for `aet ship open-epic`."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.repo = _init_repo(Path(self.tmpdir.name) / "repo")
        self.cwd = os.getcwd()
        self.addCleanup(os.chdir, self.cwd)
        os.chdir(self.repo)
        old_ledger_path = os.environ.get("AET_LEDGER_PATH")
        os.environ["AET_LEDGER_PATH"] = str(self.repo / ".agents" / "ledger.jsonl")

        def _cleanup_env():
            if old_ledger_path is None:
                os.environ.pop("AET_LEDGER_PATH", None)
            else:
                os.environ["AET_LEDGER_PATH"] = old_ledger_path

        self.addCleanup(_cleanup_env)

    def _backend(self):
        backend = create_backend(
            queue_file=str(self.repo / ".agents" / "aet-queue"),
            history_file=str(self.repo / ".agents" / "work-history.jsonl"),
        )
        self.addCleanup(backend.close)
        return backend

    def _branch(self, name: str, filename: str, content: str, msg: str) -> None:
        git(["checkout", "-q", "-b", name], self.repo)
        (self.repo / filename).write_text(content, encoding="utf-8")
        git(["add", filename], self.repo)
        git(["commit", "-q", "-m", msg], self.repo)
        git(["push", "-u", "origin", name], self.repo)

    def test_no_active_epic_fails_closed(self):
        """With no active epic and no argument, the command exits non-zero and names `aet epic set`."""
        result = run_typer(app, ["ship", "open-epic"], cwd=self.repo)
        self.assertNotEqual(result.exit_code, 0)
        combined = result.output + result.stderr
        self.assertIn("aet epic set", combined)

    def test_title_defaults_to_branch_name_and_body_to_commit_subjects(self):
        """An epic declared without a title produces a PR title equal to the branch name,
        and a body listing commit subjects.
        """
        branch_name = "epic/alpha"
        self._branch(
            branch_name,
            "feat1.txt",
            "feat 1\n",
            "feat(alpha): add first component",
        )
        (self.repo / "feat2.txt").write_text("feat 2\n", encoding="utf-8")
        git(["add", "feat2.txt"], self.repo)
        git(["commit", "-q", "-m", "feat(alpha): add second component"], self.repo)
        git(["push", "origin", branch_name], self.repo)

        backend = self._backend()
        backend.set_epic(branch_name)

        created_prs = []

        def mock_create_pr(pr_base, title, body, dry_run):
            created_prs.append({"pr_base": pr_base, "title": title, "body": body})
            return True, "https://github.com/example/repo/pull/101\n"

        with (
            patch.object(ship, "_create_pr", side_effect=mock_create_pr),
            patch.object(ship, "_find_existing_pr", return_value=None),
            patch.dict(os.environ, {"AET_SHIP_TEST_CMD": "true"}),
        ):
            result = run_typer(app, ["ship", "open-epic"], cwd=self.repo)

        self.assertEqual(result.exit_code, 0, result.output + result.stderr)
        self.assertEqual(len(created_prs), 1)
        self.assertEqual(created_prs[0]["title"], branch_name)
        self.assertIn("feat(alpha): add first component", created_prs[0]["body"])
        self.assertIn("feat(alpha): add second component", created_prs[0]["body"])

    def test_declared_title_and_body_are_used(self):
        """A declared title and body file reach `gh pr create` verbatim."""
        branch_name = "epic/beta"
        self._branch(
            branch_name,
            "beta.txt",
            "beta feature\n",
            "feat(beta): initial beta work",
        )

        body_content = "# Epic Beta PR\n\nFull description of Epic Beta.\n"
        body_file = self.repo / "docs" / "beta_body.md"
        body_file.parent.mkdir(parents=True, exist_ok=True)
        body_file.write_text(body_content, encoding="utf-8")
        git(["add", "docs/beta_body.md"], self.repo)
        git(["commit", "-q", "-m", "docs(epic): add body file"], self.repo)
        git(["push", "origin", branch_name], self.repo)

        backend = self._backend()
        backend.set_epic(
            branch_name,
            title="Epic Beta: Feature Suite",
            body_file="docs/beta_body.md",
        )

        created_prs = []

        def mock_create_pr(pr_base, title, body, dry_run):
            created_prs.append({"pr_base": pr_base, "title": title, "body": body})
            return True, "https://github.com/example/repo/pull/102\n"

        with (
            patch.object(ship, "_create_pr", side_effect=mock_create_pr),
            patch.object(ship, "_find_existing_pr", return_value=None),
            patch.dict(os.environ, {"AET_SHIP_TEST_CMD": "true"}),
        ):
            result = run_typer(app, ["ship", "open-epic"], cwd=self.repo)

        self.assertEqual(result.exit_code, 0, result.output + result.stderr)
        self.assertEqual(len(created_prs), 1)
        self.assertEqual(created_prs[0]["title"], "Epic Beta: Feature Suite")
        self.assertEqual(created_prs[0]["body"], body_content)

    def test_second_invocation_reports_the_existing_pr(self):
        """A successful run leaves exactly one PR, and a second invocation prints that
        PR's URL and exits zero without a second `gh pr create`.
        """
        branch_name = "epic/gamma"
        self._branch(
            branch_name,
            "gamma.txt",
            "gamma feature\n",
            "feat(gamma): add gamma work",
        )

        backend = self._backend()
        backend.set_epic(branch_name, title="Epic Gamma")

        created_prs = []
        existing_url = "https://github.com/example/repo/pull/103"

        def mock_create_pr(pr_base, title, body, dry_run):
            created_prs.append({"pr_base": pr_base, "title": title, "body": body})
            return True, f"{existing_url}\n"

        # First invocation: no existing PR yet -> creates PR
        with (
            patch.object(ship, "_create_pr", side_effect=mock_create_pr),
            patch.object(ship, "_find_existing_pr", return_value=None),
            patch.dict(os.environ, {"AET_SHIP_TEST_CMD": "true"}),
        ):
            res1 = run_typer(app, ["ship", "open-epic"], cwd=self.repo)

        self.assertEqual(res1.exit_code, 0, res1.output + res1.stderr)
        self.assertEqual(len(created_prs), 1)

        # Second invocation: existing PR found -> reports existing PR URL without calling _create_pr
        with (
            patch.object(ship, "_create_pr", side_effect=mock_create_pr),
            patch.object(ship, "_find_existing_pr", return_value=existing_url),
            patch.dict(os.environ, {"AET_SHIP_TEST_CMD": "true"}),
        ):
            res2 = run_typer(app, ["ship", "open-epic"], cwd=self.repo)

        self.assertEqual(res2.exit_code, 0, res2.output + res2.stderr)
        self.assertIn(existing_url, res2.output)
        # Verify _create_pr was NOT called a second time
        self.assertEqual(len(created_prs), 1)

    def test_gate_failure_creates_no_pr(self):
        """A failing gate exits non-zero and creates no PR."""
        branch_name = "epic/delta"
        self._branch(
            branch_name,
            "delta.txt",
            "delta feature\n",
            "feat(delta): add delta work",
        )

        backend = self._backend()
        backend.set_epic(branch_name)

        created_prs = []

        def mock_create_pr(pr_base, title, body, dry_run):
            created_prs.append({"pr_base": pr_base, "title": title, "body": body})
            return True, "https://github.com/example/repo/pull/104\n"

        # Gate failure via failing test command
        with (
            patch.object(ship, "_create_pr", side_effect=mock_create_pr),
            patch.object(ship, "_find_existing_pr", return_value=None),
            patch.dict(os.environ, {"AET_SHIP_TEST_CMD": "false"}),
        ):
            result = run_typer(app, ["ship", "open-epic"], cwd=self.repo)

        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(len(created_prs), 0)

    def test_branch_argument_resolves_and_records_ledger_event(self):
        """An explicit branch argument opens the PR and records a `cut` ledger event."""
        branch_name = "epic/explicit"
        self._branch(
            branch_name,
            "explicit.txt",
            "explicit content\n",
            "feat(explicit): explicit commit",
        )

        created_prs = []
        pr_url = "https://github.com/example/repo/pull/105"

        def mock_create_pr(pr_base, title, body, dry_run):
            created_prs.append({"pr_base": pr_base, "title": title, "body": body})
            return True, f"{pr_url}\n"

        with (
            patch.object(ship, "_create_pr", side_effect=mock_create_pr),
            patch.object(ship, "_find_existing_pr", return_value=None),
            patch.dict(os.environ, {"AET_SHIP_TEST_CMD": "true"}),
        ):
            result = run_typer(app, ["ship", "open-epic", branch_name], cwd=self.repo)

        self.assertEqual(result.exit_code, 0, result.output + result.stderr)
        self.assertEqual(len(created_prs), 1)
        self.assertEqual(created_prs[0]["title"], branch_name)

        # Check ledger
        ledger = Ledger(self.repo / ".agents" / "ledger.jsonl")
        cut_events = ledger.read_events(task=branch_name, kind="cut")
        self.assertEqual(len(cut_events), 1)
        self.assertEqual(cut_events[0]["ref"], pr_url)
        self.assertEqual(cut_events[0]["ref_kind"], "pr")


if __name__ == "__main__":
    unittest.main()
