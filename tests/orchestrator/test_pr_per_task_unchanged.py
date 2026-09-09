"""Regression guard: pr-per-task git command sequence matches the baseline.

This test asserts that, with ``integration_mode == 'pr-per-task'`` and
``integration_branch == trunk_branch``, the orchestrator issues exactly the
expected git command sequence.  The assertion is a command-sequence check,
not a code-read check, satisfying R-14's regression guard.

Baseline updated by owb-01 (R-19): the working plan is rendered from the
task record instead of seeded with a standalone commit, and ``docs/plans/``
is no longer overlaid by ``copy_untracked_files``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from aet.cli_adapter import CLIAdapter

# Load the orchestrator script (no .py extension) as a module.
_ORCHESTRATOR_BIN = Path(__file__).parents[2] / "src" / "aet" / "cli" / "orchestrator.py"
_orchestrator_loader = importlib.machinery.SourceFileLoader(
    "orchestrator", str(_ORCHESTRATOR_BIN)
)
_spec = importlib.util.spec_from_loader("orchestrator", _orchestrator_loader)
orchestrator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orchestrator)

pytestmark = pytest.mark.xdist_group("git-repo")


_FAKE_ADAPTER = CLIAdapter(
    name="test",
    bin="echo",
    prompt_flag="-p",
    workdir_flag=None,
    headless_flag=None,
)


def _init_git_repo(repo_root: str) -> None:
    """Initialize a git repo with a clean main branch tracking origin."""
    subprocess.run(["git", "init", "-q", repo_root], check=True)
    subprocess.run(
        ["git", "-C", repo_root, "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", repo_root, "config", "user.name", "Test User"],
        check=True,
    )
    Path(repo_root, "README.md").write_text("# test", encoding="utf-8")
    subprocess.run(["git", "-C", repo_root, "add", "."], check=True)
    subprocess.run(
        ["git", "-C", repo_root, "commit", "-q", "-m", "initial"],
        check=True,
    )
    subprocess.run(["git", "-C", repo_root, "branch", "-M", "main"], check=True)
    subprocess.run(
        ["git", "-C", repo_root, "remote", "add", "origin", repo_root],
        check=True,
    )
    subprocess.run(
        ["git", "-C", repo_root, "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )


class _GitCommandRecorder:
    """Record subprocess.run calls that start with ``git``."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self._real_run = subprocess.run

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        return self._real_run(cmd, **kwargs)


def _git_only(calls: list[list[str]]) -> list[list[str]]:
    """Return calls whose executable is ``git``."""
    return [c for c in calls if c and c[0] == "git"]


def _normalize(calls: list[list[str]], repo_root: str, worktree_dir: str) -> list[list[str]]:
    """Replace absolute paths with placeholders so baselines are stable."""
    return [
        [
            part.replace(str(worktree_dir), "<worktree>")
            .replace(str(repo_root), "<repo>")
            for part in call
        ]
        for call in calls
    ]


class TestPrPerTaskGitSequenceUnchanged(unittest.TestCase):
    """R-14 regression guard: Scenario A uses the pre-change git sequence."""

    def test_process_task_pr_per_task_git_sequence_matches_baseline(self):
        self.maxDiff = None
        with tempfile.TemporaryDirectory() as repo_root:
            _init_git_repo(repo_root)
            plan_file = os.path.join(repo_root, "docs", "plans", "demo-plan.md")
            Path(plan_file).parent.mkdir(parents=True, exist_ok=True)
            Path(plan_file).write_text(
                "---\nid: demo\n---\n\n# Demo\n\n_Stage: plan-approved_\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", repo_root, "add", "."], check=True)
            subprocess.run(
                ["git", "-C", repo_root, "commit", "-q", "-m", "add plan"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo_root, "update-ref", "refs/remotes/origin/main", "HEAD"],
                check=True,
            )

            Path(repo_root, ".agents").mkdir(parents=True, exist_ok=True)
            Path(repo_root, ".agents", "aet-config.json").write_text(
                json.dumps(
                    {
                        "trunk_branch": "main",
                        "integration_branch": "main",
                        "integration_mode": "pr-per-task",
                    }
                ),
                encoding="utf-8",
            )

            task = {"id": "demo", "title": "Demo", "plan_file": plan_file}
            recorder = _GitCommandRecorder()

            env = os.environ.copy()
            env["AET_PROJECT_ID"] = "demo-project"

            with patch.dict(os.environ, env, clear=True):
                with patch.object(subprocess, "run", side_effect=recorder):
                    with patch.object(
                        orchestrator, "run_stage", return_value=(0, None, None, "")
                    ):
                        with patch.object(
                            orchestrator,
                            "run_stage_group",
                            return_value=(0, None, None, None),
                        ):
                            with patch.object(
                                orchestrator,
                                "verify_branch_has_commits",
                                return_value=(True, ""),
                            ):
                                with patch.object(
                                    orchestrator,
                                    "verify_stage_advancement",
                                    return_value=(True, ""),
                                ):
                                    with patch.object(
                                        orchestrator,
                                        "_require_passing_verdict",
                                        return_value=True,
                                    ):
                                        with patch.object(
                                            orchestrator,
                                            "_record_stage",
                                            return_value=True,
                                        ):
                                            orchestrator.process_task(
                                                task,
                                                repo_root,
                                                _FAKE_ADAPTER,
                                                "standard",
                                                integration_mode="pr-per-task",
                                            )

            worktree_dir = os.path.join(repo_root, ".worktrees", "demo")
            git_calls = _normalize(_git_only(recorder.calls), repo_root, worktree_dir)

            expected = [
                # Read-only probe: a base is only fetched when its leading
                # segment names a configured remote, so `fix/x` is not mistaken
                # for remote `fix` + ref `x`.
                ["git", "-C", "<repo>", "remote"],
                ["git", "-C", "<repo>", "fetch", "origin", "main"],
                ["git", "-C", "<repo>", "rev-parse", "origin/main"],
                [
                    "git",
                    "-C",
                    "<repo>",
                    "show-ref",
                    "--verify",
                    "refs/heads/demo",
                ],
                [
                    "git",
                    "-C",
                    "<repo>",
                    "worktree",
                    "add",
                    "<worktree>",
                    "-b",
                    "demo",
                    "origin/main",
                ],
                [
                    "git",
                    "-C",
                    "<repo>",
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "docs/prds/",
                    "docs/adr/",
                    "docs/audits/",
                    "docs/retros/",
                    "docs/product-briefs/",
                ],
                # No seed check: the plan is rendered from the task record
                # (R-19), so no cat-file probe and no seed commit.
                # Telemetry diff stats emitted after each stage/session group.
                ["git", "-C", "<worktree>", "diff", "--name-only", "origin/main...HEAD"],
                ["git", "-C", "<worktree>", "rev-list", "--count", "origin/main..HEAD"],
                ["git", "-C", "<worktree>", "diff", "--name-only", "origin/main...HEAD"],
                ["git", "-C", "<worktree>", "rev-list", "--count", "origin/main..HEAD"],
                ["git", "-C", "<worktree>", "diff", "--name-only", "origin/main...HEAD"],
                ["git", "-C", "<worktree>", "rev-list", "--count", "origin/main..HEAD"],
            ]

            self.assertEqual(git_calls, expected)

    def test_epic_declaration_is_inert_in_pr_per_task(self):
        """R-4: With integration_mode == pr-per-task and an active epic set, resolution matches no-epic result."""
        from aet.backends.factory import create_backend
        from aet.branch_ref import resolve_integration_branch_for_task

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = os.path.join(temp_dir, "repo")
            os.makedirs(repo_root)
            _init_git_repo(repo_root)

            # Set epic in envelope
            backend = create_backend(
                queue_file=os.path.join(repo_root, ".agents", "aet-queue"),
                history_file=os.path.join(repo_root, ".agents", "work-history.jsonl"),
            )
            backend.set_epic(branch="epic-branch", title="My Epic")
            backend.close()

            config = {"trunk_branch": "main"}
            task = {
                "id": "task-1",
                "spec": {"frontmatter": {"source_prd": "docs/prds/alpha.md"}},
            }

            ref_with_epic = resolve_integration_branch_for_task(
                repo_root, config, task, "pr-per-task"
            )

            # In pr-per-task mode, epic declaration in envelope must be ignored
            self.assertEqual(ref_with_epic.ref, "main")
            self.assertEqual(ref_with_epic.provenance, "trunk")


if __name__ == "__main__":
    unittest.main()
