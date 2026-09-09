"""PRD-derived integration branch for single-pr mode (R-17).

When ``integration_mode`` is ``single-pr`` and no static ``integration_branch``
is configured, the epic integration branch is derived from the task's PRD so
that concurrent PRDs each carry their own branch and PR.
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


def _write_prd(repo_root: str, name: str) -> Path:
    """Write a PRD file and return its path."""
    prd_file = Path(repo_root, "docs", "prds", f"{name}.md")
    prd_file.parent.mkdir(parents=True, exist_ok=True)
    prd_file.write_text(f"# {name}\n\nRequirement: R-17\n", encoding="utf-8")
    return prd_file


def _write_plan(repo_root: str, task_id: str, prd_name: str) -> str:
    """Write a plan file that references a PRD and return its path."""
    plan_file = Path(repo_root, "docs", "plans", f"{task_id}.md")
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(
        f"---\nid: {task_id}\n---\n\n"
        f"# {task_id}\n\n"
        "## Context\n\n"
        f"- PRD: `docs/prds/{prd_name}.md`\n\n"
        "## Task List\n\n"
        "- [ ] Implement the thing\n\n"
        "_Stage: plan-approved_\n",
        encoding="utf-8",
    )
    return str(plan_file)


def _create_integration_branch(repo_root: str, name: str) -> None:
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
    subprocess.run(["git", "-C", repo_root, "checkout", "-q", "main"], check=True)


def _add_commit_to_worktree(worktree_dir: str, filename: str, content: str) -> None:
    Path(worktree_dir, filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", worktree_dir, "add", "."], check=True)
    subprocess.run(
        ["git", "-C", worktree_dir, "commit", "-q", "-m", f"add {filename}"],
        check=True,
    )


def _remote_heads(repo_root: str) -> set[str]:
    result = subprocess.run(
        ["git", "-C", repo_root, "ls-remote", "--heads", "origin"],
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.split()[1].removeprefix("refs/heads/") for line in result.stdout.splitlines()}


def _integration_log(repo_root: str, branch: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", repo_root, "log", f"origin/{branch}", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


class TestPrdDerivedIntegrationBranch(unittest.TestCase):
    def test_single_prd_derives_integration_branch_from_prd(self):
        """R-17: a single-pr task with no static integration_branch uses its PRD stem."""
        with tempfile.TemporaryDirectory() as repo_root, tempfile.TemporaryDirectory() as origin_root:
            _init_git_repo(repo_root, origin_root)

            _write_prd(repo_root, "alpha-prd")
            plan_a = _write_plan(repo_root, "task-a", "alpha-prd")

            Path(repo_root, ".agents").mkdir(parents=True, exist_ok=True)
            Path(repo_root, ".agents", "aet-config.json").write_text(
                json.dumps(
                    {
                        "trunk_branch": "main",
                        "integration_mode": "single-pr",
                    }
                ),
                encoding="utf-8",
            )

            subprocess.run(["git", "-C", repo_root, "add", "."], check=True)
            subprocess.run(
                ["git", "-C", repo_root, "commit", "-q", "-m", "add prd and plan"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo_root, "push", "-q", "origin", "main"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo_root, "update-ref", "refs/remotes/origin/main", "HEAD"],
                check=True,
            )
            _create_integration_branch(repo_root, "alpha-prd")

            worktree_a = orchestrator.create_worktree(
                repo_root, "task-a", base_branch="origin/main"
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
                                        base_branch="origin/main",
                                    )

            self.assertTrue(result)

            # The PRD-derived integration branch should exist on origin.
            remote_heads = _remote_heads(repo_root)
            self.assertIn("alpha-prd", remote_heads)
            # No per-task branch should reach origin.
            self.assertNotIn("task-a", remote_heads)

            log = _integration_log(repo_root, "alpha-prd")
            self.assertIn("Integrate task-a", log)

    def test_two_prds_produce_two_integration_branches(self):
        """R-17: concurrent PRDs each get their own integration branch and PR."""
        self.maxDiff = None
        with tempfile.TemporaryDirectory() as repo_root, tempfile.TemporaryDirectory() as origin_root:
            _init_git_repo(repo_root, origin_root)

            _write_prd(repo_root, "alpha-prd")
            _write_prd(repo_root, "beta-prd")
            plan_a = _write_plan(repo_root, "task-a", "alpha-prd")
            plan_b = _write_plan(repo_root, "task-b", "beta-prd")

            Path(repo_root, ".agents").mkdir(parents=True, exist_ok=True)
            Path(repo_root, ".agents", "aet-config.json").write_text(
                json.dumps(
                    {
                        "trunk_branch": "main",
                        "integration_mode": "single-pr",
                    }
                ),
                encoding="utf-8",
            )

            subprocess.run(["git", "-C", repo_root, "add", "."], check=True)
            subprocess.run(
                ["git", "-C", repo_root, "commit", "-q", "-m", "add prds and plans"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo_root, "push", "-q", "origin", "main"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo_root, "update-ref", "refs/remotes/origin/main", "HEAD"],
                check=True,
            )
            _create_integration_branch(repo_root, "alpha-prd")
            _create_integration_branch(repo_root, "beta-prd")

            worktree_a = orchestrator.create_worktree(
                repo_root, "task-a", base_branch="origin/main"
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
                                    result_a = orchestrator.process_task(
                                        {"id": "task-a", "plan_file": plan_a},
                                        repo_root,
                                        _FAKE_ADAPTER,
                                        "standard",
                                        worktree_dir=worktree_a,
                                        integration_mode="single-pr",
                                        base_branch="origin/main",
                                    )

            self.assertTrue(result_a)

            worktree_b = orchestrator.create_worktree(
                repo_root, "task-b", base_branch="origin/main"
            )
            _add_commit_to_worktree(worktree_b, "task-b.txt", "task-b work")

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
                                    result_b = orchestrator.process_task(
                                        {"id": "task-b", "plan_file": plan_b},
                                        repo_root,
                                        _FAKE_ADAPTER,
                                        "standard",
                                        worktree_dir=worktree_b,
                                        integration_mode="single-pr",
                                        base_branch="origin/main",
                                    )

            self.assertTrue(result_b)

            remote_heads = _remote_heads(repo_root)
            self.assertIn("alpha-prd", remote_heads)
            self.assertIn("beta-prd", remote_heads)
            self.assertNotIn("task-a", remote_heads)
            self.assertNotIn("task-b", remote_heads)

            alpha_log = _integration_log(repo_root, "alpha-prd")
            beta_log = _integration_log(repo_root, "beta-prd")
            self.assertIn("Integrate task-a", alpha_log)
            self.assertIn("Integrate task-b", beta_log)
            self.assertNotIn("Integrate task-b", alpha_log)
            self.assertNotIn("Integrate task-a", beta_log)

    def test_pr_per_task_scenario_a_unchanged(self):
        """ADR-045 Scenario A: pr-per-task with integration_branch == trunk is unchanged."""
        with tempfile.TemporaryDirectory() as repo_root, tempfile.TemporaryDirectory() as origin_root:
            _init_git_repo(repo_root, origin_root)

            _write_prd(repo_root, "alpha-prd")
            plan_a = _write_plan(repo_root, "task-a", "alpha-prd")

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

            subprocess.run(["git", "-C", repo_root, "add", "."], check=True)
            subprocess.run(
                ["git", "-C", repo_root, "commit", "-q", "-m", "add prd and plan"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo_root, "push", "-q", "origin", "main"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo_root, "update-ref", "refs/remotes/origin/main", "HEAD"],
                check=True,
            )

            worktree_a = orchestrator.create_worktree(
                repo_root, "task-a", base_branch="origin/main"
            )
            _add_commit_to_worktree(worktree_a, "task-a.txt", "task-a work")

            env = os.environ.copy()
            env["AET_PROJECT_ID"] = "demo-project"

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
                                        integration_mode="pr-per-task",
                                        base_branch="origin/main",
                                    )

            self.assertTrue(result)

            # The task branch should be the one that exists locally; no PRD-derived
            # integration branch should have been created in pr-per-task mode.
            self.assertTrue(
                Path(repo_root, ".git", "refs", "heads", "task-a").exists()
            )
            remote_heads = _remote_heads(repo_root)
            self.assertNotIn("alpha-prd", remote_heads)

    def test_declared_prd_branch_outranks_stem(self):
        """R-5: A PRD declaring branch outranks its filename stem, and a plain PRD still derives the stem."""
        from aet.branch_ref import resolve_integration_branch_for_task

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = os.path.join(temp_dir, "repo")
            os.makedirs(repo_root)
            _init_git_repo(repo_root, os.path.join(temp_dir, "origin.git"))

            # PRD declaring a custom branch
            declared_prd = Path(repo_root, "docs", "prds", "my-feature-stem.md")
            declared_prd.parent.mkdir(parents=True, exist_ok=True)
            declared_prd.write_text(
                "---\nbranch: declared-custom-branch\n---\n# PRD\n", encoding="utf-8"
            )

            # Plain PRD
            plain_prd = Path(repo_root, "docs", "prds", "plain-feature-stem.md")
            plain_prd.write_text("# Plain PRD\n", encoding="utf-8")

            task_declared = {"spec": {"frontmatter": {"source_prd": "docs/prds/my-feature-stem.md"}}}
            task_plain = {"spec": {"frontmatter": {"source_prd": "docs/prds/plain-feature-stem.md"}}}

            ref_declared = resolve_integration_branch_for_task(
                repo_root, {}, task_declared, "single-pr"
            )
            self.assertEqual(ref_declared.ref, "declared-custom-branch")
            self.assertEqual(ref_declared.provenance, "document")

            ref_plain = resolve_integration_branch_for_task(
                repo_root, {}, task_plain, "single-pr"
            )
            self.assertEqual(ref_plain.ref, "plain-feature-stem")
            self.assertEqual(ref_plain.provenance, "prd")


if __name__ == "__main__":
    unittest.main()
