"""Merge evidence is recorded, not inferred from ancestry (ADR-064).

Regression tests for the defect where a task branch with zero commits derived
as ``merged``: an undiverged branch sits at its base and is trivially an
ancestor of that base, which ancestry alone cannot distinguish from a branch
that was really merged.
"""

import importlib.machinery
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.state._helpers import add_bare_origin, init_git_repo

_AET_STATE_PY = Path(__file__).parents[2] / "src" / "aet" / "cli" / "aet_state.py"

_spec = importlib.util.spec_from_loader(
    "aet_state", importlib.machinery.SourceFileLoader("aet_state", str(_AET_STATE_PY))
)
aet_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aet_state)


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )


class MergeEvidenceRepo:
    """A repo with an origin, an undiverged branch, and a merged branch."""

    def __init__(self, root: Path):
        self.root = root
        init_git_repo(root)
        add_bare_origin(root)
        (root / "a.txt").write_text("a\n", encoding="utf-8")
        _git(root, "add", "a.txt")
        _git(root, "commit", "-qm", "base")
        _git(root, "branch", "-M", "main")
        _git(root, "push", "-q", "-u", "origin", "main")

        # The base every task branch is created from.
        self.base = _git(root, "rev-parse", "main").stdout.strip()

        # An undiverged task branch: created and never committed to.
        _git(root, "branch", "empty-task", "main")

        # A genuinely merged task branch (--no-ff, this repo's merge style).
        _git(root, "checkout", "-q", "-b", "merged-task", "main")
        (root / "b.txt").write_text("b\n", encoding="utf-8")
        _git(root, "add", "b.txt")
        _git(root, "commit", "-qm", "real work")
        self.merged_tip = _git(root, "rev-parse", "merged-task").stdout.strip()
        _git(root, "checkout", "-q", "main")
        _git(root, "merge", "-q", "--no-ff", "-m", "merge", "merged-task")
        _git(root, "push", "-q", "origin", "main")

        # An unmerged task branch with work on it.
        _git(root, "checkout", "-q", "-b", "open-task", "main")
        (root / "c.txt").write_text("c\n", encoding="utf-8")
        _git(root, "add", "c.txt")
        _git(root, "commit", "-qm", "unmerged work")
        _git(root, "checkout", "-q", "main")


class TestMergeEvidence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = MergeEvidenceRepo(Path(self._tmp.name) / "repo")
        self.cwd = str(self.repo.root)

    def _derive(self, task):
        task.setdefault("spec", {})
        return aet_state.derive_status(task, cwd=self.cwd, trunk_branch="main")

    # -- the defect --------------------------------------------------------

    def test_undiverged_branch_does_not_derive_merged(self):
        """A branch still sitting at its base has authored nothing."""
        derived = self._derive(
            {"id": "t", "branch": "empty-task", "base_commit": self.repo.base}
        )
        self.assertFalse(derived["on_trunk"])
        self.assertEqual(derived["derived_status"], "ready")

    def test_merged_branch_still_derives_merged(self):
        """The fix must not reclassify genuinely merged work."""
        derived = self._derive(
            {"id": "t", "branch": "merged-task", "base_commit": self.repo.base}
        )
        self.assertTrue(derived["on_trunk"])
        self.assertEqual(derived["derived_status"], "merged")

    def test_unmerged_branch_with_work_is_in_progress(self):
        derived = self._derive(
            {"id": "t", "branch": "open-task", "base_commit": self.repo.base}
        )
        self.assertFalse(derived["on_trunk"])
        self.assertEqual(derived["derived_status"], "in_progress")

    # -- fail closed (ADR-064 decision 4) ----------------------------------

    def test_missing_base_commit_never_derives_merged_from_branch(self):
        """Absence of a recorded origin is not evidence that a merge happened."""
        derived = self._derive({"id": "t", "branch": "merged-task"})
        self.assertFalse(derived["on_trunk"])
        self.assertNotEqual(derived["derived_status"], "merged")

    def test_recorded_merge_commit_is_evidence_without_base_commit(self):
        """A recorded merge commit stands on its own."""
        derived = self._derive(
            {"id": "t", "branch": "merged-task", "merge_commit": self.repo.merged_tip}
        )
        self.assertTrue(derived["on_trunk"])
        self.assertEqual(derived["derived_status"], "merged")

    def test_merge_commit_equal_to_base_is_not_evidence(self):
        """A "merge commit" that is the branch's own base records no work."""
        derived = self._derive(
            {
                "id": "t",
                "branch": "empty-task",
                "base_commit": self.repo.base,
                "merge_commit": self.repo.base,
            }
        )
        self.assertFalse(derived["on_trunk"])

    # -- resolution (ADR-064 decision 3) -----------------------------------

    def test_resolve_merge_commit_refuses_undiverged_branch(self):
        """Resolution must not manufacture a merge commit from the base."""
        merge_commit, strategy, match_kind = aet_state.resolve_merge_commit(
            "empty-task",
            cwd=self.cwd,
            trunk_branch="main",
            use_diff_fallback=False,
            base_commit=self.repo.base,
        )
        self.assertIsNone(merge_commit)
        self.assertIsNone(strategy)
        self.assertIsNone(match_kind)

    def test_resolve_merge_commit_still_resolves_real_merge(self):
        merge_commit, strategy, match_kind = aet_state.resolve_merge_commit(
            "merged-task",
            cwd=self.cwd,
            trunk_branch="main",
            use_diff_fallback=False,
            base_commit=self.repo.base,
        )
        self.assertEqual(merge_commit, self.repo.merged_tip)
        self.assertEqual(strategy, "regular")
        self.assertEqual(match_kind, "ancestry")

    # -- transition guards (ADR-064 decision 5) ----------------------------

    def test_validate_transition_refuses_merged_without_evidence(self):
        ok, msg = aet_state.validate_transition(
            {
                "id": "t",
                "state": "awaiting_merge",
                "branch": "empty-task",
                "base_commit": self.repo.base,
            },
            "awaiting_merge",
            "merged",
            cwd=self.cwd,
            trunk_branch="main",
        )
        self.assertFalse(ok)
        self.assertIn("no merge evidence", msg)

    def test_validate_transition_allows_merged_with_evidence(self):
        ok, _ = aet_state.validate_transition(
            {
                "id": "t",
                "state": "awaiting_merge",
                "branch": "merged-task",
                "base_commit": self.repo.base,
            },
            "awaiting_merge",
            "merged",
            cwd=self.cwd,
            trunk_branch="main",
        )
        self.assertTrue(ok)

    def test_branch_has_own_commits(self):
        self.assertFalse(
            aet_state.branch_has_own_commits("empty-task", self.repo.base, cwd=self.cwd)
        )
        self.assertTrue(
            aet_state.branch_has_own_commits("merged-task", self.repo.base, cwd=self.cwd)
        )
        # Fails closed on an unknown or unresolvable base.
        self.assertFalse(
            aet_state.branch_has_own_commits("merged-task", None, cwd=self.cwd)
        )
        self.assertFalse(
            aet_state.branch_has_own_commits("merged-task", "nope", cwd=self.cwd)
        )


class TestBaseCommitRecording(unittest.TestCase):
    """base_commit is stamped at branch creation, once (ADR-064 decision 1)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = MergeEvidenceRepo(Path(self._tmp.name) / "repo")

    def test_resolve_base_commit_returns_branch_tip(self):
        from aet.queue import resolve_base_commit

        self.assertEqual(
            resolve_base_commit(str(self.repo.root), "empty-task"), self.repo.base
        )

    def test_resolve_base_commit_is_none_for_unknown_branch(self):
        from aet.queue import resolve_base_commit

        self.assertIsNone(resolve_base_commit(str(self.repo.root), "no-such-branch"))
        self.assertIsNone(resolve_base_commit(str(self.repo.root), None))

    def test_record_task_meta_stamps_base_commit(self):
        from aet.queue import record_task_meta

        queue = [{"id": "t1"}]
        record_task_meta(queue, "t1", ".worktrees/t1", "t1", base_commit="base0000")
        self.assertEqual(queue[0]["base_commit"], "base0000")

    def test_record_task_meta_does_not_overwrite_an_existing_base(self):
        """A task re-recorded after committing must keep its original origin."""
        from aet.queue import record_task_meta

        queue = [{"id": "t1", "base_commit": "original"}]
        record_task_meta(queue, "t1", ".worktrees/t1", "t1", base_commit="later-tip")
        self.assertEqual(queue[0]["base_commit"], "original")

    def test_record_task_meta_stamps_integration_branch(self):
        from aet.queue import record_task_meta

        queue = [{"id": "t1"}]
        record_task_meta(
            queue, "t1", ".worktrees/t1", "t1", base_commit="base0000", integration_branch="epic-01"
        )
        self.assertEqual(queue[0]["integration_branch"], "epic-01")

    def test_record_task_meta_does_not_overwrite_an_existing_integration_branch(self):
        """A task re-recorded must keep its original stamped integration branch."""
        from aet.queue import record_task_meta

        queue = [{"id": "t1", "integration_branch": "original-epic"}]
        record_task_meta(
            queue, "t1", ".worktrees/t1", "t1", base_commit="base0000", integration_branch="new-epic"
        )
        self.assertEqual(queue[0]["integration_branch"], "original-epic")

    def test_recorded_base_makes_a_real_merge_derivable(self):
        """End to end: a task recorded at creation derives merged once merged."""
        from aet.queue import record_task_meta, resolve_base_commit

        queue = [{"id": "t1"}]
        # The orchestrator records at branch creation, before any commit.
        record_task_meta(
            queue,
            "t1",
            ".worktrees/t1",
            "merged-task",
            base_commit=resolve_base_commit(str(self.repo.root), "empty-task"),
        )
        task = dict(queue[0], spec={})
        derived = aet_state.derive_status(
            task, cwd=str(self.repo.root), trunk_branch="main"
        )
        self.assertEqual(derived["derived_status"], "merged")


if __name__ == "__main__":
    unittest.main()
