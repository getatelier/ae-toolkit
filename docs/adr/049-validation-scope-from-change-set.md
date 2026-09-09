---
subject: targeted-validation-scope
---

# Validation Scope Is Derived from the Change Set, in Code

## Status

Accepted (2026-07-24). Sibling to ADR-047 (pipeline mode by plan size) and shares the
`evidence.default_is_code_path` primitive with ADR-025 (validation freshness). Delivered by
plan `vre-01-change-scope-targeted-validation`; motivated by
`reports/2026-07-24-validation-runtime-review.md`.

## Context

`make validate` decides what to run by shelling out to `src/aet/change_scope.py`, which today
emits a **binary** signal: `main()` prints `"tests/"` (run the whole ~1,200-test suite) or `""`
(skip pytest — the prose-only case). The Makefile branches on empty-vs-non-empty
(`Makefile:106-111`) and then runs `test-installer` **unconditionally** (`Makefile:112`).

Two costs follow from the bluntness:

- Any code change — a one-line edit in `src/aet/change_scope.py` itself, a fix in one CLI
  command — runs the entire suite. The 2026-07-24 measurement puts the suite floor at ~150 s
  of real work even after the `--dist=loadgroup` overhead is addressed separately.
- The installer smoke test (`tests/installer/test_installer.py`, plus an editable reinstall)
  runs on **every** `make validate`, including prose-only changes and changes nowhere near the
  installer surface.

The classification "did code change?" is not new: `change_scope.is_code_path` already
delegates to `evidence.default_is_code_path` (with a deliberately stricter rule — it counts
`tests/` markdown fixtures as code for the repo-wide gate), and `evidence.validation_freshness`
(ADR-025) uses the same primitive to return a `RUN` / `LINT_ONLY` / `SKIP` tier for cross-stage
re-run suppression. So the toolkit already has one shared code/non-code primitive and one tier
vocabulary; what it lacks is a `change_scope` that emits anything richer than all-or-nothing.

## Decision

`change_scope` is the **single, code-level authority for local validation scope**, and it
derives that scope from the **change set**, never from the plan's `*Stage:*` label.

1. **Emit a minimal test target list, not `"tests/"`.** `change_scope` maps the changed-file
   set to the smallest set of pytest targets that covers it (a small, explicit,
   path-prefix → test-dir table), printed on stdout for the Makefile to consume unchanged via
   `PYTEST_TARGETS` (`Makefile:17,106`). The Makefile plumbing does not change.

2. **The installer test is part of that mapping.** `test-installer` runs only when the
   installer surface changed (`scripts/install.sh`, `src/aet/cli/setup.py`). The
   "did the installer change?" decision lives in `change_scope` Python, not in Makefile shell.

3. **Scope is a tier keyed on the change set, reusing the ADR-025 vocabulary.** The tier is
   computed from what changed, aligned with `evidence.validation_freshness`'s
   `RUN` / `LINT_ONLY` / `SKIP` rather than a third, parallel vocabulary. It is **never** keyed
   on the plan stage: a `synced`-stage plan can still carry code (measured 2026-07-24; see
   ADR-025's bias-to-`RUN` for the same reasoning).

4. **Fail toward more tests.** Any uncertainty — `conftest.py`, shared fixtures, an unmapped
   path, an undetermined diff — falls back to the full suite. A wrong *skip* hides a real
   regression; a wrong *include* costs one extra run. The mapping is biased, by construction,
   to over-run, exactly as ADR-025's freshness query is biased to `RUN`.

This makes local validation scope a deterministic function of the diff, decided in code — a
peer of ADR-047's size-based pipeline-mode default, but deterministic rather than advisory
because the change set is a fact the tool can read, not a prediction the author must make.

## Consequences

- Routine changes validate faster: a focused edit runs its mapped targets, not the whole suite;
  an unrelated change stops paying for the installer smoke test.
- `change_scope` and `evidence.validation_freshness` stay on one shared code/non-code primitive
  and one tier vocabulary; a future reader finds one place, not two divergent classifiers.
- The bias-to-full-suite makes the failure mode safe by construction: a mapping gap or a new
  test directory costs an unnecessary run, never a skipped-but-needed one — until someone adds a
  mapping entry to tighten it.
- The mapping table is a maintenance surface: a new `src/` subsystem without a table entry runs
  the full suite until mapped. That is the safe default and an intentional prompt to map it.
- Installer coverage is now conditional; a change that alters installer behavior indirectly
  (e.g. a dependency the installer relies on) must be mapped to the installer target explicitly,
  or it falls back to full-suite — never to silently skipping installer tests on an installer
  change.
- The resolved target list is now a published output, not just an internal decision.
  `--explain` prints it as the `AET_TEST_SCOPE_TARGETS:` marker so telemetry can label a
  `make validate` by what it actually ran (`tap-06`); the sub-make that runs pytest is invisible
  to a session log, so without the marker every narrowed run recorded as `full-suite` and this
  ADR's win was unmeasurable. The marker is the machine contract — the human `--explain` prose
  beside it stays free to change. `telemetry`'s `full-suite`/`impact` vocabulary is unchanged:
  a run resolving to `tests/` is still `full-suite`, and the fail-toward-more-tests bias carries
  over, since a missing or malformed marker falls back to `full-suite`.

## Alternatives Considered

- **Keep the binary `"tests/"`/skip contract.** Rejected: it is the source of the redundant
  full-suite and unconditional-installer cost the 2026-07-24 review measured; the plumbing to
  consume a target list already exists, so the binary is a self-imposed limit.
- **Key the tier on the plan's `*Stage:*` footer** (e.g. skip tests for `synced`). Rejected:
  `synced` is not reliably code-free; keying on a lifecycle label rather than the diff
  re-introduces exactly the staleness ADR-025 removed.
- **Select tests by import-graph / coverage analysis.** Rejected for now: powerful but
  false-skip-prone and a heavy maintenance surface; a conservative static path table is
  auditable and fails safe. Revisit only if the table's maintenance cost grows (PRD open
  question).
- **A third code/non-code classifier local to `change_scope`.** Rejected: `change_scope`
  already delegates to `evidence.default_is_code_path`; forking a parallel classifier would let
  the two drift. Extend the shared primitive instead.
