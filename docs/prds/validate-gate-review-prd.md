# PRD: Validate Gate Review — slim the markdown gates, keep the real ones

## Overview

The repo's quality gates spend most of their time on checks that catch **zero
structural defects**. Prettier and markdownlint reformat/relint all 454 tracked
markdown files on every commit, `make validate`, and push, while the checks that
actually catch defects (ruff, validate-workflows, skills-lint, validate-skills.sh,
pytest) are unaffected by markdown style. This feature drops the cosmetic gates,
fixes a version-drift bug, reorders `make validate` to fail fast, and speeds up
the two slow-but-valuable validators — spending gate time only on checks that
catch real defects. Decision direction and scope were confirmed with the owner
via structured questions before this PRD was written.

**Intake triage:** enhancement/cleanup of working tooling — **not** a reproducible
defect. (The one latent-defect flavor, markdownlint version drift between
pre-commit and the Makefile, is folded in as correctness item R-2, not a separate
bug report.)

### Measured cost profile (live repo, 454 tracked `.md`, none under `content/`)

| Gate in `make validate`        | Cost               | Catches real defects?                | Disposition                      |
| ------------------------------ | ------------------ | ------------------------------------ | -------------------------------- |
| markdownlint (`make lint`)     | 5.07s              | No — cosmetics (5 rules already off) | Slim to staged-only pre-commit   |
| prettier (`make format-check`) | 10.27s             | No — whitespace/wrapping/tables      | **Drop entirely**                |
| ruff (`make lint-py`)          | 0.10s              | Yes                                  | Keep                             |
| validate-workflows             | 0.20s              | Yes                                  | Keep                             |
| skills-lint                    | 0.29s              | Yes (doc-to-CLI drift)               | Keep                             |
| validate-skills.sh             | 22.78s             | Yes (frontmatter/dirs/links)         | Keep + **optimize**              |
| pytest (`make test`)           | 91.75s (610 tests) | Yes                                  | Keep + **parallelize**, run last |

Current `make validate` order is near-worst-case: pytest (92s) runs at Makefile
line 79, _before_ the sub-second validate-workflows/skills-lint and the 23s
validate-skills.sh — a broken CLI reference isn't caught until ~107s in.

## Goals

- Remove prettier from every gate; stop auto-rewriting staged files at commit.
- Keep markdownlint only as a pinned, staged-only pre-commit check; eliminate the
  pre-commit↔Makefile version drift.
- Reorder `make validate` for fail-fast (cheap high-signal first, pytest last).
- Preserve every non-cosmetic validator (they all earn their place) and record
  the decision as an ADR.
- Cut `make validate` / pre-push wall time: ~15s immediately from dropping the
  cosmetic sweeps, plus the two optimization plans (validate-skills.sh, pytest).
- Propagate the slimmer gate to newly scaffolded repos via aet-setup.

## Non-Goals

- **No CI.** Gates stay local (pre-commit + Make), per AGENTS.md.
- **No change to `.markdownlint.yaml` rule config** — the 5 disabled rules stay as-is.
- **No removal of generic hygiene hooks** (trailing-whitespace, end-of-file-fixer,
  check-yaml, detect-private-key) or any real validator.
- **No edits to `content/`** (untracked) or to historical records under
  `docs/plans/**` and `docs/bugs/**` (frozen).
- YAML/JSON lose prettier's _cosmetic_ formatting; syntax is still validated by
  `check-yaml`. This is an accepted consequence, not a goal to preserve.

## Requirements

- **R-1**: Prettier runs in no quality gate. Neither `git commit`, `make validate`,
  nor `git push` invokes prettier or rewrites files for formatting. (A manual-only
  `make format` convenience may remain, wired into no gate.)
- **R-2**: markdownlint runs only as a pinned pre-commit hook over _staged_ files;
  it is absent from `make validate` and the pre-push path. The retained manual
  `make lint` invocation is version-pinned to match the pre-commit hook (v0.17.2),
  removing cross-path drift.
- **R-3**: `make validate` executes gates fail-fast — ruff → validate-workflows →
  skills-lint → validate-skills.sh → pytest (last) — so a failure in an early gate
  aborts before pytest runs.
- **R-4**: AGENTS.md and `docs/CONVENTIONS.md` describe the post-change gates with
  no stale references to removed checks (e.g., `format-check`); the "structure and
  formatting" quality-surface line is revised; ADR-026 records the decision, the
  retained-validator rationale, and the pytest-xdist trade-off.
- **R-5**: `scripts/validate-skills.sh` validates relative markdown links with
  materially reduced runtime (no per-link subshell spawning) and identical
  pass/fail results, covered by a named test.
- **R-6**: `make validate` runs the pytest suite in parallel via `-n auto` with all
  tests passing deterministically; `pytest-xdist` is declared as a dev dependency
  with a documented install path; validate wall-time is materially reduced.
- **R-7**: The aet-setup scaffold no longer installs prettier, so a newly
  scaffolded repo inherits the slimmer gate set.

## User Stories

- As a contributor, when I commit a markdown file, prettier does not rewrite it and
  only a fast staged-only markdownlint runs, so commits stop mutating my files
  (satisfies: R-1, R-2)
- As a contributor, `make validate` and `git push` no longer sweep all 454 markdown
  files for style, so both are faster (satisfies: R-1, R-2)
- As a contributor, when a cheap check fails, `make validate` aborts in <1s instead
  of after the 92s test run (satisfies: R-3)
- As a maintainer, the docs and ADR-026 accurately describe the current gates and
  the reasoning, so the contract matches reality (satisfies: R-4)
- As a contributor, `make validate` completes substantially faster because
  validate-skills.sh and pytest are optimized (satisfies: R-5, R-6)
- As a downstream user, `aet-setup` scaffolds a repo without prettier, matching this
  repo's slimmer gate (satisfies: R-7)

## Acceptance Criteria

- [ ] Committing a deliberately mis-wrapped `.md` rewrites nothing; only markdownlint
      runs on the staged file (satisfies: R-1, R-2)
- [ ] `grep -n prettier .pre-commit-config.yaml Makefile` shows prettier only in a
      manual `make format` target — absent from validate, pre-commit, pre-push (R-1)
- [ ] `make validate` output shows markdownlint/prettier do not run, in order
      ruff → validate-workflows → skills-lint → validate-skills.sh → pytest (R-2, R-3)
- [ ] Breaking a documented `aet` command reference makes `make validate` fail at
      skills-lint in <1s, before pytest (satisfies: R-3)
- [ ] The retained `make lint` pins the same markdownlint version as the pre-commit
      hook rev (satisfies: R-2)
- [ ] AGENTS.md / CONVENTIONS.md contain no `format-check` reference; ADR-026 exists
      with Status: Accepted (satisfies: R-4)
- [ ] validate-skills.sh runs materially faster and its link-check test passes for
      both valid and broken-link fixtures (satisfies: R-5)
- [ ] `make validate` runs pytest with `-n auto`, all 610+ tests green across
      workers, wall time materially reduced; xdist install is documented (R-6)
- [ ] A repo scaffolded via aet-setup has no prettier hook or target (satisfies: R-7)

## Technical Notes

**Touchpoints (live only; frozen records untouched):** `.pre-commit-config.yaml`
(mirrors-prettier block 13–17), `Makefile` (`lint`/`format`/`format-check`/`validate`,
`make test`), `scripts/hooks/pre-commit` (fallback lines 12–14), `AGENTS.md`
(command table + rationale line 105 + dependency stance line 102),
`docs/CONVENTIONS.md` (pre-commit section ~276–284), `scripts/validate-skills.sh`
(link loop ~162–185), `aet-setup/SKILL.md` + `aet-setup/examples/illustrative-walkthrough.md`.

**Retained-validator rationale (the "does each gate earn its place" verdict):** every
non-cosmetic gate catches real defects — ruff (Python lint), validate-workflows
(workflow definitions), skills-lint (doc↔CLI drift), validate-skills.sh
(frontmatter/dirs/links), pytest (610 tests). Only prettier and all-files
markdownlint are cut. `validate-skills.sh` and `skills-lint` do **not** overlap
(structure vs. CLI-reference validation).

**pytest-xdist dependency mechanism (the thorny one):** this repo has _no_ Python
dependency manifest and AGENTS.md states "no requirements.txt." vgr-04 must
therefore (a) choose a dev-dep declaration mechanism and (b) revise that AGENTS.md
line. Recommended default: a minimal `requirements-dev.txt` (dev-only, doesn't
reintroduce a _runtime_ manifest) + an AGENTS.md note + `make test` degrading
gracefully if xdist is absent (so contributors who skipped `pip install` aren't
hard-blocked). Parallel-safety of the git/process-group tests
(`test_orchestrator`, `test_git_refs_parity`) is unknown until measured — vgr-04's
first task measures, and the isolation-fix scope may force an implement-time split
per the auto-split rule.

## Proposed plan breakdown (DAG)

| Plan       | Scope                                                                     | R             | Size | blocked_by     |
| ---------- | ------------------------------------------------------------------------- | ------------- | ---- | -------------- |
| **vgr-01** | Drop prettier; slim + pin markdownlint; fail-fast reorder `make validate` | R-1, R-2, R-3 | M    | —              |
| **vgr-02** | Gate docs (AGENTS.md, CONVENTIONS.md) + ADR-026                           | R-4           | S    | vgr-01         |
| **vgr-03** | De-subshell `validate-skills.sh` link check + add its first test          | R-5           | M    | —              |
| **vgr-04** | `pytest-xdist` + `-n auto` + dev-dep mechanism + parallel-safety fixes    | R-6           | M–L  | vgr-01, vgr-02 |
| **vgr-05** | Drop prettier from aet-setup scaffold templates/examples                  | R-7           | S    | —              |

vgr-03 and vgr-05 run in parallel with the vgr-01→vgr-02→vgr-04 chain. vgr-04 is
sequenced after vgr-01 (shared `Makefile`) and vgr-02 (shared `AGENTS.md`) to avoid
parallel-worktree merge conflicts.

## Open Questions

1. **pytest-xdist dep mechanism** — `requirements-dev.txt` (recommended) vs
   `pyproject.toml [optional-dependencies]` vs documented manual install. Lock in
   vgr-04 / at scope validation.
2. **`make test` when xdist is absent** — graceful fallback to single-process
   (recommended) vs hard-require the dep. Lock in vgr-04.
3. **vgr-04 isolation-fix size** — unknown until the parallel run is measured; may
   split at implement time.
4. **aet-setup scaffold surface** — confirm whether aet-setup ships a
   `.pre-commit-config`/Makefile _template_ injecting prettier, beyond the two prose
   files found, at vgr-05 implement time.

## Risks

- **Parallel-unsafe tests** (R-6): git/process-group tests may share state; `-n auto`
  could flake. Mitigation: measure-first task; fix isolation or scope down.
- **Dependency-stance drift** (R-6): introducing any dep cuts against the repo's
  "portable, no manifest" ethos; ADR-026 must record the trade-off explicitly.
- **Lost YAML/JSON formatting** (R-1): accepted; `check-yaml` still validates syntax.
- **Downstream expectation** (R-7): repos previously scaffolded with prettier are
  unaffected; only new scaffolds change.

## Divergence Summary

_Recorded: 2026-07-15 — Branch: vgr-04-pytest-xdist-parallel_

### Changed from plan

- **vgr-04 Task 3 (fix parallel-unsafe tests):** The planned approach was to isolate shared state via `tmp_path`/`monkeypatch`/unique directories. The implementation-time measurement revealed the actual failure mode was a Python stdlib `queue` module name collision under `pytest-xdist` workers, not shared mutable state. The fix renamed `aet-work/lib/queue.py` to `aet-work/lib/aet_queue.py` and updated imports across `aet-work/bin/*`, `aet-work/lib/*`, `tests/`, and `aet-work/references/context-isolation.md`.

### Added (unplanned)

- **`.gitignore`**: Added `.venv/` to support the documented `pip install -r requirements-dev.txt` workflow in a local virtual environment.
- **`scripts/test-merge-verified-removed.sh`**: Updated the queue-module presence check from `aet-work/lib/queue.py` to `aet-work/lib/aet_queue.py` to match the rename.

### Deferred

- None.

---

_Stage: synced_
_Next step: run `aet-ship`_
