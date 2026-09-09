# PRD: Fresh-Install Correctness

## Overview

The documented one-line install cannot succeed on a stock macOS machine, and
when worked around, the resulting install corrupts its own `aet` symlink on the
first real subcommand. Both shipped in v1.4.0 and were found by a user
installing on a clean machine, not by the test suite.

The five defects are recorded in
`docs/bugs/2026-07-22-fresh-install-v140-installer-and-path-link-failures.md`.
They are not five independent bugs. The toolkit has **three overlapping,
hand-rolled mechanisms** answering one question — how does `aet` get onto `PATH`
and run under an interpreter that can import it — and each defect is two of them
colliding:

| # | Mechanism | Defect it produced |
|---|---|---|
| 1 | `install.sh` `link_aet_binary()` | — (correct, and overwritten by 2) |
| 2 | `_ensure_path_link()` on every subcommand | rewrites the link to a module path |
| 3 | `main.py` bootstrap guard | exists only to make 2's bad target work; fails on packaged installs |

Plus a fourth hand-rolled surface: ~90 lines of bash flag parsing in
`install.sh` marshalling arguments for a Python program that already parses
flags — which is where the empty-array crash lives.

This PRD replaces the hand-rolled mechanisms with the packaging system's
answers, rather than repairing each in place. It reverses the self-repair
decision locked in `cli-04` and supersedes R-8 of `uv-one-line-installer-prd.md`.

**Intake classification.** All five defects are reproducible and were
investigated under `aet-bug-report`. The work planned here is the structural
replacement, routed out of `aet-bug-report` by its structural-redesign rule.
Diagnosis is not re-derived; the bug report is the evidence.

**Direction note.** An earlier draft of this PRD fixed each defect in place —
guard the array, gate the version mismatch, warn about shadowing. Those are
detectors and patches on instances. The owner rejected that framing on
2026-07-22; the requirements below target the classes instead. Where this
reverses an earlier owner decision (the version gate, R-19), the reversal is
stated explicitly in ADR-043.

## Goals

- **G1** — The documented one-liner, pasted verbatim with no flags, completes on
  a stock macOS machine.
- **G2** — A completed install stays working. No `aet` invocation may degrade
  its own PATH link.
- **G3** — `aet --version` cannot report a version other than the one installed.
- **G4** — One mechanism owns PATH linking; one mechanism owns interpreter
  selection. Not three.
- **G5** — Install logic is testable in the language it is written in, and the
  documented default invocation is covered.
- **G6** — The installer reports the end state the user experiences, not the
  state it believes it created.

## Non-Goals

- Windows support. macOS/Linux only.
- Changing the user-facing contract of the one-liner: same command, same flags,
  same idempotence, same `--dry-run`.
- Changing the uv-based install model, the venv location, or skills-linking
  behavior. R-1…R-14 of `uv-one-line-installer-prd.md` stand except where R-16
  supersedes R-8.
- Moving the *bootstrap* into Python. Acquiring `uv`, cloning, and creating the
  venv necessarily precede an importable `aet` (ADR-042).
- Resolving PATH shadowing on the user's behalf — no `PATH` edits, no shell
  profile edits, no touching other installations. Report only.
- Backfilling repair for users holding a corrupted link. Re-running the
  installer fixes it; release notes say so.
- Replacing the `git clone` with a downloadable release artifact. Raised
  2026-07-22 and deferred to its own PRD: the wheel ships `src/aet` only
  (in `pyproject.toml`), and `setup skills` symlinks out of the clone
  (in `src/aet/cli/setup.py`), so the repo is the delivery mechanism for the skills, not an
  installer detail. Removing it is a distribution-model decision — where skills
  live, how updates work — and no defect here is caused by cloning. It would
  make ADR-043 strictly stronger (a release-built wheel bakes in the version,
  removing that ADR's `--depth 1` risk) and does not invalidate `fic-02`, whose
  change is where the shell/Python boundary sits, not what precedes it.

## Requirements

### One entry point (ADR-041)

- **R-15** — `_ensure_path_link()`, `_running_script()`, and the callback call
  site are deleted. No `aet` subcommand mutates `<bin-dir>/aet` as a side effect
  of running.
- **R-16** — **Supersedes R-8 of `uv-one-line-installer-prd.md`.** The link
  target is always the environment's console script
  (`Path(sys.executable).parent / "aet"`), never `__file__`. R-8 identified this
  hazard but applied it only to `aet install`; the same code ran from the
  callback on every subcommand, which is the defect.
- **R-17** — The direct-script invocation mode is deleted: the
  `#!/usr/bin/env python3` shebang, the `if __name__ == "__main__"` block, and
  the module-level bootstrap guard. Supported invocations are
  the `aet` console script and `python -m aet.cli.main`. No repo caller invokes
  `main.py` by file path — audited: `Makefile` uses `-m`,
  `scripts/skills-lint` imports the app.
- **R-18** — `aet install` is replaced by `aet setup link`: explicit, reporting,
  and the only code path in the package that writes the link. It keeps existing
  semantics (repair an AET-managed symlink, refuse a non-symlink collision,
  print the `export PATH=` line when the bin dir is off `PATH`) and retains the
  `.worktrees/` refusal required by R-9. A symlink counts as AET-managed when it
  targets any `aet` console script **or any `aet/cli/main.py`** — the latter is
  the v1.4.0 corruption signature, and recognizing it is what makes re-running
  the installer sufficient repair for users holding a corrupted link.
- **R-19** — `main.py`'s module docstring, which asserts that `aet install` and
  `_ensure_path_link` remain "because single-name PATH ownership is still
  required," is corrected to describe installer-owned linking.

### Installer is a bootstrap (ADR-042)

- **R-20** — `scripts/install.sh` performs only pre-Python work: bootstrap `uv`,
  resolve the tag, clone or update the repo, create the venv, install the
  package. It then hands off to the installed CLI.
- **R-21** — Flag ownership is split at the bootstrap boundary, and each side
  parses only what it owns. Bash owns the pre-Python flags — `--tag`, `--repo`,
  `--bin-dir`, `--dry-run`, `--help` — with their env defaults (`REPO`, `TAG`,
  `AET_DATA_DIR`, `AET_BIN_DIR`); these are scalar assignments, consumed by the
  bootstrap, and never forwarded. Everything else — today `--agent` and
  `--skills-dir` — passes through to `aet setup` unparsed, and Typer binds
  `AGENT` / `AET_SKILLS_DIR` via `envvar=` so the documented env-var contract
  survives the handoff. The `skills_args` array is **removed, not guarded** —
  bash never marshals arguments for a Python program again. This eliminates the
  empty-array expansion class rather than patching its instances
  in `scripts/install.sh`.
- **R-22** — Post-bootstrap work is `aet setup`: `skills` (exists), `link`
  (R-18), and `verify` (R-23).
- **R-23** — `aet setup verify` resolves what `aet` actually runs on `PATH` and
  reports when it is not the copy just installed, naming the shadowing path. It
  is read-only and exits 0 on a successful-but-shadowed install. It is a
  standalone diagnostic, runnable later, not only an installer step.
- **R-24** — `--dry-run` is honored on both sides of the bash/Python boundary.
- **R-25** — `scripts/validate-skills.sh` receives the `${arr[@]+"${arr[@]}"}`
  guard at its three `SKILL_DIRS` expansions. It is not on the installer path
  and does not justify a rewrite; it is one empty `skills/` directory away from
  the same crash.

### Version derives from the tag (ADR-043)

- **R-26** — **Reverses the release-gate decision of 2026-07-22.** `hatch-vcs`
  derives the version from the git tag; `[project].version` is deleted in favor
  of `dynamic = ["version"]`. The two cannot disagree, so no gate is needed to
  detect disagreement. `aet --version` reads
  `importlib.metadata.version("aet")` unchanged.
- **R-27** — Building without git metadata (sdist/tarball) still yields a
  correct version via the fallback `hatch-vcs` writes into the sdist. Verified,
  not assumed.

### Verification (ADR-042)

- **R-28** — The installer test suite exercises the documented one-liner with
  **no flags** — the configuration in which every reported defect reproduces and
  which had no coverage at all.
- **R-29** — The suite executes a real subcommand through the **unresolved**
  `<bin-dir>/aet` symlink and asserts the link is unchanged afterward. Resolving
  the link first, or invoking only `--help`/`--version`, does not satisfy this:
  both exit before the callback body and could not observe the defect.
- **R-30** — The suite asserts the exact version, not a substring that any
  version satisfies (`"aet" in stdout` passes for `aet 1.3.0`).
- **R-31** — The remaining shell is exercised under `/bin/bash` explicitly, so
  the bash under test is the one macOS users have.
- **R-32** — Every new test is demonstrated failing against pre-fix code. A test
  written after the fix and never seen red is how this suite reached a state
  where it passed while three defects shipped.

### Documentation

- **R-33** — The doc sweep ships with the rename. `README.md` (the manual
  install instructions at `:144` and the `make install-skills` description at
  `:169`) and `docs/CONVENTIONS.md` (`:57-59`, which declares `aet install` the
  canonical installer) are updated to name `aet setup link`. Release notes for
  the version carrying this change state that users holding a v1.4.0-corrupted
  link repair it by re-running the installer — the mechanism the Non-Goals
  section relies on. AGENTS.md mandates keeping CONVENTIONS.md current when
  patterns change; the rename is one.

## User Stories

- As a new user on stock macOS, I want the documented one-liner to complete
  without flags, so installing does not require debugging a shell error
  (satisfies: R-20, R-21, R-31).
- As a new user, I want `aet` to keep working after my first command, so the
  tool does not break itself (satisfies: R-15, R-16, R-17, R-29).
- As a user reporting a problem, I want `aet --version` to name what I installed
  so a maintainer can act on my report (satisfies: R-26, R-30).
- As a user with another `aet` on `PATH`, I want to be told which copy wins, so
  a successful-looking install does not silently do nothing (satisfies: R-23).
- As a user whose install misbehaves later, I want one command that tells me
  what `aet` actually resolves to (satisfies: R-23).
- As a maintainer, I want install logic in Python with the rest of the toolkit,
  so it is covered by the suite I already run (satisfies: R-20, R-22).
- As a maintainer, I want releases to be `git tag` with nothing to remember
  (satisfies: R-26).
- As a maintainer, I want `validate-skills.sh` safe against an empty `skills/`
  directory, so the bash we keep carries no known footgun (satisfies: R-25).
- As a new user, I want the README and conventions to name commands that exist,
  so following the docs cannot lead me to a deleted subcommand (satisfies:
  R-33).
- As a contributor reading `main.py`, I want its docstring and its supported
  invocations to match reality (satisfies: R-17, R-19).

## Acceptance Criteria

- [ ] `curl -fsSL .../install.sh | bash` with no flags completes on stock macOS
      bash 3.2 and leaves a working `aet` (satisfies: R-20, R-21, R-31).
- [ ] The installer suite invokes the remaining shell via `/bin/bash`
      explicitly, never the PATH bash (satisfies: R-31).
- [ ] `install.sh --dry-run` with no other flags exits 0 and modifies nothing
      (satisfies: R-21, R-24).
- [ ] `grep -n 'skills_args' scripts/install.sh` returns nothing — the array is
      gone, not guarded (satisfies: R-21).
- [ ] `AGENT=generic` and `--agent generic` produce identical installs — the
      documented env-var contract survives the bash/Python handoff (satisfies:
      R-21).
- [ ] `scripts/validate-skills.sh` under bash 3.2 with an empty `skills/`
      directory exits cleanly — no unbound-variable error (satisfies: R-25).
- [ ] After install, `readlink <bin-dir>/aet` names the venv console script;
      after running a real subcommand through that link, `readlink` is unchanged
      (satisfies: R-15, R-16, R-29).
- [ ] No code path outside `aet setup link` and `scripts/install.sh` writes to
      `<bin-dir>/aet` (satisfies: R-15).
- [ ] `aet setup link` from a non-editable venv produces a link that executes
      (satisfies: R-16, R-18).
- [ ] `main.py` has no shebang, no `__main__` block, and no module-level
      `os.execv`; `python -m aet.cli.main plans lint` and the `aet` console
      script both still work (satisfies: R-17).
- [ ] `aet --version` matches `git describe` — expected value derived at test
      time, never a hardcoded literal — and no version string exists in
      `pyproject.toml` (satisfies: R-26, R-30).
- [ ] Building an sdist without `.git` present yields a correct version
      (satisfies: R-27).
- [ ] Installing with a different `aet` earlier on `PATH` prints a warning
      naming the shadowing path and still exits 0; `aet setup verify` reports the
      same thing standalone (satisfies: R-23).
- [ ] Each new installer test is demonstrated failing against pre-fix code, with
      the failure recorded in the PR (satisfies: R-32).
- [ ] `grep -rn 'aet install' README.md docs/CONVENTIONS.md` returns nothing,
      and the release notes for the carrying version name re-running the
      installer as the repair for v1.4.0 installs (satisfies: R-33).

## Technical Notes

- **The premise that expired.** `cli-04` locked "the invoked copy wins" on
  2026-07-11, when `aet` was a source-checkout script at `aet-work/bin/aet` —
  there `Path(__file__)` genuinely was the entry point. `uvi-02` changed
  deployment to a packaged console script and invalidated the premise without
  revisiting what rested on it. ADR-041 records the reversal.
- **Second occurrence, not first.** `.agents/learnings.jsonl` (2026-07-15)
  records a `vgr-04` worktree stage repointing `~/.local/bin/aet` at an
  ephemeral copy that dangled on cleanup. That entry's proposed fix was to
  narrow the mechanism to reject `.worktrees/` paths; `cli-04` did exactly that;
  the mechanism survived and produced 2026-07-22. Narrowing a third time is why
  R-15 deletes instead.
- **The bootstrap guard is circular.** It exists so a directly-invoked
  `main.py` can import its own package — and the only artifact that invokes
  `main.py` directly is the symlink `_ensure_path_link()` wrongly creates. It
  works in a source checkout only because walking four parents up from
  `src/aet/cli/main.py` lands on the repo root and finds `.venv/bin/python`;
  from `site-packages` the same walk lands in `venv/lib/pythonX.Y/` and finds
  nothing. Deleting R-15 removes its only caller.
- **The array is a symptom of a boundary error.** `skills_args` exists because
  bash marshals arguments for `aet setup skills`, a Python program with a Typer
  parser. R-21 moves the boundary rather than guarding the expansion.
- **`_is_worktree_copy()` is retained** with `aet setup link` as its only
  caller — R-9 still requires it and the 2026-07-15 incident is why.
- Symlink creation in the user bin directory is why `cli-04` carried
  `security_review: required`. Plans touching that code inherit it.

## Open Questions

None. The two naming questions from the review draft — `aet setup link` versus
a top-level `aet install` with a fixed target, and whether verify belongs in
`setup` or the `ship`/`doctor` family — are settled at PRD approval
(2026-07-22): R-18 and R-23 stand as written. All three install-phase commands
live under `setup` for coherence (`skills`, `link`, `verify`), and no alias is
retained — the repo has no backward-compatibility obligation (see the
no-backward-compat convention).

---

*Amended at review 2026-07-22: R-18 names the v1.4.0 corruption signature as*
*AET-managed; R-21 specifies the bash/Python flag and env-var boundary; R-33*
*(doc sweep) added; naming questions settled.*

## Divergence Summary

*Recorded: 2026-07-23 — Branch: fic-01-one-entry-point*

### Changed from plan

- **R-17 / Task 2:** The `if __name__ == "__main__"` block was kept, not deleted. Deleting it left `python -m aet.cli.main` importable but inert (silent exit 0), which disabled the `make validate` gate in `Makefile` and broke 9 subprocess tests. The direct-script machinery actually targeted by ADR-041 — the shebang and the module-level bootstrap guard — was removed instead. The module docstring and test coverage (`test_module_invocation_propagates_subcommand_exit_code`, `test_console_script_dispatches`) were updated to reflect this.

### Deferred

- **R-33 release-notes half:** The `CHANGELOG` edit naming re-running the installer as the repair for v1.4.0-corrupted links is deferred to release-prep. `scripts/prevent-release-on-feature-branch.sh` blocks `CHANGELOG` edits on feature branches; the exact wording is preserved in the plan's Rollback Plan for the release-prep stage.
- **Merge to main:** Task 7 (merge branch to main and verify integration) remains pending and will be handled by `aet-ship`.

## Divergence Summary — fic-02-installer-bootstrap-boundary

*Recorded: 2026-07-23 — Branch: fic-02-installer-bootstrap-boundary*

### Changed from plan

- **R-21 / Task 3:** Recognized flags (`--agent`, `--bin-dir`, `--skills-dir`) are
  bound via Typer `envvar=` options rather than appended to `"$@"` untouched.
  The env-var contract survives the bash/Python handoff and bash still rejects
  unrecognized flags before the clone, so the intent of the boundary shift is
  preserved.

### Added (unplanned)

- **`tests/setup/test_setup_verify.py`:** Added
  `test_reports_ok_when_no_link_but_console_script_wins_path` to cover the
  no-symlink case where the console script already wins on `PATH`.

### Deferred

- **Merge to main:** Task 8 (merge branch to main and verify integration) remains
  pending and will be handled by `aet-ship`.

*Stage: synced*
*Next step: run `aet-ship`*
