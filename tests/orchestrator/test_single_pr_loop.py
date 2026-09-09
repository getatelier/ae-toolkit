"""End-to-end test for single-pr completion loop.

Runs a two-task epic in ``single-pr`` mode, asserts that:

- the integration branch is the only branch pushed to origin (R-15);
- completing the first task squash-merges it into the integration branch,
  making the next task's worktree start from the live tip (R-16, R-17);
- no per-task branch is reachable on origin.
"""

from __future__ import annotations

import importlib.machinery
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


def _init_git_repo(repo_root: str, origin_root: str) -> None:
    """Initialize a git repo with main and a bare origin remote."""
    subprocess.run(["git", "init", "--bare", "-q", origin_root], check=True)
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
        ["git", "-C", repo_root, "remote", "add", "origin", origin_root],
        check=True,
    )
    subprocess.run(
        ["git", "-C", repo_root, "push", "-q", "-u", "origin", "main"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", repo_root, "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )


def _create_integration_branch(repo_root: str, name: str = "epic-01") -> None:
    """Create and push an integration branch from the current HEAD."""
    subprocess.run(
        ["git", "-C", repo_root, "checkout", "-q", "-b", name],
        check=True,
    )
    subprocess.run(
        ["git", "-C", repo_root, "push", "-q", "-u", "origin", name],
        check=True,
    )
    subprocess.run(
        ["git", "-C", repo_root, "update-ref", f"refs/remotes/origin/{name}", "HEAD"],
        check=True,
    )
    # Return to main so the repo root is not on the epic branch.
    subprocess.run(["git", "-C", repo_root, "checkout", "-q", "main"], check=True)


def _write_plan(repo_root: str, task_id: str, blocked_by: list[str] | None = None) -> str:
    plan_file = os.path.join(repo_root, "docs", "plans", f"{task_id}-plan.md")
    Path(plan_file).parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {"id": task_id}
    if blocked_by:
        frontmatter["blocked_by"] = blocked_by
    Path(plan_file).write_text(
        f"---\n{json.dumps(frontmatter)}\n---\n\n# {task_id}\n\n_Stage: plan-approved_\n",
        encoding="utf-8",
    )
    return plan_file


def _add_commit_to_worktree(worktree_dir: str, filename: str, content: str) -> None:
    Path(worktree_dir, filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", worktree_dir, "add", "."], check=True)
    subprocess.run(
        ["git", "-C", worktree_dir, "commit", "-q", "-m", f"add {filename}"],
        check=True,
    )


def _remote_heads(repo_root: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", repo_root, "ls-remote", "--heads", "origin"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.split()[1].removeprefix("refs/heads/") for line in result.stdout.splitlines()]


class TestSinglePrLoop(unittest.TestCase):
    def test_two_task_epic_integration_branch_only_remote(self):
        """R-15, R-16, R-17: local integration, live tip, no task branches on origin."""
        self.maxDiff = None
        with tempfile.TemporaryDirectory() as repo_root, tempfile.TemporaryDirectory() as origin_root:
            _init_git_repo(repo_root, origin_root)

            Path(repo_root, ".agents").mkdir(parents=True, exist_ok=True)
            Path(repo_root, ".agents", "aet-config.json").write_text(
                json.dumps(
                    {
                        "trunk_branch": "main",
                        "integration_branch": "epic-01",
                        "integration_mode": "single-pr",
                    }
                ),
                encoding="utf-8",
            )

            plan_a = _write_plan(repo_root, "task-a")
            _write_plan(repo_root, "task-b", blocked_by=["task-a"])

            subprocess.run(["git", "-C", repo_root, "add", "."], check=True)
            subprocess.run(
                ["git", "-C", repo_root, "commit", "-q", "-m", "add plans"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo_root, "update-ref", "refs/remotes/origin/main", "HEAD"],
                check=True,
            )
            _create_integration_branch(repo_root, "epic-01")

            # Create task-a worktree with a real commit, then run process_task in single-pr.
            worktree_a = orchestrator.create_worktree(
                repo_root, "task-a", base_branch="origin/epic-01"
            )
            _add_commit_to_worktree(worktree_a, "task-a.txt", "task-a work")

            env = os.environ.copy()
            env["AET_PROJECT_ID"] = "demo-project"
            env["AET_INTEGRATION_VALIDATE_CMD"] = "true"

            with patch.dict(os.environ, env, clear=True):
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
                                    result = orchestrator.process_task(
                                        {"id": "task-a", "plan_file": plan_a},
                                        repo_root,
                                        _FAKE_ADAPTER,
                                        "standard",
                                        worktree_dir=worktree_a,
                                        integration_mode="single-pr",
                                        base_branch="origin/epic-01",
                                    )

            self.assertTrue(result)

            # task-a branch should have been deleted locally.
            self.assertFalse(
                Path(repo_root, ".git", "refs", "heads", "task-a").exists()
            )

            # Integration branch should exist on origin; task-a should not.
            remote_heads = _remote_heads(repo_root)
            self.assertIn("epic-01", remote_heads)
            self.assertNotIn("task-a", remote_heads)

            # epic-01 should contain the squash-merged task-a commit.
            result = subprocess.run(
                ["git", "-C", repo_root, "log", "origin/epic-01", "--oneline"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("Integrate task-a", result.stdout)

            # Create task-b worktree from the live tip and assert it sees task-a.
            worktree_b = orchestrator.create_worktree(
                repo_root, "task-b", base_branch="origin/epic-01"
            )
            self.assertTrue(
                Path(worktree_b, "task-a.txt").exists(),
                "task-b worktree should include task-a's integrated change",
            )

            # No push of task-b should have happened yet.
            remote_heads = _remote_heads(repo_root)
            self.assertNotIn("task-b", remote_heads)

    def test_epic_mismatch_halts_before_worktree_creation(self):
        """Task 5 (R-9): Resuming a task stamped to another epic exits non-zero,
        names both branches and remedies, leaves worktree list and branch list unchanged.
        """

        with tempfile.TemporaryDirectory() as repo_root, tempfile.TemporaryDirectory() as origin_root:
            _init_git_repo(repo_root, origin_root)

            Path(repo_root, ".agents").mkdir(parents=True, exist_ok=True)
            queue_file = os.path.join(repo_root, ".agents", "aet-queue")
            history_file = os.path.join(repo_root, ".agents", "work-history.jsonl")
            config_file = os.path.join(repo_root, ".agents", "aet-config.json")
            Path(config_file).write_text(
                json.dumps(
                    {
                        "trunk_branch": "main",
                        "integration_branch": "epic-02",
                        "integration_mode": "single-pr",
                    }
                ),
                encoding="utf-8",
            )

            plan_a = _write_plan(repo_root, "task-a")
            subprocess.run(["git", "-C", repo_root, "add", "."], check=True)
            subprocess.run(
                ["git", "-C", repo_root, "commit", "-q", "-m", "add config and plan"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo_root, "update-ref", "refs/remotes/origin/main", "HEAD"],
                check=True,
            )
            _create_integration_branch(repo_root, "epic-01")
            _create_integration_branch(repo_root, "epic-02")


            from aet.backends.factory import create_backend

            backend = create_backend(
                config_path=config_file,
                queue_file=queue_file,
                history_file=history_file,
            )
            # Stamped to epic-01, but config / envelope points to epic-02
            task_record = {
                "id": "task-a",
                "plan_file": plan_a,
                "state": "ready",
                "integration_branch": "epic-01",
            }
            backend.save([task_record])

            # Record initial worktree and branch lists
            initial_worktrees = subprocess.run(
                ["git", "-C", repo_root, "worktree", "list", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            initial_branches = subprocess.run(
                ["git", "-C", repo_root, "branch"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout

            # Run batch
            args = orchestrator.argparse.Namespace(
                queue_file=queue_file,
                repo_root=repo_root,
                max_jobs=1,
                isolation="minimal",
                task_timeout=3600,
                heartbeat_interval=60,
                on_failure="continue",
                cli_bin=None,
                base=None,
            )

            import io
            from contextlib import redirect_stdout

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = orchestrator.run_batch(args, _FAKE_ADAPTER)

            output = out.getvalue()
            self.assertEqual(exit_code, 1)
            self.assertIn("Epic mismatch for task 'task-a'", output)
            self.assertIn("epic-01", output)
            self.assertIn("epic-02", output)
            self.assertIn("aet epic set epic-01", output)
            self.assertIn("aet state reset task-a", output)

            # Assert worktrees and branches are unchanged
            final_worktrees = subprocess.run(
                ["git", "-C", repo_root, "worktree", "list", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            final_branches = subprocess.run(
                ["git", "-C", repo_root, "branch"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout

            self.assertEqual(initial_worktrees, final_worktrees)
            self.assertEqual(initial_branches, final_branches)


if __name__ == "__main__":
    unittest.main()
