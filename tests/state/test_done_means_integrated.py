"""Tests for single-pr mode: "done" means integrated, not trunk arrival.

In ``single-pr`` mode a task completes by squash-merging into the epic's
integration branch locally. ADR-011 dependency-unblocking fires on that event
rather than on trunk arrival. These tests assert that ``aet_state`` derives
terminal status and unblocks dependents against the integration branch, while
``pr-per-task`` behavior (integration_branch == trunk_branch) is unchanged.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_AET_STATE_PY = Path(__file__).parents[2] / "src" / "aet" / "cli" / "aet_state.py"
_spec = importlib.util.spec_from_loader(
    "aet_state", importlib.machinery.SourceFileLoader("aet_state", str(_AET_STATE_PY))
)
aet_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aet_state)


class MockResult:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _git_mock(responses):
    """Return a mock subprocess.run that answers git commands.

    responses maps tuple(git_args) -> (returncode, stdout, stderr).
    """

    def mock_run(cmd, **kwargs):
        args = tuple(cmd[1:])
        rc, out, err = responses.get(args, (1, "", ""))
        return MockResult(rc, out, err)

    return mock_run


def _plan_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Plan\n")
        return f.name


class TestDoneMeansIntegrated(unittest.TestCase):
    """A task on the integration branch is merged in single-pr mode."""

    def test_task_merged_to_integration_branch_derives_terminal(self):
        """A branch merged to the integration branch derives merged."""
        plan_path = _plan_file()
        task = {
            "id": "t1",
            "plan_file": plan_path,
            "branch": "t1",
            "base_commit": "base0000",
        }

        responses = {
            ("show-ref", "--verify", "--quiet", "refs/heads/t1"): (0, "", ""),
            ("rev-parse", "t1"): (0, "t1tip00\n", ""),
            ("rev-parse", "base0000"): (0, "base0000\n", ""),
            # Ancestor of origin/epic-01 but not origin/main.
            ("merge-base", "--is-ancestor", "t1", "origin/epic-01"): (0, "", ""),
            ("merge-base", "--is-ancestor", "t1", "origin/main"): (1, "", ""),
        }

        with patch.object(
            aet_state.subprocess, "run", side_effect=_git_mock(responses)
        ):
            derived = aet_state.derive_status(
                task, trunk_branch="main", integration_branch="epic-01"
            )

        self.assertEqual(derived["derived_status"], "merged")
        self.assertTrue(derived["on_trunk"])

    def test_task_not_on_integration_branch_derives_in_progress(self):
        """A branch not on the integration branch is still in progress."""
        plan_path = _plan_file()
        task = {
            "id": "t1",
            "plan_file": plan_path,
            "branch": "t1",
            "base_commit": "base0000",
        }

        responses = {
            ("show-ref", "--verify", "--quiet", "refs/heads/t1"): (0, "", ""),
            ("rev-parse", "t1"): (0, "t1tip00\n", ""),
            ("rev-parse", "base0000"): (0, "base0000\n", ""),
            ("merge-base", "--is-ancestor", "t1", "origin/epic-01"): (1, "", ""),
        }

        with patch.object(
            aet_state.subprocess, "run", side_effect=_git_mock(responses)
        ):
            derived = aet_state.derive_status(
                task, trunk_branch="main", integration_branch="epic-01"
            )

        self.assertEqual(derived["derived_status"], "in_progress")
        self.assertFalse(derived["on_trunk"])

    def test_dependent_unblocks_when_blocker_integrated(self):
        """A dependent becomes ready when its blocker is on the integration branch."""
        plan_path = _plan_file()

        def blocker_status(task_id):
            return "merged" if task_id == "blocker" else "unknown"

        task = {
            "id": "dependent",
            "plan_file": plan_path,
            "branch": None,
            "blocked_by": ["blocker"],
        }

        responses = {
            ("show-ref", "--verify", "--quiet", "refs/heads/None"): (1, "", ""),
        }

        with patch.object(
            aet_state.subprocess, "run", side_effect=_git_mock(responses)
        ):
            derived = aet_state.derive_status(
                task,
                blocker_status,
                trunk_branch="main",
                integration_branch="epic-01",
            )

        self.assertEqual(derived["derived_status"], "ready")

    def test_trunk_arrival_not_required_for_terminal(self):
        """A task on the integration branch is merged even if not on trunk."""
        _plan_file()
        task = {
            "id": "t1",
            "state": "awaiting_merge",
            "branch": "t1",
            "base_commit": "base0000",
        }

        responses = {
            ("rev-parse", "t1"): (0, "t1tip00\n", ""),
            ("rev-parse", "base0000"): (0, "base0000\n", ""),
            ("merge-base", "--is-ancestor", "t1", "origin/epic-01"): (0, "", ""),
            ("merge-base", "--is-ancestor", "t1", "origin/main"): (1, "", ""),
        }

        with patch.object(
            aet_state.subprocess, "run", side_effect=_git_mock(responses)
        ):
            ok, msg = aet_state.validate_transition(
                task,
                "awaiting_merge",
                "merged",
                trunk_branch="main",
                integration_branch="epic-01",
            )

        self.assertTrue(ok, msg)

    def test_pr_per_task_unchanged_when_integration_equals_trunk(self):
        """When integration_branch == trunk_branch, behavior matches pr-per-task."""
        plan_path = _plan_file()
        task = {
            "id": "t1",
            "plan_file": plan_path,
            "branch": "t1",
            "base_commit": "base0000",
        }

        responses = {
            ("show-ref", "--verify", "--quiet", "refs/heads/t1"): (0, "", ""),
            ("rev-parse", "t1"): (0, "t1tip00\n", ""),
            ("rev-parse", "base0000"): (0, "base0000\n", ""),
            ("merge-base", "--is-ancestor", "t1", "origin/main"): (0, "", ""),
        }

        with patch.object(
            aet_state.subprocess, "run", side_effect=_git_mock(responses)
        ):
            derived = aet_state.derive_status(
                task, trunk_branch="main", integration_branch="main"
            )

        self.assertEqual(derived["derived_status"], "merged")

    def test_closure_reads_the_stamp_not_the_declaration(self):
        """Task 3 (R-8): Deriving closure verifies against stamped integration_branch, not active epic."""
        plan_path = _plan_file()
        task = {
            "id": "t1",
            "plan_file": plan_path,
            "branch": "t1",
            "base_commit": "base0000",
            "integration_branch": "epic-01",
        }

        responses = {
            ("show-ref", "--verify", "--quiet", "refs/heads/t1"): (0, "", ""),
            ("rev-parse", "t1"): (0, "t1tip00\n", ""),
            ("rev-parse", "base0000"): (0, "base0000\n", ""),
            # Merged on stamped epic-01, but NOT on active epic-02 or main
            ("merge-base", "--is-ancestor", "t1", "origin/epic-01"): (0, "", ""),
            ("merge-base", "--is-ancestor", "t1", "origin/epic-02"): (1, "", ""),
            ("merge-base", "--is-ancestor", "t1", "origin/main"): (1, "", ""),
        }

        with patch.object(
            aet_state.subprocess, "run", side_effect=_git_mock(responses)
        ):
            # Pass active epic 'epic-02', but task is stamped to 'epic-01'
            derived = aet_state.derive_status(
                task, trunk_branch="main", integration_branch="epic-02"
            )
            ok, msg = aet_state.validate_transition(
                dict(task, state="awaiting_merge"),
                "awaiting_merge",
                "merged",
                trunk_branch="main",
                integration_branch="epic-02",
            )

        self.assertEqual(derived["derived_status"], "merged")
        self.assertTrue(ok, msg)


if __name__ == "__main__":
    unittest.main()
