"""Tests for aet sprint add and re-ingestion of inert tasks (R-1, R-2, R-3, R-4)."""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aet.backends.git_refs_backend import GitRefsBackend
from aet.cli import sprint as sprint_cmd
from aet.plan_parser import is_task_inert


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test User"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "initial"],
        check=True,
    )


def _write_prd(prds_dir: Path, name: str = "default.md", rids: list[str] | None = None) -> Path:
    prds_dir.mkdir(parents=True, exist_ok=True)
    path = prds_dir / name
    lines = [f"# PRD: {path.stem}", "", "## Requirements"]
    for rid in rids or ["R-1"]:
        lines.append(f"- **{rid}**: requirement {rid}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_plan(
    plans_dir: Path,
    stem: str,
    *,
    prd_name: str = "default.md",
    rids: list[str] | None = None,
    blocked_by: list[str] | None = None,
    work_class: str = "normal",
    body_extra: str = "",
) -> Path:
    plans_dir.mkdir(parents=True, exist_ok=True)
    path = plans_dir / f"{stem}.md"
    lines = [
        "---",
        f"id: {stem}",
        "size: S",
        f"work_class: {work_class}",
    ]
    if blocked_by is not None:
        lines.append("blocked_by:")
        for b in blocked_by:
            lines.append(f"  - {b}")
    lines.extend(
        [
            "---",
            "",
            f"# {stem}",
            "",
            "## Context",
            f"PRD: docs/prds/{prd_name}",
            "",
            "## Task List",
        ]
    )
    for i, rid in enumerate(rids or ["R-1"], 1):
        lines.append(f"{i}. Task item {i} (traces: {rid}).")
    if body_extra:
        lines.extend(["", body_extra])
    lines.extend(
        [
            "",
            "## Files to Modify",
            f"- `src/{stem}.py`",
            "",
            "## Validation Steps",
            f"- [ ] test_{stem} verifies {stem}.py",
            "",
            "---",
            "",
            "*Stage: plan-approved*",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestInertnessPredicate(unittest.TestCase):
    """Unit tests for the inertness predicate in aet.plan_parser (R-3)."""

    def test_inert_states_are_allowed(self):
        for state in ("planned", "ready", "blocked"):
            task = {
                "id": "t1",
                "state": state,
                "branch": None,
                "worktree": None,
                "merge_commit": None,
            }
            inert, blocking_field = is_task_inert(task)
            self.assertTrue(inert, f"state {state} should be inert")
            self.assertIsNone(blocking_field)

    def test_non_inert_states_are_refused_with_state_field(self):
        for state in (
            "in_progress",
            "awaiting_merge",
            "failed",
            "quarantined",
            "merged",
            "abandoned",
        ):
            task = {
                "id": "t1",
                "state": state,
                "branch": None,
                "worktree": None,
                "merge_commit": None,
            }
            inert, blocking_field = is_task_inert(task)
            self.assertFalse(inert, f"state {state} should not be inert")
            self.assertEqual(blocking_field, "state")

    def test_execution_artifacts_are_refused_with_named_field(self):
        base_task = {
            "id": "t1",
            "state": "ready",
            "branch": None,
            "worktree": None,
            "merge_commit": None,
        }

        with_branch = dict(base_task, branch="poh-01-feature")
        inert, blocking_field = is_task_inert(with_branch)
        self.assertFalse(inert)
        self.assertEqual(blocking_field, "branch")

        with_wt = dict(base_task, worktree="/workspace/wt/t1")
        inert, blocking_field = is_task_inert(with_wt)
        self.assertFalse(inert)
        self.assertEqual(blocking_field, "worktree")

        with_mc = dict(base_task, merge_commit="abc1234")
        inert, blocking_field = is_task_inert(with_mc)
        self.assertFalse(inert)
        self.assertEqual(blocking_field, "merge_commit")

        with_ib = dict(base_task, integration_branch="epic-01")
        inert, blocking_field = is_task_inert(with_ib)
        self.assertFalse(inert)
        self.assertEqual(blocking_field, "integration_branch")


class TestSprintAddReingestion(unittest.TestCase):
    """Tests for sprint add re-ingestion and distinct outcomes (R-1, R-2, R-3, R-4)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plans_dir = self.root / "docs" / "plans"
        self.prds_dir = self.root / "docs" / "prds"
        self.queue_file = self.root / ".agents" / "aet-queue"
        self.history_file = self.root / ".agents" / "work-history.jsonl"
        self.config_path = self.root / ".agents" / "aet-config.json"
        self.plans_dir.mkdir(parents=True)
        self.prds_dir.mkdir(parents=True)
        _write_prd(self.prds_dir)
        _git_init(self.root)
        self.backend = GitRefsBackend(
            queue_file=str(self.queue_file),
            history_file=str(self.history_file),
        )

    def tearDown(self):
        self.backend.close()
        self.tmp.cleanup()

    def _run_sprint_add(self, target: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            sys,
            "argv",
            [
                "sprint",
                "add",
                target,
                "--queue-file",
                str(self.queue_file),
                "--history-file",
                str(self.history_file),
                "--plans-dir",
                str(self.plans_dir),
                "--config",
                str(self.config_path),
            ],
        ):
            with contextlib.redirect_stdout(stdout):
                with contextlib.redirect_stderr(stderr):
                    rc = sprint_cmd.main()
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_inert_task_is_re_ingested(self):
        """Editing an inert queued task's plan and re-adding re-ingests the spec (R-1)."""
        _write_plan(self.plans_dir, "feat-001", rids=["R-1"])
        rc, out, err = self._run_sprint_add("feat-001")
        self.assertEqual(rc, 0)
        self.assertIn("queued without publishing", out)

        # Update PRD and modify plan file with an additional task
        _write_prd(self.prds_dir, rids=["R-1", "R-2"])
        _write_plan(
            self.plans_dir,
            "feat-001",
            rids=["R-1", "R-2"],
            body_extra="Additional spec prose for testing.",
        )

        rc, out, err = self._run_sprint_add("feat-001")
        self.assertEqual(rc, 0)
        self.assertIn("spec re-ingested", out)

        # Inspect backend data
        data = self.backend.load()["queue"]
        task = next(t for t in data if t["id"] == "feat-001")
        self.assertIn("Additional spec prose for testing.", task["spec"]["body"])
        self.assertEqual(len(task["spec"]["tasks"]), 2)

    def test_task_with_run_state_is_refused(self):
        """A task carrying run state or non-inert state is refused with the blocking field named (R-3)."""
        _write_plan(self.plans_dir, "feat-run")
        rc, out, err = self._run_sprint_add("feat-run")
        self.assertEqual(rc, 0)

        # Case 1: non-inert state in_progress
        queue = self.backend.load()["queue"]
        task = next(t for t in queue if t["id"] == "feat-run")
        task["state"] = "in_progress"
        self.backend.save(queue)

        rc, out, err = self._run_sprint_add("feat-run")
        self.assertEqual(rc, 1)
        self.assertIn("Refusing to re-ingest", err)
        self.assertIn("state", err)

        # Case 2: ready state with assigned branch
        queue = self.backend.load()["queue"]
        task = next(t for t in queue if t["id"] == "feat-run")
        task["state"] = "ready"
        task["branch"] = "feat-run-branch"
        self.backend.save(queue)

        rc, out, err = self._run_sprint_add("feat-run")
        self.assertEqual(rc, 1)
        self.assertIn("Refusing to re-ingest", err)
        self.assertIn("branch", err)

        # Case 3: ready state with assigned worktree
        task["branch"] = None
        task["worktree"] = "/tmp/wt/feat-run"
        self.backend.save(queue)

        rc, out, err = self._run_sprint_add("feat-run")
        self.assertEqual(rc, 1)
        self.assertIn("Refusing to re-ingest", err)
        self.assertIn("worktree", err)

        # Case 4: ready state with merge_commit
        task["worktree"] = None
        task["merge_commit"] = "deadbeef1234"
        self.backend.save(queue)

        rc, out, err = self._run_sprint_add("feat-run")
        self.assertEqual(rc, 1)
        self.assertIn("Refusing to re-ingest", err)
        self.assertIn("merge_commit", err)

    def test_re_ingest_recomputes_blockers_and_keeps_history(self):
        """Re-ingestion recomputes blocked_by, pending_blockers, state, and retains history (R-4)."""
        _write_plan(self.plans_dir, "blocker-1")
        self._run_sprint_add("blocker-1")

        _write_plan(self.plans_dir, "dep-1", blocked_by=["blocker-1"])
        rc, out, err = self._run_sprint_add("dep-1")
        self.assertEqual(rc, 0)

        # Verify dep-1 is blocked
        queue = self.backend.load()["queue"]
        task = next(t for t in queue if t["id"] == "dep-1")
        self.assertEqual(task["state"], "blocked")
        self.assertEqual(task["pending_blockers"], 1)
        self.assertEqual(len(task["history"]), 1)
        initial_history_entry = task["history"][0]

        # Edit dep-1 to remove the blocker
        _write_plan(self.plans_dir, "dep-1", blocked_by=[])
        rc, out, err = self._run_sprint_add("dep-1")
        self.assertEqual(rc, 0)

        queue = self.backend.load()["queue"]
        task = next(t for t in queue if t["id"] == "dep-1")
        self.assertEqual(task["state"], "ready")
        self.assertEqual(task["pending_blockers"], 0)
        self.assertEqual(task["blocked_by"], [])
        # History retains earlier entry and appends new transition
        self.assertGreaterEqual(len(task["history"]), 2)
        self.assertEqual(task["history"][0], initial_history_entry)
        self.assertEqual(task["history"][-1]["from"], "blocked")
        self.assertEqual(task["history"][-1]["to"], "ready")
        self.assertEqual(task["history"][-1]["by"], "sync")

    def test_intake_outcomes_are_distinguishable(self):
        """The three intake outcomes produce three distinct messages (R-2)."""
        _write_plan(self.plans_dir, "msg-001")

        # Outcome 1: Newly admitted
        rc1, out1, err1 = self._run_sprint_add("msg-001")
        self.assertEqual(rc1, 0)
        self.assertIn("queued without publishing", out1)

        # Outcome 2: Spec re-ingested with changed content
        _write_plan(self.plans_dir, "msg-001", body_extra="New content added here.")
        rc2, out2, err2 = self._run_sprint_add("msg-001")
        self.assertEqual(rc2, 0)
        self.assertIn("spec re-ingested", out2)

        # Outcome 3: Spec unchanged
        rc3, out3, err3 = self._run_sprint_add("msg-001")
        self.assertEqual(rc3, 0)
        self.assertIn("spec unchanged", out3)

        # Assert all 3 messages are mutually distinct
        self.assertNotEqual(out1.strip(), out2.strip())
        self.assertNotEqual(out2.strip(), out3.strip())
        self.assertNotEqual(out1.strip(), out3.strip())

    def test_edit_then_add_changes_stored_spec(self):
        """Editing a plan and running sprint add updates the stored spec in git refs (R-1)."""
        _write_plan(self.plans_dir, "git-spec-001")
        self._run_sprint_add("git-spec-001")

        # Edit plan body
        _write_plan(
            self.plans_dir,
            "git-spec-001",
            body_extra="Updated body line for git refs verification.",
        )
        rc, out, err = self._run_sprint_add("git-spec-001")
        self.assertEqual(rc, 0)
        self.assertIn("spec re-ingested", out)

        # Verify directly from GitRefsBackend load
        fresh_backend = GitRefsBackend(
            queue_file=str(self.queue_file),
            history_file=str(self.history_file),
        )
        try:
            tasks = fresh_backend.load()["queue"]
            task = next(t for t in tasks if t["id"] == "git-spec-001")
            self.assertIn(
                "Updated body line for git refs verification.",
                task["spec"]["body"],
            )
        finally:
            fresh_backend.close()


if __name__ == "__main__":
    unittest.main()
