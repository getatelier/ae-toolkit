"""Tests for resilient plan archival at closure (ppa-02)."""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from aet import plan_parser
from aet.backends.git_refs_backend import GitRefsBackend
from aet.cli import ship
from aet.closure import archive_plan_file

pytestmark = pytest.mark.xdist_group("cwd")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    (path / ".agents").mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "initial")
    _git(path, "remote", "add", "origin", str(path))
    _git(path, "push", "-u", "origin", "main", check=False)
    return path


class TestArchivePlanFile(unittest.TestCase):
    """Unit tests for `archive_plan_file` helper."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.repo = _init_repo(Path(self.tmpdir.name) / "repo")
        self.cwd = os.getcwd()
        self.addCleanup(os.chdir, self.cwd)
        os.chdir(self.repo)

    def test_archive_active_plan_file_moved_and_staged(self):
        """Active plan file is moved to docs/plans/archive/<task_id>.md and staged."""
        active_plan = self.repo / "docs" / "plans" / "active" / "feat-01.md"
        active_plan.parent.mkdir(parents=True, exist_ok=True)
        active_plan.write_text("# Feat 01\n", encoding="utf-8")

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            dest = archive_plan_file("feat-01", repo_root=self.repo)

        expected_dest = self.repo / "docs" / "plans" / "archive" / "feat-01.md"
        self.assertEqual(dest, expected_dest)
        self.assertFalse(active_plan.exists())
        self.assertTrue(expected_dest.exists())
        self.assertEqual(expected_dest.read_text(encoding="utf-8"), "# Feat 01\n")
        self.assertIn("✓ Plan archived: docs/plans/archive/feat-01.md", fake_out.getvalue())

        # Verify staged in git
        staged = _git(self.repo, "status", "--porcelain").stdout
        self.assertIn("docs/plans/archive/feat-01.md", staged)

    def test_archive_legacy_plan_file_moved_and_staged(self):
        """Legacy plan file at docs/plans/<task_id>.md is moved to archive and staged."""
        legacy_plan = self.repo / "docs" / "plans" / "legacy-01.md"
        legacy_plan.parent.mkdir(parents=True, exist_ok=True)
        legacy_plan.write_text("# Legacy 01\n", encoding="utf-8")
        _git(self.repo, "add", str(legacy_plan))
        _git(self.repo, "commit", "-q", "-m", "add legacy plan")

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            dest = archive_plan_file("legacy-01", repo_root=self.repo)

        expected_dest = self.repo / "docs" / "plans" / "archive" / "legacy-01.md"
        self.assertEqual(dest, expected_dest)
        self.assertFalse(legacy_plan.exists())
        self.assertTrue(expected_dest.exists())
        self.assertEqual(expected_dest.read_text(encoding="utf-8"), "# Legacy 01\n")
        self.assertIn("✓ Plan archived: docs/plans/archive/legacy-01.md", fake_out.getvalue())

        staged = _git(self.repo, "status", "--porcelain").stdout
        self.assertIn("docs/plans/archive/legacy-01.md", staged)

    def test_archive_active_takes_precedence_over_legacy(self):
        """If both active and legacy exist, active is preferred."""
        active_plan = self.repo / "docs" / "plans" / "active" / "dup-01.md"
        active_plan.parent.mkdir(parents=True, exist_ok=True)
        active_plan.write_text("# Active version\n", encoding="utf-8")

        legacy_plan = self.repo / "docs" / "plans" / "dup-01.md"
        legacy_plan.write_text("# Legacy version\n", encoding="utf-8")

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            dest = archive_plan_file("dup-01", repo_root=self.repo)

        expected_dest = self.repo / "docs" / "plans" / "archive" / "dup-01.md"
        self.assertEqual(dest, expected_dest)
        self.assertFalse(active_plan.exists())
        self.assertTrue(legacy_plan.exists())
        self.assertTrue(expected_dest.exists())
        self.assertEqual(expected_dest.read_text(encoding="utf-8"), "# Active version\n")
        self.assertIn("✓ Plan archived: docs/plans/archive/dup-01.md", fake_out.getvalue())

    def test_archive_plan_file_when_archive_is_gitignored(self):
        """If docs/plans/archive/ is gitignored, the file is moved but not staged."""
        gitignore = self.repo / ".gitignore"
        gitignore.write_text("docs/plans/archive/\n", encoding="utf-8")
        _git(self.repo, "add", ".gitignore")
        _git(self.repo, "commit", "-q", "-m", "ignore archive")

        active_plan = self.repo / "docs" / "plans" / "active" / "ignored-01.md"
        active_plan.parent.mkdir(parents=True, exist_ok=True)
        active_plan.write_text("# Ignored Plan\n", encoding="utf-8")

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            dest = archive_plan_file("ignored-01", repo_root=self.repo)

        expected_dest = self.repo / "docs" / "plans" / "archive" / "ignored-01.md"
        self.assertEqual(dest, expected_dest)
        self.assertFalse(active_plan.exists())
        self.assertTrue(expected_dest.exists())
        self.assertIn("✓ Plan archived: docs/plans/archive/ignored-01.md", fake_out.getvalue())

        # Verify not staged in git
        staged = _git(self.repo, "diff", "--cached", "--name-only").stdout
        self.assertNotIn("docs/plans/archive/ignored-01.md", staged)

    def test_archive_plan_file_absent_logs_notice_and_returns_none(self):
        """When no local plan file exists, an informational notice is logged and returns None cleanly."""
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            dest = archive_plan_file("missing-01", repo_root=self.repo)

        self.assertIsNone(dest)
        out = fake_out.getvalue()
        self.assertIn(
            "ℹ Plan archival: No local plan file found at docs/plans/active/missing-01.md; "
            "archive move skipped (spec preserved in task record)",
            out,
        )

    def test_archive_plan_file_defaults_to_cwd(self):
        """When repo_root is not provided, defaults to current working directory."""
        active_plan = self.repo / "docs" / "plans" / "active" / "cwd-01.md"
        active_plan.parent.mkdir(parents=True, exist_ok=True)
        active_plan.write_text("# Cwd Plan\n", encoding="utf-8")

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            dest = archive_plan_file("cwd-01")

        expected_dest = self.repo / "docs" / "plans" / "archive" / "cwd-01.md"
        self.assertEqual(dest.resolve(), expected_dest.resolve())
        self.assertTrue(expected_dest.exists())
        self.assertIn("✓ Plan archived: docs/plans/archive/cwd-01.md", fake_out.getvalue())


class TestShipArchivalClosureIntegration(unittest.TestCase):
    """Integration tests for plan archival during `aet ship close` and `aet ship merge`."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.repo = _init_repo(Path(self.tmpdir.name) / "repo")
        self.cwd = os.getcwd()
        self.addCleanup(os.chdir, self.cwd)
        os.chdir(self.repo)

    def _setup_task(
        self, task_id: str, plan_rel_path: str | None = None, base_commit: str | None = None
    ) -> Path | None:
        spec = {
            "frontmatter": {"id": task_id},
            "title": f"Plan {task_id}",
            "body": "",
            "tasks": ["- [x] task one"],
        }
        plan_path = None
        if plan_rel_path is not None:
            plan_path = self.repo / plan_rel_path
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            content = f"---\nid: {task_id}\nstatus: awaiting_merge\n---\n# Plan\n- [x] done\n"
            plan_path.write_text(content, encoding="utf-8")
            spec = plan_parser.extract_plan_spec_from_text(content, task_id)

        backend = GitRefsBackend(
            queue_file=str(self.repo / ".agents" / "aet-queue"),
            history_file=str(self.repo / ".agents" / "work-history.jsonl"),
        )
        backend.save(
            [
                {
                    "id": task_id,
                    "state": "awaiting_merge",
                    "stage": "qa-complete",
                    "branch": task_id,
                    "plan_file": plan_rel_path or f"docs/plans/{task_id}.md",
                    "spec": spec,
                    "base_commit": base_commit or _git(self.repo, "rev-parse", "HEAD").stdout.strip(),
                }
            ]
        )
        return plan_path

    def test_ship_close_with_active_plan_archives_and_stages(self):
        """`aet ship close` moves active plan to archive and succeeds."""
        task_id = "t-close-active"
        base_commit = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        plan_path = self._setup_task(task_id, f"docs/plans/active/{task_id}.md", base_commit=base_commit)

        # Feature branch with commit merged into main
        _git(self.repo, "checkout", "-q", "-b", task_id)
        (self.repo / "f.txt").write_text("feature\n", encoding="utf-8")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-q", "-m", "work")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "merge", "-q", "--no-ff", task_id, "-m", f"Merge {task_id}")
        _git(self.repo, "push", "origin", "main")

        args = argparse.Namespace(
            command="close",
            task_id=task_id,
            plan=None,
            queue=".agents/aet-queue",
            branch=None,
            merge_commit=None,
            target_branch=None,
            dry_run=False,
        )
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            rc = ship.cmd_ship(args)

        self.assertEqual(rc, 0)
        self.assertFalse(plan_path.exists())
        archived = self.repo / "docs" / "plans" / "archive" / f"{task_id}.md"
        self.assertTrue(archived.exists())
        self.assertIn(f"✓ Plan archived: docs/plans/archive/{task_id}.md", fake_out.getvalue())

    def test_ship_close_with_absent_plan_logs_info_and_succeeds(self):
        """`aet ship close` with absent plan logs info message and succeeds."""
        task_id = "t-close-absent"
        base_commit = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self._setup_task(task_id, None, base_commit=base_commit)

        _git(self.repo, "checkout", "-q", "-b", task_id)
        (self.repo / "f.txt").write_text("feature\n", encoding="utf-8")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-q", "-m", "work")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "merge", "-q", "--no-ff", task_id, "-m", f"Merge {task_id}")
        _git(self.repo, "push", "origin", "main")

        args = argparse.Namespace(
            command="close",
            task_id=task_id,
            plan=None,
            queue=".agents/aet-queue",
            branch=None,
            merge_commit=None,
            target_branch=None,
            dry_run=False,
        )
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            rc = ship.cmd_ship(args)

        self.assertEqual(rc, 0)
        out = fake_out.getvalue()
        self.assertIn(
            f"ℹ Plan archival: No local plan file found at docs/plans/active/{task_id}.md; "
            "archive move skipped (spec preserved in task record)",
            out,
        )

    def test_ship_merge_with_active_plan_archives_and_succeeds(self):
        """`aet ship merge` moves active plan to archive."""
        task_id = "t-merge-active"
        plan_path = self._setup_task(task_id, f"docs/plans/active/{task_id}.md")

        gate_result = ship.GateResult(
            ok=True,
            pr_base="origin/main",
            rebased=False,
            scope_audit=[],
            dry_run=False,
            message="Gate passed.",
        )
        with (
            patch.object(ship, "_run_gate", return_value=gate_result),
            patch.object(ship, "_resolve_feature_branch", return_value=task_id),
            patch.object(ship, "_check_release_guard", return_value=None),
            patch.object(ship, "_is_monolithic_commit", return_value=False),
            patch.object(ship, "_has_merge_conflicts", return_value=(False, "")),
            patch.object(ship, "_merge_into_target", return_value=(True, "merged", "abc123")),
            patch.object(ship.aet_state, "cmd_record_merge", return_value=0),
            patch("sys.stdout", new=io.StringIO()) as fake_out,
        ):
            rc = ship.cmd_merge(argparse.Namespace(plan=task_id, branch="main", dry_run=False))

        self.assertEqual(rc, 0)
        self.assertFalse(plan_path.exists())
        archived = self.repo / "docs" / "plans" / "archive" / f"{task_id}.md"
        self.assertTrue(archived.exists())
        self.assertIn(f"✓ Plan archived: docs/plans/archive/{task_id}.md", fake_out.getvalue())


if __name__ == "__main__":
    unittest.main()
