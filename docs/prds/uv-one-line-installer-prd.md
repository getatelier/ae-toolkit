# PRD: uv-Based One-Line Installer

## Overview

Replace the current three-step AE Toolkit onboarding — `pip install`, `npx skills add`, and `aet install` — with a single `curl | bash` command that bootstraps `uv`, installs the `aet` CLI, links skills into detected agent directories, and puts `aet` on `PATH`. The existing pip/editable path remains untouched for development.

## Goals

- **G1**: A new user can install the entire toolkit with one command copied from the README.
- **G2**: The installer uses `uv` when available and bootstraps it when missing, without making `uv` a runtime requirement of `aet`.
- **G3**: Skills are installed automatically alongside the CLI for detected agents (Claude, Kimi, Cursor, generic `~/.agents`).
- **G4**: The installer is idempotent, supports dry-run, and is safe to re-run after updates.
- **G5**: Existing `pip install -e .[dev]` and `make install-skills` workflows keep working unchanged.

## Non-Goals

- No Windows-native PowerShell installer in this phase; Windows users continue to use WSL or manual instructions.
- No migration away from directory-based skill distribution; individual `.skill` zip artifacts remain retired per ADR-016/018.
- No PyPI publishing in this phase; the installer clones the git repo and installs from source.
- No removal of the `npx skills add` path; it becomes the fallback/manual path.
- No shell-profile editing by the installer; warning when `~/.local/bin` is missing from `PATH` stays manual, matching the existing `aet install` behavior.

## Requirements

- **R-1**: A POSIX shell script at `scripts/install.sh` is the entry point for the one-liner `curl -fsSL https://raw.githubusercontent.com/thebrightnest/ae-toolkit/main/scripts/install.sh | bash`.
- **R-2**: The script accepts flags:
  - `--tag <tag>` — install a tagged release (default: latest stable tag derived from the repo or `main` if no tag is found).
  - `--agent <agent>` — target one agent directory (e.g., `claude-code`, `kimi`, `cursor`, `generic`).
  - `--bin-dir <dir>` — override the target `PATH` directory (default: `~/.local/bin`).
  - `--skills-dir <dir>` — override the skills directory (default: auto-detect, fallback to `~/.agents/skills`).
  - `--repo <url-or-path>` — override the source to clone (default: `https://github.com/thebrightnest/ae-toolkit`); a local path lets the smoke test run offline against the working tree.
  - `--dry-run` — print actions without executing them.
  - `--help` — print usage and exit.
- **R-3**: The installer bootstraps `uv` if it is not on `PATH`, using the official Astral standalone installer, and verifies the `uv` binary is executable.
- **R-4**: The installer clones or updates the AE Toolkit repo to a persistent path (`~/.local/share/ae-toolkit` by default) and checks out the requested tag.
- **R-5**: The `aet` CLI is installed from the cloned repo into a dedicated virtual environment at `~/.local/share/ae-toolkit/venv` (created and managed with `uv`), so the installed `aet` is independent of any transient checkout and does not depend on `uv tool` internals.
- **R-6**: The installer links all `skills/*` directories into the selected skills directory, preserving existing symlinks and warning on collisions (matching `make install-skills` behavior).
- **R-7**: `--agent` maps to directories as follows: `claude-code` → `~/.claude/skills`, `kimi` → `~/.kimi/skills`, `cursor` → `~/.cursor/skills`, `generic` → `~/.agents/skills`. Without `--agent`, auto-detection checks, in order:
  - `~/.claude/skills`
  - `~/.kimi/skills`
  - `~/.cursor/skills`
  - `~/.agents/skills`
  If more than one exists and no `--agent` flag is given, the installer installs to all detected directories and prints a summary.
- **R-8**: After skills are linked, the installer symlinks `<bin-dir>/aet` to the venv's console script (`~/.local/share/ae-toolkit/venv/bin/aet`), mirroring `aet install`'s symlink semantics (repair stale symlinks, warn and skip on non-symlink collisions). The installer does not invoke `aet install`: `aet install` links `Path(__file__)` inside the installed package, which only resolves correctly for the editable dev path and would produce a broken link from a non-editable venv.
- **R-9**: The installer never links from inside a `.worktrees/` path; it always targets the persistent clone's venv console script, never a local or worktree copy of the repo.
- **R-10**: The script is idempotent: re-running it updates the repo checkout, refreshes skill symlinks, re-installs the CLI, and repairs the `aet` PATH link.
- **R-11**: The script exits non-zero with a clear message on any failure (missing dependencies, clone failure, `uv` bootstrap failure, `aet install` failure).
- **R-12**: Existing development paths remain documented and functional:
  - `pip install -e ".[dev]"`
  - `make install-skills`
  - `npx skills add https://github.com/thebrightnest/ae-toolkit --all`
- **R-13**: A smoke test runs the installer with `--repo <local-checkout>` against temporary `HOME`, `AET_BIN_DIR`, and `AET_SKILLS_DIR` directories — no network, exercising the working tree's installer before merge — wired into `make validate` as a standalone test target (this repo has no CI; all gates are local). It verifies `aet --version` succeeds and at least one skill symlink resolves.
- **R-14**: The README Quick Start section leads with the one-liner and keeps the manual pip/editable path under a "Development" or "Manual install" heading.

## User Stories

- As a new user on macOS or Linux, I want to install AE Toolkit with one command so I can start using `/aet-setup` immediately (satisfies: R-1, R-3, R-4, R-5, R-8).
- As a Claude Code user, I want the installer to link skills to `~/.claude/skills` automatically so I don't have to run `npx skills add` separately (satisfies: R-6, R-7).
- As a developer who already has `uv` installed, I want the installer to use it instead of pip so my environment stays consistent (satisfies: R-3, R-5).
- As a maintainer, I want the installer to be tested in isolation so regressions in onboarding are caught before merge (satisfies: R-13).
- As an existing contributor, I want my `make install-skills` workflow to keep working unchanged (satisfies: R-12, G5).

## Acceptance Criteria

- [ ] `curl -fsSL https://raw.githubusercontent.com/thebrightnest/ae-toolkit/main/scripts/install.sh | bash` completes on a fresh macOS/Linux machine and leaves `aet --version` working (satisfies: R-1, R-11).
- [ ] After installation, `aet-setup/SKILL.md` under every detected (or `--agent`-selected) skills directory resolves to the cloned repo's `skills/aet-setup/SKILL.md` (satisfies: R-6, R-7).
- [ ] Re-running the installer with `--dry-run` prints every planned action and modifies no files (satisfies: R-2, R-10).
- [ ] The smoke test passes in `make validate` or a standalone test target and uses temporary directories only (satisfies: R-13).
- [ ] `pip install -e ".[dev]" && make install-skills` still works on a clean clone after these changes (satisfies: R-12).
- [ ] `aet install` continues to refuse to link from inside a `.worktrees/` path, and the installer never triggers that failure mode (satisfies: R-9, and prevents the 2026-07-15 worktree symlink regression from `.agents/learnings.jsonl`).

## Technical Notes

- **Ground truth**: `aet install` lives in `src/aet/cli/main.py`; it already validates against worktree copies. Skill linking logic exists in the Makefile (`install-skills` target) and should be extracted or mirrored in a CLI-accessible form so the installer can call it without `make`.
- **Skill installation CLI**: Add `aet setup skills` (or extend `aet install`) as a deterministic, testable command that discovers agent directories and symlinks skills. This keeps judgment out of the installer script and makes the skill-linking surface lintable and unit-testable.
- **Why a dedicated venv, not `uv tool install` + `aet install`**: `aet install` links `Path(__file__).resolve()` (`src/aet/cli/main.py`), which only works for the editable dev path — there `__file__` resolves to the repo checkout and the bootstrap guard re-execs into the repo `.venv`. From a non-editable install (`uv tool install` or a plain venv), `__file__` lands in copied site-packages with no discoverable venv, and the linked `aet` breaks. The installer therefore creates `~/.local/share/ae-toolkit/venv` with `uv venv`, installs the cloned repo into it with `uv pip install`, and symlinks `<bin-dir>/aet` to the venv's console script, which carries a correct venv-python shebang.
- **Repo persistence**: The installer needs the skills directory on disk after installation, so it clones to `~/.local/share/ae-toolkit`. `uv tool install` from a path copies the package; the cloned repo remains the source for skill symlinks.
- **Tag resolution**: If `--tag` is omitted, use `git ls-remote --tags --sort=-v:refname` (git's own version sort; BSD `sort` on macOS has no `-V`) to find the latest semver tag, falling back to `main`.
- **Security**: The script only writes under `~/.local`, `~/.claude`, `~/.kimi`, `~/.cursor`, `~/.agents`, and the requested `--bin-dir`/`--skills-dir`. It never runs `sudo`. `uv` is bootstrapped only via Astral's official installer, which verifies the SHA-256 checksum of the binary it downloads.
- **Worktree guard**: The learning from 2026-07-15 (`aet install` run from a worktree broke the global symlink) is blocked by R-9; the installer must invoke the freshly-installed `aet` binary, not a script inside a worktree.
- **Testing strategy**: A pytest test or shell test creates a temporary `HOME`, runs `scripts/install.sh --repo <local-checkout> --bin-dir <tmp> --skills-dir <tmp>/skills --agent generic`, and asserts `aet --version` exits 0 and `<tmp>/skills/aet-setup/SKILL.md` resolves. Cloning from the local checkout keeps the test offline and exercises unmerged installer changes.

## Open Questions

None blocking for this PRD. The following assumptions were made because this is a design conversation under auto-permission mode; confirm or override at the PRD gate:

1. **Distribution model**: The installer clones from git rather than installing from PyPI. PyPI publishing is deferred to a later packaging phase.
2. **OS scope**: The curl installer targets POSIX (macOS/Linux). Windows/WSL users follow the manual path or a future PowerShell installer.
3. **Agent default**: When multiple agent directories exist, install to all of them. No agent selected installs only to `~/.agents/skills`.
4. **uv fallback**: If `uv` bootstrap fails, the script exits with a clear error rather than falling back to pip; pip remains the documented manual alternative.

## Divergence Summary

_Recorded: 2026-07-21 — Branch: uvi-01-aet-setup-skills-command_

### Changed from plan

- None. The `aet setup skills` implementation matches the plan intent.

### Added (unplanned)

- None.

### Deferred

- `scripts/install.sh` one-line installer shell script (R-1 through R-5, R-8, R-10, R-11).
- `uv` bootstrap logic and venv management (R-3, R-5).
- Smoke test wired into `make validate` using a temporary `HOME` (R-13).
- README Quick Start rewrite leading with the `curl | bash` one-liner (R-14).
- These items remain in the PRD and will be addressed in follow-up plans.

## Divergence Summary — uvi-02-curl-installer-script

_Recorded: 2026-07-21 — Branch: uvi-02-curl-installer-script_

### Changed from plan

- The installer items previously deferred in the `uvi-01-aet-setup-skills-command` divergence summary are now implemented in this branch:
  - `scripts/install.sh` one-line installer shell script (R-1 through R-5, R-8, R-10, R-11).
  - `uv` bootstrap logic and venv management (R-3, R-5).
  - Smoke test wired into `make validate` using a temporary `HOME` (R-13).
  - README Quick Start rewrite leading with the `curl | bash` one-liner (R-14).

### Added (unplanned)

- None.

### Deferred

- None.

---

_Stage: synced_
_Next step: run `aet-ship`_
