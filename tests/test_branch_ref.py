"""Tests for branch_ref resolution."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aet.branch_ref import (
    resolve_base_ref,
    resolve_integration_branch,
    resolve_trunk_branch,
)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )


def test_trunk_branch_config_wins(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    ref = resolve_trunk_branch(repo, {"trunk_branch": "release"})

    assert ref.ref == "release"
    assert ref.provenance == "config"


def test_trunk_branch_detected_from_origin_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/dev"],
        check=True,
        capture_output=True,
    )

    ref = resolve_trunk_branch(repo, {})

    assert ref.ref == "dev"
    assert ref.provenance == "detected"


def test_trunk_branch_fallback_when_origin_head_unset(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    ref = resolve_trunk_branch(repo, {})

    assert ref.ref == "main"
    assert ref.provenance == "fallback"


def test_integration_branch_cli_base_wins(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    ref = resolve_integration_branch(
        repo,
        {"integration_branch": "feature/config"},
        cli_base="feature/cli",
    )

    assert ref.ref == "feature/cli"
    assert ref.provenance == "cli"


def test_integration_branch_env_beats_config(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    monkeypatch.setenv("AET_WORK_BASE_BRANCH", "feature/env")

    ref = resolve_integration_branch(repo, {"integration_branch": "feature/config"})

    assert ref.ref == "feature/env"
    assert ref.provenance == "env"


def test_integration_branch_config_beats_trunk(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    ref = resolve_integration_branch(repo, {"integration_branch": "feature/config"})

    assert ref.ref == "feature/config"
    assert ref.provenance == "config"


def test_integration_branch_falls_back_to_trunk(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    ref = resolve_integration_branch(repo, {})

    assert ref.ref == "main"
    assert ref.provenance == "trunk"


def _set_remote_ref(repo: Path, ref: str) -> None:
    """Point ``refs/remotes/<ref>`` at HEAD, as a fetch would."""
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", f"refs/remotes/{ref}", head],
        check=True,
        capture_output=True,
    )


def test_base_ref_prefers_remote_tracking_ref(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _set_remote_ref(repo, "origin/main")

    assert resolve_base_ref(repo, "main") == "origin/main"


def test_base_ref_falls_back_to_local_when_no_remote(tmp_path: Path) -> None:
    """A project with no remote must still get a usable worktree base."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    assert resolve_base_ref(repo, "main") == "main"


def test_base_ref_falls_back_when_integration_branch_is_unpushed(tmp_path: Path) -> None:
    """single-pr integration branches are often local-only for their first run."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _set_remote_ref(repo, "origin/main")
    subprocess.run(
        ["git", "-C", str(repo), "branch", "fix/catalog-job-runtime"],
        check=True,
        capture_output=True,
    )

    assert resolve_base_ref(repo, "fix/catalog-job-runtime") == "fix/catalog-job-runtime"


def test_base_ref_leaves_an_already_qualified_ref_alone(tmp_path: Path) -> None:
    """``--base origin/main`` must not become ``origin/origin/main``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _set_remote_ref(repo, "origin/main")

    assert resolve_base_ref(repo, "origin/main") == "origin/main"


def test_resolution_order_for_single_pr(monkeypatch, tmp_path: Path) -> None:
    """R-4: Test each step of the 8-step resolution order in single-pr mode."""
    from aet.backends.factory import create_backend
    from aet.branch_ref import resolve_integration_branch_for_task

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    # Setup PRD file with declared branch
    prd_path = repo / "docs" / "prds" / "my-prd-stem.md"
    prd_path.parent.mkdir(parents=True, exist_ok=True)
    prd_path.write_text(
        "---\nbranch: feature/doc-declared\npr_title: Doc PR Title\n---\n\n# PRD\n",
        encoding="utf-8",
    )

    # Setup PRD file without declared branch
    plain_prd = repo / "docs" / "prds" / "plain-prd-stem.md"
    plain_prd.write_text("# Plain PRD\n", encoding="utf-8")

    # Setup envelope epic
    backend = create_backend(
        queue_file=str(repo / ".agents" / "aet-queue"),
        history_file=str(repo / ".agents" / "work-history.jsonl"),
    )
    backend.set_epic(branch="epic/envelope-branch", title="Envelope Epic")
    backend.close()

    config = {"integration_branch": "config/branch", "trunk_branch": "main"}
    task_with_doc = {"spec": {"frontmatter": {"source_prd": "docs/prds/my-prd-stem.md"}}}
    task_with_plain_prd = {"spec": {"frontmatter": {"source_prd": "docs/prds/plain-prd-stem.md"}}}
    task_no_prd = {}

    # 1. CLI override wins over everything
    monkeypatch.setenv("AET_WORK_BASE_BRANCH", "env/branch")
    task_full = {**task_with_doc, "integration_branch": "stamp/branch"}
    ref = resolve_integration_branch_for_task(
        repo, config, task_full, "single-pr", cli_base="cli/branch"
    )
    assert ref.ref == "cli/branch"
    assert ref.provenance == "cli"

    # 2. Env wins over stamp, document, epic, prd, config, trunk
    ref = resolve_integration_branch_for_task(
        repo, config, task_full, "single-pr", cli_base=None
    )
    assert ref.ref == "env/branch"
    assert ref.provenance == "env"

    monkeypatch.delenv("AET_WORK_BASE_BRANCH", raising=False)

    # 3. Task record stamp wins over document, epic, prd, config, trunk
    ref = resolve_integration_branch_for_task(
        repo, config, task_full, "single-pr", cli_base=None
    )
    assert ref.ref == "stamp/branch"
    assert ref.provenance == "stamp"

    # 4. Parent document declared branch wins over epic, prd, config, trunk
    ref = resolve_integration_branch_for_task(
        repo, config, task_with_doc, "single-pr", cli_base=None
    )
    assert ref.ref == "feature/doc-declared"
    assert ref.provenance == "document"

    # 5. Envelope active epic wins over prd stem, config, trunk
    ref = resolve_integration_branch_for_task(
        repo, config, task_with_plain_prd, "single-pr", cli_base=None
    )
    assert ref.ref == "epic/envelope-branch"
    assert ref.provenance == "epic"

    # Clear epic from envelope
    backend = create_backend(
        queue_file=str(repo / ".agents" / "aet-queue"),
        history_file=str(repo / ".agents" / "work-history.jsonl"),
    )
    backend.clear_epic()
    backend.close()

    # 6. PRD filename stem wins over config, trunk
    ref = resolve_integration_branch_for_task(
        repo, config, task_with_plain_prd, "single-pr", cli_base=None
    )
    assert ref.ref == "plain-prd-stem"
    assert ref.provenance == "prd"

    # 7. Config integration_branch wins over trunk
    ref = resolve_integration_branch_for_task(
        repo, config, task_no_prd, "single-pr", cli_base=None
    )
    assert ref.ref == "config/branch"
    assert ref.provenance == "config"

    # 8. Trunk fallback
    ref = resolve_integration_branch_for_task(
        repo, {}, task_no_prd, "single-pr", cli_base=None
    )
    assert ref.ref == "main"
    assert ref.provenance == "trunk"


def test_declared_branch_is_used_verbatim(tmp_path: Path) -> None:
    """R-6: A declared branch containing slashes is used verbatim without alteration."""
    from aet.branch_ref import resolve_integration_branch_for_task

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    prd_path = repo / "docs" / "prds" / "feature-prd.md"
    prd_path.parent.mkdir(parents=True, exist_ok=True)
    prd_path.write_text(
        "---\nbranch: feature/custom/deep-branch-name\n---\n# PRD\n",
        encoding="utf-8",
    )

    task = {"spec": {"frontmatter": {"source_prd": "docs/prds/feature-prd.md"}}}
    ref = resolve_integration_branch_for_task(repo, {}, task, "single-pr")

    assert ref.ref == "feature/custom/deep-branch-name"
    assert ref.provenance == "document"
