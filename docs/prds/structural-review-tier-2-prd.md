# PRD: Structural Review — Tier 2 Follow-ups

## Overview

The structural review (`content/aet-structural-review/`, 2026-08-09) identified twelve order-of-attack items and six beads steals, distilled in `13-value-snapshot.md` to a prioritized sequence. Tier 1 is delivered or underway (the slc series merged footer/stage atomicity, verdict-writer consolidation, and the content-addressed ledger per ADR-055). This PRD schedules the six **Tier 2 moves**: the remainder of the incident-evidenced prose→code tranche (item 7 T1), the `aet context` command (steal 02), the boundary-contract and identity-conflation gate lenses (item 4), the run-scoped handoff note (item 5), generated-or-absent documentation (steal 05), and the `single-pr` rehearsal (item 8). Each move is evidence-backed by the review corpus; each converts prose duties or unverified configurations into code that fails closed.

**Intake triage:** all six moves are features/enhancements (new commands, new lenses, new gates), not reproducible defects in existing code. Planning pipeline applies.

## Goals

- Delete the prose-implemented mechanics the review's incident log proves are unreliable (verdict side-channels, merge-verification prose, learnings written by hand, duplicated preambles).
- Make the two defect classes that cost the most consumer-project hours (boundary-contract and identity-conflation bugs — 25 of 111 consumer entries) catchable by a mechanical gate instead of review judgment alone.
- Stop later pipeline stages re-deriving context from zero (39.7-min review on a 635-line diff against an 11-min baseline).
- Make the docs corpus self-checking: one subject, one live rule, enforced by `aet docs lint`; references generated or absent, never hand-copied.
- Exercise the `single-pr` + shadow-config + heavy-dependency configuration — the one the hardest client repos actually run — with a rehearsal instead of production incidents.

## Non-Goals

- Migrating the ~166 judgment instructions identified by the prose-to-code study — judgment stays prose; only mechanical duties move to code.
- Patching the five drifted plans (superseded: slc-03 deleted plan drift and the `status` field entirely).
- Tier 3 tranches (duplicated-across-skills duties, single-skill bookkeeping), the isolation re-pricing experiment (item 9), the `orchestrator.py` split (item 11), and the telemetry adapter (item 2, held until the ledger settles).
- Implementing the parked cross-cutting-completeness and auth-infra-blind-spots PRDs — their disposition is an Open Question, not scope.
- Deleting ADR immutability, deleting the fail-closed verdict gate, or deleting `single-pr` mode — all three are explicitly declined by the review.
- Worktree environment setup (item 0) and cross-project defect mining (item 3) — Tier 1, tracked separately; the rehearsal in R-12 exercises item 0 but does not implement it.

## Requirements

- **R-1**: `aet learnings append` — a code writer for `.agents/learnings.jsonl` (schema-validated, one command), adopted by the three prose call sites (aet-bug-report, aet-evolve, aet-implement). Today no command writes learnings; 169 entries exist and zero are read.
- **R-2**: Merge-verification prose→code completion — the study §3.1.3 remainder: squash-merge diff-match fallback (`aet ship verify --squash-fallback`, N=20 threshold), atomic record-then-delete (`aet ship close --delete-branch`), stacked-PR detection with PR-body injection in `aet ship open`, `aet ship split`, and trunk substitution resolved by commands themselves. Each halt condition becomes an exit code, not a prose instruction.
- **R-3**: `aet context` — one command emitting the session's workflow context: the fixed Shared Preamble fields (branch, repo state, AGENTS.md, learnings, active plan/PRD stage) as JSON plus a stage banner, with token budget adapted to MCP vs bare CLI, overridable wholesale by a project-local `PRIME.md`, plus `--memories-only` and `--hook-json` modes (SessionStart envelope for Claude Code, Codex, Gemini).
- **R-4**: Preamble/banner absorption — the 16 Shared Preamble blocks and 11 stage-banner prints across the skills corpus are replaced by consumption of `aet context` (~30 duplicated prose blocks deleted).
- **R-5**: Current-rules digest — generated from ADR frontmatter (`subject:`, `supersedes:`), never hand-maintained; emitted by `aet context`; durable insights (mined learnings at promotion threshold) injected at prime time rather than filed unread.
- **R-6**: Boundary-contract lens — when a diff touches both a response shape and a client consumer, a mechanical gate fires off the changed-file set (ADR-049 scoping mechanism) requiring a test that asserts they agree. ADR-008 declared this as prose; the consumer data proves declared-and-not-effective.
- **R-7**: Identity-conflation lens — a plan or diff that introduces a second identifier for the same entity must name both identifiers and state which one persists; the check fires mechanically, not by reviewer recall.
- **R-8**: Run-scoped handoff note — the implement session writes one artifact (decisions taken, pre-existing failures, validation commands, evidence path); each later stage appends; the orchestrator injects it into subsequent stage prompts. Audit R1, three weeks unbuilt.
- **R-9**: Docs contradiction lint — ADR frontmatter gains `subject:`/`supersedes:` (extending ADR-040's invariants-as-data grammar); `aet docs lint` fails when one subject has two live rules; the three known live contradictions (intake-commit rules, direct-JSON-edit permission, footer-format strings) are resolved.
- **R-10**: Generated CLI reference — a CLI reference doc generated from the Typer command tree, marked `AUTO-GENERATED: do not edit manually`; hand-maintained CLI mirrors are deleted or replaced by pointers to the generated doc.
- **R-11**: Plan archival at closure — merged/abandoned plans move to `docs/plans/archive/` at terminal closure, so the live directory `init-queue` scans holds only live work (173 settled files sit there today).
- **R-12**: `single-pr` rehearsal — a fixture-repo rehearsal of the configuration used in anger (`single-pr` + non-trunk integration branch + shadow config + a real dependency install), run whenever integration or worktree paths change. Modeled on the nightshift rehearsal precedent.

## User Stories

- As a toolkit maintainer, I want learnings appended by a command so that every bug-fix session writes a schema-valid entry without remembering the format (satisfies: R-1)
- As an operator, I want squash-merged PRs verified by code so that `aet ship merge` can never again record "Merging main into main" as a merge (satisfies: R-2)
- As an agent starting a session, I want one command for workflow context so that I stop half-executing 16 prose preambles and hand-parsing the wrong footer (satisfies: R-3, R-4)
- As an operator, I want current rules injected at session start so that the 169 filed learnings and the ADR lineage actually change what the agent does (satisfies: R-5)
- As a consumer-project maintainer, I want boundary and identity bugs caught at the gate so that the 25-of-111 defect class stops passing the full pipeline green (satisfies: R-6, R-7)
- As a review-stage session, I want the implement session's decisions and validation commands handed to me so that I stop re-investigating what QA already navigated (satisfies: R-8)
- As a toolkit maintainer, I want docs contradictions to fail lint so that the next five-plan defect class dies at lint time instead of at run time (satisfies: R-9, R-10, R-11)
- As an operator of `single-pr` client repos, I want the configuration rehearsed in CI-local testing so that the mode my hardest projects run in stops being unverified (satisfies: R-12)

## Acceptance Criteria

- [x] `aet learnings append` writes a schema-valid entry and the three skill call sites invoke it (satisfies: R-1)
- [ ] A squash-merged task verifies via diff-match fallback in code; a stacked PR is detected at `aet ship open`; halt conditions exit non-zero with named codes (satisfies: R-2)
- [ ] `aet context` emits the full preamble battery as JSON + banner, honors `PRIME.md` override and both hook modes, and the 16 preamble blocks + 11 banners are deleted from skills (satisfies: R-3, R-4)
- [ ] `aet context` output includes the generated current-rules digest and promoted learnings; no hand-maintained copy of either exists (satisfies: R-5)
- [ ] A diff touching a response shape and its client consumer fails the gate without an agreement test; a plan introducing a second identifier for one entity fails without naming both (satisfies: R-6, R-7)
- [x] A run's review-stage prompt contains the handoff note written by its implement session; the note records all four fields (satisfies: R-8)
- [ ] `aet docs lint` fails on a deliberately introduced dual-live-rule subject; the three known contradictions are gone (satisfies: R-9)
- [ ] The CLI reference carries `AUTO-GENERATED` and is reproducible from the command tree; stale mirrors are deleted (satisfies: R-10)
- [x] Merged plans no longer occupy the live `docs/plans/` scan set; closure moves them to `archive/` (satisfies: R-11)
- [ ] The `single-pr` + shadow-config + real-deps rehearsal passes on a fixture repo and is wired to run when integration/worktree paths change (satisfies: R-12)

## Technical Notes

- **Sequencing:** the snapshot schedules Tier 2 behind the Tier 1 ratification; the slc series has merged, so the fork is resolved in favor of the ledger. T1's closure duties targeted the footer surface that slc-05 now owns in code — scope R-2 against the post-slc state, not the pre-slc study text. Footer/stage atomicity and verdict-writer consolidation are **already delivered by slc-05** and are excluded from R-2.
- **Overlap check required at scope validation:** `docs/plans/mvr-01` (merged), `docs/prds/merge-verified-redundancy-prd.md` (scope-validated, remainder unclear), and the parked `cov-02`/`cov-04` plans (plan-approved, unimplemented) touch R-2/R-6/R-7 territory. Disposition before plan drafting.
- **R-3/R-5 coupling:** the review specifies the current-rules digest ships inside the `aet context` shape ("in one shape already proven in the field" — `bd prime`).
- **R-12 ↔ item 0 coupling:** the rehearsal's real dependency install exercises the worktree-setup work; it is the natural verification vehicle whenever item 0 lands.
- **Lens mechanics:** `src/aet/change_scope.py` (ADR-049 changed-file-set scoping) is the existing trigger mechanism R-6/R-7 build on; `aet gate submit` (slc-05) is the verdict path the new lenses write through.
- **Ledger discipline:** every new mechanism emits ledger events where the taxonomy supports it; no new mechanism reintroduces a prose writer around `aet gate submit` or `aet state set-stage`.
- Ticket prefix for this PRD's plans: `t2r` (unused in `docs/plans/`).

## Open Questions

1. **cov-02 / cov-04 disposition — RESOLVED at scope validation (2026-08-10).** cov-04 is superseded by t2r-08: the R-6 boundary-contract lens subsumes its review-side coverage check. cov-02 is abandoned: its API-boundary item already shipped as prose (`skills/aet-tdd/SKILL.md`), and its tdd-side remainder (plan-tests enumeration, coverage→0% completion check) is declined — the review corpus carries no incident evidence for it; reopen if defects surface. Dispositions recorded in both plan files.
2. **Parked PRDs (STILL OPEN, user decision — outside this PRD's scope):** cross-cutting-completeness and `auth-infra-blind-spots-prd.md` are scope-validated and unimplemented. Ship or close — per the review, a validated PRD that never enters a sprint is worse than none.
3. **merge-verified-redundancy PRD remainder — RESOLVED at scope validation (2026-08-10).** mvr-01 is merged and has no `mvr-*` siblings; the PRD's premise ("`status` the single source of truth") was voided by ADR-055 deleting the `status` field. Closed as superseded bookkeeping. No collision with R-2 — t2r-02's scope was verified against the post-slc surface.
4. **Rehearsal fixture ecosystem — RESOLVED:** npm (`npm ci`) for the R-12 fixture (t2r-13); composer coverage arrives with item 0's `worktree_setup`, which the rehearsal then exercises.
5. **Learnings injection threshold — RESOLVED:** t2r-07 degrades to top-N recent entries; the item-3 recurrence-threshold mechanism plugs into the same selector interface when it lands.

<!-- markdownlint-disable MD024 -->

## Divergence Summary

### t2r-01-learnings-append-cli

_Recorded: 2026-08-10 — Branch: t2r-01-learnings-append-cli_

#### Changed from plan

- None — the implementation matches the plan intent for R-1.

#### Added (unplanned)

- None.

#### Deferred

- Task 5 (merge branch to main and verify integration): deferred to `aet-ship` closure; not part of the implementation/docs-sync stage.

### t2r-02-ship-squash-verify-fallback

_Recorded: 2026-08-10 — Branch: t2r-02-ship-squash-verify-fallback_

#### Changed from plan

No meaningful divergences between the t2r-02 plan and the implementation.

#### Added (unplanned)

- `tests/cli/test_build_parsers.py` updated to register the new `verify`
  subcommand in the parser inventory. This is a mechanical test-maintenance
  change driven by adding `aet ship verify`, not a functional divergence.

#### Deferred

- R-2 remainder (stacked-PR detection in `aet ship open`, `aet ship split`, and
  trunk substitution) is explicitly deferred to the sibling plan
  `t2r-03-ship-stacked-pr-split-trunk`, per the original plan.
- The remaining Tier 2 requirements (R-1, R-3 through R-12) are outside the
  t2r-02 slice and remain open on this PRD.

### t2r-04-aet-context-command

_Recorded: 2026-08-10 — Branch: t2r-04-aet-context-command_

#### Changed from plan

- R-3 (`aet context`) implemented as specified in `docs/plans/t2r-04-aet-context-command.md`; no material contract changes.

#### Deferred

- t2r-04 task 10 (merge branch to main and verify integration) is deferred to the `aet-ship` stage, consistent with the standard pipeline.

### t2r-10-run-handoff-note

_Recorded: 2026-08-10 — Branch: t2r-10-run-handoff-note_

#### Changed from plan

- R-8 implemented as specified; no material contract changes.

#### Deferred

- t2r-10 task 8 (merge branch to main and verify integration) is deferred to the `aet-ship` stage, consistent with the standard pipeline.

### t2r-11-generated-cli-reference

_Recorded: 2026-08-10_

#### Changed from plan

_No material approach divergences for t2r-11._

#### Added (unplanned)

- Supporting test adjustments in `tests/cli/test_build_parsers.py`, `tests/cli/test_retired_names.py`, and `tests/test_change_scope.py` were needed to accommodate the generated `docs/CLI.md` artifact and the new `tests/cli/test_docs_generate.py` drift guard.

#### Deferred

- t2r-11 Task 6 (merge branch to main and verify integration): deferred to the ship stage.

### t2r-12-plan-archival-at-closure

_Recorded: 2026-08-10_

#### Changed from plan

- Task 4 (scan exclusion): only the `plans_lint` module docstring needed updating; corpus scanners already use non-recursive `*.md` globs, so no code-path change was required to exclude `docs/plans/archive/`.

#### Added (unplanned)

- `tests/cli/test_ship_close.py`: extended the existing ship-close integration test to assert the plan is archived at terminal closure and that the ledger `land` payload carries `archived_to`.
- `tests/queue/test_queue.py`: added direct unit tests for `commit_and_push_plan_change` archive move and fail-closed abort behavior.
- `scripts/validate-skills.sh`: excluded `docs/plans/archive/` from internal markdown link checks so archived relative links do not produce false-positive validation failures.

#### Deferred

- None.

### Branch: t2r-05-skills-preamble-absorption

_Recorded: 2026-08-10_

#### Changed from plan

- No meaningful divergences between the t2r-05 plan and the implementation.

#### Added (unplanned)

- None.

#### Deferred

- t2r-05 Task 6 (merge branch to main and verify integration) is deferred to the `aet-ship` stage, consistent with the standard pipeline.

---

_Recorded: 2026-08-11 — Branch: t2r-06-adr-frontmatter-docs-lint_

### Changed from plan

- Added directory-target support for `must_contain` / `must_not_contain` rules so
  the `must_not_contain "commit the plan files" scoped to skills/` rule could be
  expressed directly. The plan described the rule as scoped to `skills/`; the
  base rule engine previously only supported file targets.

### Added (unplanned)

- None.

### Deferred

- Task 9 (merge branch to main and verify integration): deferred to the
  `aet-ship` closure stage, consistent with the standard pipeline.

---

### t2r-07-context-digest-injection

_Recorded: 2026-08-11 — Branch: t2r-07-context-digest-injection_

#### Changed from plan

- None — the implementation matches the R-5 plan intent.

#### Added (unplanned)

- `tests/conftest.py`: extended `sys.path`/`PYTHONPATH` setup to include the repo root alongside `src/`, keeping test imports consistent with the new R-5 test fixtures.
- `tests/fixtures/context/{claude_code,codex,gemini}_envelope.json`: updated the hook-mode SessionStart envelope fixtures to include the new `rules_digest` and `durable_insights` fields introduced by the extended `aet context` JSON shape.

#### Deferred

- Task 7 (merge branch to main and verify integration): deferred to the `aet-ship` closure stage, consistent with the standard pipeline.

---

### t2r-09-identity-conflation-lens

_Recorded: 2026-08-12 — Branch: t2r-09-identity-conflation-lens_

#### Changed from plan

- No meaningful divergences between the t2r-09 plan and the implementation.
  The identity-conflation lens (`src/aet/identity.py`), gate wiring
  (`src/aet/cli/gate.py`), targeted tests, `change_scope` mapping, and plan
  template documentation all match the plan intent.

#### Added (unplanned)

- None.

#### Deferred

- Task 6 (merge branch to main and verify integration): deferred to the
  `aet-ship` closure stage, consistent with the standard pipeline.

---

### t2r-13-single-pr-rehearsal

_Recorded: 2026-08-12 — Branch: t2r-13-single-pr-rehearsal_

#### Changed from plan

- Task 4 end-state assertions: the existing `_finalize_task` path did not seal a
  single-pr task to `merged` after the child had already integrated locally and
  recorded a `merge_commit`. The implementation added that sealed transition in
  `src/aet/cli/orchestrator.py` so both tasks reach `merged` and unblock
  dependents, matching the ADR-045 "done means integrated" contract the
  rehearsal asserts.

#### Added (unplanned)

- `scripts/validate-skills.sh`: skip `node_modules` directories during the
  internal markdown link scan. This prevents the corpus validator from treating
  third-party dependency markdown as maintained content when the npm fixture is
  installed locally.

#### Deferred

- Task 6 (merge branch to main and verify integration): deferred to the
  `aet-ship` closure stage, consistent with the standard pipeline.

---
<!-- markdownlint-enable MD024 -->

_Stage: synced_
_Next step: run `aet-ship`_
