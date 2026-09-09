# PRD: Validation-Runtime Efficiency & Determinism

*Stage: synced*
*Next step: run `aet-ship`*

## Overview

Make the AE Toolkit's validation runtime **faster on routine changes** and **deterministic
where it currently relies on prose**. Two measured problems motivate this initiative
(evidence: `reports/2026-07-24-validation-runtime-review.md`):

1. **Avoidable test serialization.** The full suite runs ~76 s (+47%) slower under
   `--dist=loadgroup` (238 s) than `--dist=load` (162 s), because a single
   `xdist_group("orchestrator")` marker pins **15 files / 171 tests** to one worker while
   the other seven idle. Dropping the group is **not** an option — a safety probe running
   it unpinned failed 3/3 (a different orchestrator test each time); the group exists for
   real isolation. The ~76 s is reclaimable only by refining the group taxonomy and
   shrinking the serial pole.

2. **Coarse, partly-prose validation scope.** `src/aet/change_scope.py` today emits a
   binary signal — `"tests/"` (whole suite) or `""` (skip) — so any code change runs all
   ~1,200 tests, `test-installer` runs on **every** `make validate` regardless of what
   changed, and QA-freshness re-run suppression is driven **only** by an injected prose clause
   the QA agent may or may not honor. `AET_QA_FRESHNESS` is exported but has no runtime consumer
   (verified 2026-07-24 — observability-only), so nothing enforces the suppression in code.
   Unlike the `aet ship merge` ancestry regression
   (`docs/bugs/2026-07-24-aet-ship-merge-does-not-merge-branch.md`), every freshness ignore-path
   is *safe* (bias-to-`RUN`; the fail-closed verdict gate is separate — ADR-025), so this is an
   efficiency-hardening opportunity, not a correctness hole.

This initiative moves validation-scope decisions into `change_scope` as a code-derived,
change-set function (targeted test list, conditional installer, change-set tier), refines
the orchestrator test group so mutually-safe tests parallelize, shrinks the serial pole, and
makes the QA-freshness re-run suppression deterministic (ADR-025-consistent — the fail-closed
verdict gate is untouched).

## Goals

- **G-1**: Reclaim the measured ~76 s/run of avoidable orchestrator-test serialization
  **without weakening isolation** — the suite must stay green across repeated runs.
- **G-2**: Make validation scope (which tests, whether the installer runs, which tier) a
  deterministic function of the **change set**, computed in `change_scope` code — never
  from the plan's stage name and never as prose an agent must interpret.
- **G-3**: Make the QA-freshness re-run suppression **deterministic** — enforced by the
  runtime, not left to an agent honoring a prose clause — while keeping the fail-closed verdict
  gate untouched (ADR-025). An efficiency-determinism gain, not a correctness fix.
- **G-4**: Cut redundant validation work on routine changes (whole-suite when a subset
  suffices; unconditional installer smoke test) so common edits validate faster.

## Non-Goals

- **Does not remove or weaken `--dist=loadgroup`.** The safety probe proved the group is
  load-bearing (3/3 failures unpinned); the lever is refining the taxonomy, not deleting it.
- **Does not address Rec 1 (the cfg-01 72%-of-wall-clock session).** That is a task-sizing
  / model concern blocked on turn-level telemetry the toolkit does not emit today (measured:
  the finest telemetry granularity is the stage record — no per-tool-call data). It is
  **carved out as a separate initiative**, parked at
  `content/backlog/cfg-01-session-efficiency.md`, and is not planned here.
- **Does not rewire the Makefile's `PYTEST_TARGETS` plumbing.** `make validate` already
  consumes `change_scope` stdout as `PYTEST_TARGETS` in `Makefile`; this initiative
  changes what `change_scope` emits, not how the Makefile consumes it.
- **Does not touch the sibling base-resolver bug** (`_determine_pr_base` returning the
  branch's own name). That stays owned by the `epi-*` resolver epic.
- **Does not touch the fail-closed verdict gate** (`_require_passing_verdict`). Per ADR-025
  decision 4, freshness suppresses only redundant re-runs; review/CSO still emit their own
  passing verdicts. R-6 hardens the *suppression*, never the correctness gate.
- **Does not make `change_scope` an unbounded/speculative test selector.** The mapping stays
  a small, conservative, auditable table that fails *toward* running more tests.

## Requirements

- **R-1**: `src/aet/change_scope.py` maps the changed-file set to a **minimal pytest target
  list** (e.g. `tests/orchestrator/ tests/gate/`) emitted on stdout, replacing the blunt
  `"tests/"`. `make validate` consumes it unchanged via `PYTEST_TARGETS` in `Makefile`.
- **R-2**: The installer smoke test (`test-installer`) runs **only when the installer
  surface changed** (`scripts/install.sh`, `src/aet/cli/setup.py`), driven by a signal
  `change_scope` emits — not the unconditional `Makefile` line. The
  "did the installer change?" logic lives in `change_scope` Python, not Makefile shell.
- **R-3**: The scope decision is a **tier computed from the change set**, never from the
  plan's `*Stage:*` label (a `synced` plan can still carry code — see
  `reports/2026-07-24-validation-runtime-review.md` and the validation-freshness note).
  Uncertain or broad changes (shared fixtures, `conftest.py`, unmapped paths) fall back to
  the full suite — the mapping fails toward *more* tests, never fewer.
- **R-4**: The monolithic `pytest.mark.xdist_group("orchestrator")` (15 files) is split into
  **≥2 resource-scoped subgroups** keyed on the real shared resource (process group, cwd,
  telemetry dir, git repo), so mutually-safe heavy tests spread across workers while
  genuinely-conflicting tests stay co-grouped and serialized.
- **R-5**: The orchestrator **serial pole (~120 s)** is reduced by replacing fixed `sleep`
  waits and avoidable subprocess fixtures in the hottest orchestrator tests with
  event/poll-based waits, measured against the 238 s baseline.
- A sixth requirement — **deterministic QA-freshness suppression** — was reframed during scope
  validation and is **deferred out of this sprint** pending a keep / defer / drop decision. It
  is documented under *Deferred Requirements* below and is **not** part of this initiative's
  committed scope (R-1 through R-5).

## Deferred Requirements (not in this sprint)

One requirement surfaced during scope validation was reframed and **deferred as an idea**, not
queued: **deterministic QA-freshness re-run suppression** (originally R-6). It is an
efficiency-determinism gain — not a correctness fix; the fail-closed verdict gate
(`_require_passing_verdict`) stays untouched (ADR-025 decision 4). The full analysis and what it
would take to pick it up are parked at
**`content/backlog/deterministic-qa-freshness-suppression.md`**. No task traces R-6; `vre-04` is
neither written nor queued.

## User Stories

- As a toolkit user changing a handful of source files, I want `make validate` to run only
  the tests mapped to my change set, so I get a fast targeted signal instead of the full
  ~150 s+ suite. (satisfies: R-1)
- As a toolkit user who did not touch the installer, I want `test-installer` skipped so I do
  not pay for an unrelated smoke test on every validate. (satisfies: R-2)
- As a toolkit maintainer, I want the validation tier derived from what actually changed —
  not the plan's stage label — because a `synced` plan can still carry code. (satisfies: R-3)
- As a toolkit maintainer running the full suite, I want the orchestrator tests spread across
  workers by their real resource conflicts, so the suite finishes ~76 s faster with no new
  flakes. (satisfies: R-4)
- As a toolkit maintainer, I want the slowest orchestrator tests to stop sleeping and
  spawning unnecessarily, so the serial pole shrinks toward the ~150 s floor. (satisfies: R-5)

## Acceptance Criteria

- [ ] `python -m aet.change_scope` emits a minimal target list derived from the changed
      files (not the blunt `"tests/"`); `make validate` runs `pytest` against exactly that
      list via `PYTEST_TARGETS`, with no Makefile plumbing change. (satisfies: R-1)
- [ ] A change set touching neither `scripts/install.sh` nor `src/aet/cli/setup.py` does not
      run `test-installer`; a change touching either does. The decision is emitted by
      `change_scope`, not encoded as Makefile shell logic. (satisfies: R-2)
- [ ] The scope tier is computed from the change set in `change_scope`; a plan whose footer
      says `*Stage: synced*` but whose diff includes a `.py` file still selects the code
      tier. Unmapped/shared-fixture/`conftest.py` changes select the full suite.
      (satisfies: R-3)
- [ ] `xdist_group("orchestrator")` is replaced by ≥2 resource-scoped subgroups across the
      15 marker sites; full-suite wall clock drops by ≥60 s versus the 238 s baseline.
      (satisfies: R-4)
- [ ] The orchestrator serial pole is measurably smaller (the hottest orchestrator tests no
      longer use fixed `sleep` where an event/poll wait suffices), re-measured against the
      238 s baseline. (satisfies: R-5)
- [ ] The full suite stays green across **≥10 consecutive** `-n auto --dist=loadgroup` runs
      after the group-split and pole work — isolation preserved, no re-introduced flake.
      (satisfies: R-4, R-5)
- [ ] `make validate` passes after all changes. (satisfies: R-1, R-2, R-3, R-4, R-5)

## Technical Notes

- **change_scope contract (R-1/R-2/R-3).** Today `decide(paths)` returns `FULL`/`DOCS` and
  `main()` prints `"tests/"` or `""`; the Makefile branches on empty-vs-non-empty
  in `Makefile`. The target list and installer signal extend this stdout contract —
  the mapping should be a small, explicit, conservative table (path prefix → test dir), with
  a documented fallback to the full suite for `conftest.py`, shared fixtures, and any unmapped
  path. **Fail toward more tests, never fewer** — a wrong skip hides a real regression.
- **Installer signal shape (R-2).** Two viable implementations: (a) `change_scope` includes
  `tests/installer/test_installer.py` in the target list when the installer surface changed
  and the unconditional Makefile line is removed; or (b) `change_scope` emits a discrete
  installer flag the Makefile reads with a minimal branch. Option (a) folds the installer
  into the same file-to-test mapping and keeps all decision logic in Python — preferred;
  implementation choice is left to the plan, but the *decision* must live in `change_scope`.
- **Tier vs. stage (R-3).** The decision must key on the change set, never the `*Stage:*`
  footer. `synced` is not reliably code-free — see the 2026-07-24 measurement and the
  validation-freshness spike. This preserves the current change-set-keyed policy and only
  extends it from binary to tiered. **Reuse** `evidence.validation_freshness`'s
  `RUN`/`LINT_ONLY`/`SKIP` vocabulary rather than inventing a parallel tier (ADR-049);
  `change_scope` already shares `evidence.default_is_code_path`, so extend that primitive, do
  not fork a third classifier.
- **Group taxonomy (R-4).** The 15 `xdist_group("orchestrator")` sites are module-level
  `pytestmark`s. Subgroups must be keyed on the real shared resource so that only
  genuinely-conflicting tests remain serialized together. The 3/3 unpinned failure
  (`test_batch_spawns_task_promoted_mid_run`,
  `test_emit_stage_session_classifies_failure_for_nonzero_exit`,
  `test_cleanup_kills_process_groups_on_shutdown`) marks the tests that must **not** be
  scattered blindly. The suite floor is ~150 s of real work; the target is the ~76 s of
  avoidable serialization on top of it.
- **Serial pole (R-5).** The ~120 s orchestrator-group serial time is dominated by fixed
  sleeps and subprocess fixtures. Prefer event/poll waits with a bounded timeout over
  `time.sleep`. This is separable from R-4 but touches the same test files, so it is
  sequenced after the group-split to avoid marker-churn conflicts.
- **Freshness suppression (R-6).** `_qa_freshness_decision` (`src/aet/cli/orchestrator.py`) is already computed and exported as
  the `AET_QA_FRESHNESS` env var, but that env var has **no runtime consumer**
  (verified 2026-07-24 — read only in tests and run logs), so the injected `_freshness_clause`
  prose is the sole driver of re-run suppression. Making the suppression deterministic must stay
  consistent with **ADR-025** (decision 4: freshness modulates only prompt + env and never
  touches the fail-closed gate) and **ADR-031** (enforce on evidence, not on a guess). This is
  efficiency hardening — **not** the correctness class the ship-merge ancestry check fell into;
  every freshness ignore-path is already safe (bias-to-`RUN`, separate verdict gate). Keep the
  prose clause as agent-facing context; add the deterministic consumer alongside it.
- **Measurement harness.** R-4/R-5 acceptance is measured, not asserted — re-run the same
  A/B the report used (`-n auto` loadgroup vs. load, plus the ≥10-run green streak) so the
  ~76 s reclaim and no-new-flake guarantee are demonstrated, not claimed.

## Open Questions

- Should the file-to-test mapping be a static path-prefix table in `change_scope`, or derived
  from test-import analysis? (Default: static, conservative table; revisit only if
  maintenance cost grows — import analysis risks false skips.)
- Should R-5 (serial-pole speedup) be its own plan or fold into R-4 (group-split)? (Default:
  separate atomic plan, sequenced after R-4; both re-measured against the 238 s baseline.)
- How aggressive should the R-6 gate be — block progression on a stale QA verdict, or force a
  QA re-run? (Reserve for `aet-validate-scope` / an ADR; default is the least-surprising
  action that makes freshness non-bypassable.)

## Scope Validation Findings (2026-07-24)

`aet-validate-scope` surfaced one code contradiction and two refinements:

1. **R-6 reframed (was a code contradiction).** As originally approved, R-6 read as "replace the
   prose freshness clause with a code-level *gate*," which partly re-opens **ADR-025** — that ADR
   *deliberately* keeps freshness as a prompt clause + observability env signal and leaves the
   fail-closed verdict gate (`_require_passing_verdict`) untouched, because freshness is a
   bias-to-`RUN` *efficiency* optimization, not a correctness control. Verified: `AET_QA_FRESHNESS`
   has **no runtime consumer** (observability-only), so the prose clause is today the sole driver
   of suppression — but every ignore-path is safe. R-6 is therefore reframed to its ADR-consistent
   core: make the re-run **suppression deterministic**, never touching the verdict gate. This is
   efficiency hardening, not the correctness class the ship-merge bug fell into. **`vre-04` is
   deferred and parked as an idea** (`content/backlog/deterministic-qa-freshness-suppression.md`) — if
   picked up it needs an ADR extending ADR-025 (freshness suppression becomes enforced, not
   observability-only) authored before `aet sprint add`.
2. **R-3 tier reuses the existing vocabulary (refinement).** `change_scope` already shares
   `evidence.default_is_code_path`, and `evidence.validation_freshness` already defines
   `RUN`/`LINT_ONLY`/`SKIP`. R-3's tier reuses that vocabulary rather than forking a third
   classifier (recorded in ADR-049).
3. **ADR authored.** `docs/adr/049-validation-scope-from-change-set.md` is the home for
   R-1/R-2/R-3 (sibling to ADR-047; shares the ADR-025 primitive). R-4/R-5 are a test-isolation
   convention documented in-plan + `CONVENTIONS.md`, not an ADR.

**UI Coverage Lens:** not applicable — this initiative has no user-facing interface (CLI/test
runtime only). **Intake triage:** confirmed enhancement, not a defect (see record below).

## Proposed Task Decomposition

*(Preview for review; atomic `docs/plans/*.md` files + queue are materialized after PRD
approval, in Step 1 create-stories/plan → Step 3 `aet sprint add`.)*

| Ticket | Covers | Scope | Depends on |
|---|---|---|---|
| `vre-01-change-scope-targeted-validation` | R-1, R-2, R-3 | `change_scope` emits a code-derived minimal target list + conditional installer signal + change-set tier, conservative FULL fallback. Files: `src/aet/change_scope.py`, `tests/test_change_scope.py` (+ possible thin Makefile installer-line removal). | — |
| `vre-02-orchestrator-xdist-subgroups` | R-4 | Split `xdist_group("orchestrator")` into resource-scoped subgroups across the 15 sites; keep the 3 proven-conflicting tests co-grouped. Files: 15 `tests/**` marker sites + taxonomy note. | — |
| `vre-03-orchestrator-serial-pole-speedup` | R-5 | Replace fixed sleeps / heavy fixtures in the hottest orchestrator tests with event/poll waits. Files: hottest `tests/orchestrator/*.py`. | `vre-02` |
| `vre-04-qa-freshness-deterministic-suppression` *(deferred — parked at `content/backlog/deterministic-qa-freshness-suppression.md`)* | R-6 | Runtime deterministically suppresses the redundant re-run on `SKIP`/`LINT_ONLY`; verdict gate untouched (ADR-025 decision 4). Files: `src/aet/cli/orchestrator.py`, `tests/orchestrator/**`. | — |

## Intake Triage Record

Confirmed **feature/enhancement**, not a reproducible defect: Recs 2–6 harden and speed up
the validation runtime (targeted scope, conditional installer, group-split, faster tests,
code-enforced freshness). The one defect in the 2026-07-24 batch — `aet ship merge` recording
a merge without merging — was correctly routed to `aet-bug-report` (Initiative 1, PR #192)
and is not part of this PRD.

## Divergence Summary — vre-02-orchestrator-xdist-subgroups

Implementation matches intent. The 15 `xdist_group("orchestrator")` sites were replaced
with four resource-scoped subgroups (`process-group`, `cwd`, `telemetry-dir`, `git-repo`)
as documented in `docs/CONVENTIONS.md` "Test parallelization". The three proven-conflicting
tests remain in `process-group` with the rest of the heavy subprocess tests.

One incidental fix landed: `_finalize_task` in `src/aet/cli/orchestrator.py` now trusts
`awaiting_merge`/`merged` state before verifying the worktree still exists, eliminating a
pre-existing flake in `test_max_jobs_three_integration_steps_serialize` where the worktree
is intentionally removed after integration.

Measurement (8 workers, `-n auto --dist=loadgroup`, 10 consecutive runs): mean ~103.6 s,
vs. 238 s baseline → ~134 s improvement, 10/10 green.
