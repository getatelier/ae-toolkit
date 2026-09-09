"""`aet setup` subcommand group."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import typer

from aet.backends.factory import (
    resolve_config_with_source,
    resolve_integration_mode_with_provenance,
)
from aet.branch_ref import resolve_integration_branch, resolve_trunk_branch
from aet.project_id import resolve_repo_root
from aet.worktree import AET_IGNORED_PATHS, AET_RETIRED_IGNORED_PATHS

app = typer.Typer(help="Setup and bootstrap commands.")


def _format_branch_provenance(provenance: str, config_source: str) -> str:
    """Render a branch resolver provenance, annotating config with its layer."""
    if provenance == "config":
        return f"config ({config_source})"
    return provenance


def _repo_root() -> Path:
    """Return the absolute path to the AE Toolkit repository root.

    The ``AET_REPO_ROOT`` environment variable overrides filesystem
    inference so that the command works when ``aet`` is installed into a
    dedicated venv (where ``__file__`` resolves to site-packages) and when
    invoked from a git worktree (where ``__file__`` resolves to the
    ephemeral worktree copy).
    """
    env_root = os.environ.get("AET_REPO_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parent.parent.parent.parent


def _gitignore_lines(repo_root: str | Path) -> set[str]:
    """Return the stripped lines of ``repo_root/.gitignore``, empty if absent."""
    gitignore = Path(repo_root) / ".gitignore"
    if not gitignore.exists():
        return set()
    return {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}


def missing_aet_gitignore_entries(repo_root: str | Path) -> list[str]:
    """Return AET ignore entries absent from ``repo_root/.gitignore``.

    Comparison is literal, so a glob that happens to cover an entry still
    reports it as missing; the writer appends the exact name.
    """
    existing = _gitignore_lines(repo_root)
    return sorted(AET_IGNORED_PATHS - existing)


def write_aet_gitignore_entries(repo_root: str | Path) -> list[str]:
    """Idempotently write AET ignore entries to ``repo_root/.gitignore``.

    Reads ``AET_IGNORED_PATHS``, the declaration of paths the toolkit writes
    that must never be tracked. The hygiene gate forgives those and more: a
    path the toolkit appends to but that is meant to be committed belongs in
    ``AET_TOLERATED_DIRTY_PATHS``, and writing it here would silently stop it
    from ever being committed. Existing lines are preserved; duplicate entries
    are never appended.
    """
    gitignore = Path(repo_root) / ".gitignore"
    added = missing_aet_gitignore_entries(repo_root)

    if added:
        with gitignore.open("a", encoding="utf-8") as f:
            for entry in added:
                f.write(f"{entry}\n")

    return added


def stale_aet_gitignore_entries(repo_root: str | Path) -> list[str]:
    """Return ``.gitignore`` lines naming a path the toolkit no longer writes.

    Reads ``AET_RETIRED_IGNORED_PATHS``. The writer only appends, so a rename
    adds the new name and leaves the old one in place; the stale line ignores
    nothing and the new path stays untracked until the next bootstrap. Reports
    only names the toolkit itself once wrote, so a project's own entries are
    never flagged.
    """
    return sorted(_gitignore_lines(repo_root) & AET_RETIRED_IGNORED_PATHS)


def _bin_dir() -> Path:
    """Return the link target dir: ``AET_BIN_DIR`` or ``~/.local/bin``."""
    override = os.environ.get("AET_BIN_DIR")
    return Path(override) if override else Path.home() / ".local" / "bin"


def _link_target() -> Path | None:
    """Return the ``aet`` console script installed next to the interpreter.

    ADR-041 makes the console script the only supported entry point, so there
    is no fallback: linking a module file instead produces a link that cannot
    execute (no shebang, not executable), which is the defect class this
    command exists to remove. ``None`` means "refuse", not "guess".

    Resolved, because ``_link_target_resolves_to`` compares against a resolved
    readlink; leaving it unresolved makes an already-correct link compare
    unequal whenever any path component is a symlink (``/tmp`` on macOS), so
    every run would report a stale-link repair it did not need to make.
    """
    console_script = Path(sys.executable).parent / "aet"
    if console_script.exists():
        return console_script.resolve()
    return None


def _is_worktree_copy(script: Path) -> bool:
    """True when the running copy lives under a ``.worktrees`` directory."""
    return ".worktrees" in script.parts


def _link_target_resolves_to(link: Path, script: Path) -> bool:
    """True when ``link`` is a symlink already pointing at ``script``."""
    target = Path(os.readlink(link))
    if not target.is_absolute():
        target = link.parent / target
    return target.resolve() == script


def _agent_skills_dirs() -> list[Path]:
    """Return detected agent skills directories."""
    home = Path.home()
    candidates = [
        home / ".claude" / "skills",
        home / ".kimi" / "skills",
        home / ".cursor" / "skills",
        home / ".agents" / "skills",
    ]
    return [p for p in candidates if p.is_dir()]


def _resolve_target_dirs(
    skills_dir: str | None,
    agent: str | None,
) -> list[Path]:
    """Resolve the target skills directories from explicit flags or auto-detection."""
    if skills_dir is not None:
        return [Path(skills_dir).expanduser().resolve()]

    if agent is not None:
        home = Path.home()
        mapping = {
            "claude-code": home / ".claude" / "skills",
            "kimi": home / ".kimi" / "skills",
            "cursor": home / ".cursor" / "skills",
            "generic": home / ".agents" / "skills",
        }
        if agent not in mapping:
            typer.echo(f"error: unknown agent '{agent}'", err=True)
            raise typer.Exit(1)
        return [mapping[agent]]

    detected = _agent_skills_dirs()
    if detected:
        return detected
    return [Path.home() / ".agents" / "skills"]


def _link_skill(
    skill_path: Path,
    target_dir: Path,
    *,
    dry_run: bool,
    force: bool,
) -> str:
    """Ensure ``target_dir/<skill-name>`` symlinks to ``skill_path``.

    Returns a human-readable status line.
    """
    link = target_dir / skill_path.name
    repo_skill = skill_path.resolve()

    if link.is_symlink():
        try:
            if link.resolve() == repo_skill:
                return f"= {skill_path.name} already linked"
        except OSError:
            pass
        if dry_run:
            return f"~ {skill_path.name} would repoint"
        link.unlink()
        link.symlink_to(repo_skill)
        return f"~ {skill_path.name} repointed"

    if link.exists():
        if not force:
            return f"! {skill_path.name} exists but is not a symlink (skipping)"
        if dry_run:
            return f"+ {skill_path.name} would replace with symlink"
        link.unlink()
        link.symlink_to(repo_skill)
        return f"+ {skill_path.name} replaced with symlink"

    if dry_run:
        return f"+ {skill_path.name} would link"
    link.symlink_to(repo_skill)
    return f"+ {skill_path.name} linked"


@app.command("link")
def setup_link(
    bin_dir: str | None = typer.Option(None, "--bin-dir", envvar="AET_BIN_DIR", help="Target bin directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print actions without executing."),
) -> None:
    """Link ``aet`` into the bin dir."""
    target_dir = Path(bin_dir) if bin_dir else _bin_dir()

    script = _link_target()
    if script is None:
        typer.echo(
            f"  ⚠ no aet console script next to {Path(sys.executable).parent};"
            " install the package first (e.g. `pip install -e .`), then re-run"
            " setup link.",
            err=True,
        )
        raise typer.Exit(1)

    if _is_worktree_copy(script):
        typer.echo(
            f"  ⚠ refusing to link from an ephemeral worktree copy ({script});"
            " run setup link from the main checkout.",
            err=True,
        )
        raise typer.Exit(1)

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    link = target_dir / "aet"
    if link.is_symlink():
        if _link_target_resolves_to(link, script):
            typer.echo(f"  = aet already linked -> {script}")
        else:
            if dry_run:
                typer.echo(f"  ~ aet -> {script} (would update stale symlink)")
            else:
                link.unlink()
                link.symlink_to(script)
                typer.echo(f"  ✓ aet -> {script} (updated stale symlink)")
    elif link.exists():
        if dry_run:
            typer.echo(f"  ! aet exists in {target_dir} and is not a symlink (would skip)")
        else:
            typer.echo(
                f"  ⚠ aet exists in {target_dir} and is not a symlink. Skipping.",
                err=True,
            )
    else:
        if dry_run:
            typer.echo(f"  + aet -> {script} (would create symlink)")
        else:
            link.symlink_to(script)
            typer.echo(f"  ✓ aet -> {script}")

    if str(target_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        typer.echo(f"\n⚠ {target_dir} is not on your PATH. Add it to your shell profile:")
        typer.echo(f'    export PATH="{target_dir}:$PATH"')


@app.command("skills")
def setup_skills(
    skills_dir: str | None = typer.Option(
        None, "--skills-dir", envvar="AET_SKILLS_DIR", help="Target skills directory."
    ),
    agent: str | None = typer.Option(
        None, "--agent", envvar="AGENT", help="Target agent: claude-code, kimi, cursor, generic."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print actions without executing."),
    force: bool = typer.Option(False, "--force", help="Replace non-symlink collisions with symlinks."),
) -> None:
    """Symlink AE Toolkit skills into agent skills directories."""
    target_dirs = _resolve_target_dirs(skills_dir, agent)
    repo_root = _repo_root()
    skill_root = repo_root / "skills"
    skills = sorted([p for p in skill_root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()])

    if not skills:
        typer.echo("warning: no skills found in repository", err=True)
        raise typer.Exit(0)

    for target_dir in target_dirs:
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
        for skill in skills:
            status = _link_skill(skill, target_dir, dry_run=dry_run, force=force)
            typer.echo(f"  {status}")

    summary = "would link" if dry_run else "linked"
    typer.echo(f"✓ {summary} {len(skills)} skill(s) to {len(target_dirs)} director(y/ies)")


def _report_skill_link_drift() -> None:
    """Report skill symlinks that do not point at this repository's ``skills/``.

    A stale skill link is invisible otherwise: the loaded skill loads, so nothing
    fails, and the session simply follows instructions from whichever checkout
    the link was made against. That is how a fix applied to a skill can never
    reach a session — the symptom is a session behaving as though the fix does
    not exist, which reads as a model problem rather than an install problem.

    Read-only, like the rest of ``verify``: it names the drift and leaves
    ``aet setup skills`` to correct it.
    """
    skill_root = _repo_root() / "skills"
    if not skill_root.is_dir():
        return
    expected = {
        p.name: p.resolve() for p in skill_root.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    }
    if not expected:
        return

    for target_dir in _agent_skills_dirs():
        drifted: list[str] = []
        for name, repo_skill in sorted(expected.items()):
            link = target_dir / name
            if not link.is_symlink():
                continue
            try:
                if link.resolve() != repo_skill:
                    drifted.append(f"{name} -> {os.readlink(link)}")
            except OSError:
                drifted.append(f"{name} -> <unresolvable>")
        if drifted:
            typer.echo(
                f"  ⚠ {len(drifted)} skill link(s) in {target_dir} do not point at "
                f"{skill_root}:",
                err=True,
            )
            for entry in drifted:
                typer.echo(f"      {entry}", err=True)
            typer.echo("    Run `aet setup skills` to repoint them.", err=True)
        else:
            typer.echo(f"  = skill links in {target_dir} point at this repo")


@app.command("verify")
def setup_verify(
    bin_dir: str | None = typer.Option(None, "--bin-dir", envvar="AET_BIN_DIR", help="Target bin directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print actions without executing."),
) -> None:
    """Verify that the installed `aet` on PATH matches the expected link.

    Resolves what `aet` actually runs on PATH and reports when it is not the
    copy just installed. Also prints the resolved trunk branch and how it was
    derived (config, detected from ``refs/remotes/origin/HEAD``, or fallback
    to ``main``). Read-only: never edits PATH, shell profiles, or the link
    itself. Exits 0 even when shadowed — the install succeeded, but the user
    will experience a different copy.
    """
    target_dir = Path(bin_dir) if bin_dir else _bin_dir()
    expected = _link_target()
    link = target_dir / "aet"

    _report_skill_link_drift()

    if dry_run:
        typer.echo("  (dry run — would verify aet link against PATH)")

    if expected is None:
        typer.echo(
            f"  ⚠ no aet console script next to {Path(sys.executable).parent};"
            " install the package first.",
            err=True,
        )
        raise typer.Exit(1)

    # Config belongs to the repository where the command runs, not to the
    # installed package location (important under a venv install where
    # _repo_root() resolves to site-packages).
    config_repo_root = resolve_repo_root()
    config_path = str(config_repo_root / ".agents" / "aet-config.json")
    try:
        config, config_source = resolve_config_with_source(
            config_path, repo_root=config_repo_root
        )
        mode, mode_provenance = resolve_integration_mode_with_provenance(config_path)
        integration = resolve_integration_branch(config_repo_root, config)
        trunk = resolve_trunk_branch(config_repo_root, config)
    except FileNotFoundError:
        typer.echo(
            "  ⚠ could not resolve config: git is not available on PATH",
            err=True,
        )
    else:
        typer.echo(f"  integration_mode: {mode} ({mode_provenance})")
        integration_provenance = _format_branch_provenance(
            integration.provenance, config_source
        )
        typer.echo(f"  integration_branch: {integration.ref} ({integration_provenance})")
        trunk_provenance = _format_branch_provenance(trunk.provenance, config_source)
        typer.echo(f"  trunk: {trunk.ref} ({trunk_provenance})")
        try:
            from aet.backends.factory import create_backend

            backend = create_backend(
                config_path=config_path,
                queue_file=str(config_repo_root / ".agents" / "aet-queue"),
                history_file=str(config_repo_root / ".agents" / "work-history.jsonl"),
            )
            epic = backend.read_epic()
            backend.close()
            if epic and epic.get("branch"):
                title_str = f" ({epic['title']})" if epic.get("title") else ""
                typer.echo(f"  active_epic: {epic['branch']}{title_str} (envelope)")
        except Exception as exc:
            typer.echo(f"  ⚠ could not read queue envelope: {exc}", err=True)

    for entry in missing_aet_gitignore_entries(config_repo_root):
        typer.echo(f"  ⚠ .gitignore is missing {entry}; run `aet setup bootstrap`", err=True)
    for entry in stale_aet_gitignore_entries(config_repo_root):
        typer.echo(f"  ⚠ .gitignore names {entry}, a path the toolkit no longer writes", err=True)

    path_aet = shutil.which("aet", path=os.environ.get("PATH"))

    if link.is_symlink():
        try:
            link_target = link.resolve(strict=True)
        except OSError:
            typer.echo(f"  ⚠ {link} is dangling (target does not exist)", err=True)
            if path_aet and Path(path_aet).resolve() != expected:
                typer.echo(f"  ⚠ PATH `aet` resolves to {path_aet}, not {expected}", err=True)
            elif path_aet:
                typer.echo(f"  = PATH `aet` resolves to {expected}")
            else:
                typer.echo("  ⚠ no `aet` found on PATH", err=True)
            raise typer.Exit(0)

        if link_target == expected:
            if path_aet and Path(path_aet).resolve() != expected:
                typer.echo(f"  = {link} -> {expected}")
                typer.echo(
                    f"  ⚠ another `aet` on PATH shadows this install: {path_aet}",
                    err=True,
                )
            else:
                typer.echo(f"  = aet already linked -> {expected}")
            raise typer.Exit(0)

        # Link exists but points elsewhere.
        typer.echo(f"  ⚠ {link} -> {link_target}, expected {expected}", err=True)
        if path_aet and Path(path_aet).resolve() != expected:
            typer.echo(f"  ⚠ PATH `aet` resolves to {path_aet}", err=True)
        raise typer.Exit(0)

    if link.exists():
        typer.echo(
            f"  ⚠ {link} exists and is not a symlink; cannot verify",
            err=True,
        )
        if path_aet:
            typer.echo(f"  = PATH `aet` resolves to {path_aet}")
        raise typer.Exit(0)

    # No link in target dir; just report what PATH resolves to.
    if path_aet is None:
        typer.echo("  ⚠ no `aet` found on PATH", err=True)
    elif Path(path_aet).resolve() == expected:
        typer.echo(f"  = PATH `aet` resolves to {expected}")
    else:
        typer.echo(f"  = PATH `aet` resolves to {path_aet}")
        typer.echo(
            f"  ⚠ PATH `aet` is not the expected install at {expected}",
            err=True,
        )
    raise typer.Exit(0)


@app.command("bootstrap")
def setup_bootstrap(
    path: str | None = typer.Option(
        None,
        "--path",
        help="Project root to write .gitignore into (default: current directory).",
    ),
) -> None:
    """Write AET ignore entries to the project ``.gitignore``."""
    repo_root = Path(path).expanduser().resolve() if path else Path.cwd()
    added = write_aet_gitignore_entries(repo_root)
    if added:
        for entry in added:
            typer.echo(f"  + {entry}")
        typer.echo(f"✓ wrote {len(added)} AET ignore entries to .gitignore")
    else:
        typer.echo("= all AET ignore entries already present")

    for entry in stale_aet_gitignore_entries(repo_root):
        typer.echo(f"  - {entry} (retired: the toolkit no longer writes this path)")
