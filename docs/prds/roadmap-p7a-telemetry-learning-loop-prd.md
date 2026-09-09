# PRD: Roadmap Phase 7a — Telemetry Surfaces + Learning Loop

## Overview

Phase 7a of the AET roadmap (`content/fable-review/09-2026-07-10-roadmap.md`, split from Phase 7 on 2026-07-19 with a recorded ordering exception: 7a may run before Phase 6 because it only *reads* the ledger and feeds `aet-evolve`). The factory's numbers stop being vibes. Doc 04 challenge 7: *"A factory has factory metrics: first-pass merge rate by tier, rework count, tokens and cost per merged task… the factory doesn't learn yet."* Doc 06 potential 1: once every transition flows through the binary, *"first-pass merge rate, rework count, cost per merged task become real."* The data plumbing already exists — frh-09's stage telemetry, nsr-06's per-task cost rollup, twe-06's clean-merge reader over settled history — but there is no canonical metric definition, no CLI surface to query it, and `aet-evolve` still consumes only mined patterns and prose learnings. This phase defines the three metrics once in code, exposes them through a new `aet metrics` subcommand, and wires them into `aet-evolve` as first-class evidence, so the system improves on numbers rather than anecdotes. Exit gate (deliberately weak, per the roadmap): the metrics are queryable through the CLI and at least one `aet-evolve` cycle runs consuming them. The strong gate — scoreboard, `aet eval`, zero-review arming — stays with 7b, strictly after Phase 6.

## Goals

- **G1**: The three factory metrics have **one canonical definition each, in code** — routing-aware first-pass merge, rework count, cost per merged task — computed read-side from the stores that already exist (settled history, telemetry archive, gate evidence), null-honest per the telemetry contract, and shared by every consumer so the desk, the CLI, and later the scoreboard can never disagree (R-1, R-2, R-3).
- **G2**: The metrics are **queryable through the CLI** — a new `aet metrics` subcommand with a human report and a `--json` projection, overall and per work class, reading settled history plus the telemetry archive, with skills-lint green throughout (R-4, R-6).
- **G3**: **`aet-evolve` consumes the metrics** — the evolve/retro flow reads `aet metrics` alongside `learnings.jsonl` and `aet mine-learnings`, and at least one recorded evolve cycle runs on the real numbers, closing doc 04's "the factory doesn't learn yet" for the telemetry half of the diet (R-5, R-7).

## Non-Goals

- **No scoreboard, no ablation table, no `aet eval`.** Those are Phase 7b, strictly after Phase 6 — the ablation needs the kimi rows and eval pairs with skills-lint. 7a builds the metric definitions 7b will reuse, nothing more.
- **No zero-review arming.** Enabling auto-merge on track record is 7b's gate, deliberately certified on Phase 6's de-correlated review data, not same-vendor self-review. 7a only makes the underlying counts accurate and visible.
- **No new telemetry emission and no new ledger write paths.** Metrics are computed read-side from existing records (stage telemetry, settled task history, gate verdicts). In particular, no `first_pass` flag is persisted onto task records at merge time — first-pass is derived retroactively (Open Questions).
- **No enforcement on metrics.** Analytics-only, reaffirming ADR-031: no code path reads these numbers to gate, kill, throttle, route, or triage. `aet-evolve` proposes skill edits with the metrics as evidence; a human applies them. The metrics observe; they never govern.
- **No multi-harness, routing, or adapter work** — Phase 6. No panel, desk-UI, or web changes; no daemon or continuous monitoring; no new storage backend (standing fence holds — this reads git-refs, history JSONL, the telemetry archive, and the evidence store, all of which exist).
- **No backfill repair or estimation.** Tasks settled before frh-09/nsr-06 have partial records. Metrics report what exists with explicit coverage counts; unknowns stay unknown (null contract), never zero-filled or interpolated.
- **No changes to the gate-evidence contract.** The four verdict kinds and their schemas (frh-10 / ADR-019) are untouched; 7a reads verdicts, it does not redefine them.

## Requirements

- **R-1**: A **canonical, routing-aware first-pass merge definition**. Today `track_record.is_clean_merge` (`src/aet/track_record.py`) requires all four verdict kinds (`REQUIRED_VERDICT_KINDS` in `src/aet/track_record.py`), while plan gate routing (`security_review` / `docs_sync`: `required|skipped` in plan frontmatter) legitimately waives gates per plan, and the desk already treats routed-away gates as optional (`src/aet/cli/desk.py`). The definition of "first-pass clean" must derive its required verdict set from the plan's routing keys — a task whose plan routed `security_review: skipped` with all required verdicts passing, no failed stage/test_run telemetry record, no repeated stage, and no `failed → in_progress` re-entry counts as first-pass-clean. This definition lives in **one shared location** consumed by both `aet metrics` and `aet desk --eligibility`, so the two surfaces cannot report different counts for the same class.
- **R-2**: A **canonical rework count** — per settled task, the number of (a) repeated stage runs (the same stage executed more than once for the task, from telemetry stage records) plus (b) `failed → in_progress`/`ready` re-entries (from the task's transition history), mirroring the two heuristics `is_clean_merge` already uses (`_has_repeated_stage`, `_has_reentry_from_failed` in `src/aet/track_record.py`). Exposed per task and aggregated (total and per work class). `failure_signatures` remain a separate signal and are not conflated into rework.
- **R-3**: **Cost per merged task with cross-run accumulation.** nsr-06's rollup (`_task_usage_aggregates` in `src/aet/cli/orchestrator.py`) sums only the *settling run's* stage records — a task reworked across N runs keeps only the last run's cost on its ledger record. The metric instead sums the task's stage telemetry across the whole archive (the scan `iter_telemetry_task_records` in `src/aet/track_record.py` already performs). Null-honest per the telemetry null contract and ADR-031: Kimi tasks have `usd: null` by design (`src/aet/usage.py`) — report tokens, keep `usd` null, never zero-fill — and aggregates carry explicit coverage counts (how many tasks contribute a known `usd`). Aggregates: total and average per merged task, overall and per work class.
- **R-4**: An **`aet metrics` subcommand** — exposed via `src/aet/cli/metrics.py` per the dispatcher contract. It reports first-pass merge rate, rework count, and cost per merged task, overall and per work class, over settled history joined with the telemetry archive and evidence store. Output follows the `status` conventions: `--json` prints the projection dict to stdout; the human report is sectioned; errors go to stderr with `⛔` and rc 1; an empty/missing archive degrades to an explicit "no data" report rather than a traceback. An optional `--since <date>` window (on `settled_at`) supports delta reads by the evolve loop. Skills-lint needs zero changes (it derives from `SUBCOMMANDS` + `build_parser()`), but the dispatcher row and the parser must land no later than any skill markdown that invokes the command.
- **R-5**: **`aet-evolve` consumes the metrics** — the skill's flow gains `aet metrics` as a first-class evidence source next to `.agents/learnings.jsonl` and `aet mine-learnings`: the Prerequisites dispatcher list (`skills/aet-evolve/SKILL.md`), numbered invocation steps in the relevant procedure(s) mirroring the `mine-learnings` style, and any flag detail in `aet-evolve/references/`. An evolve cycle that proposes a skill or workflow edit cites the current metric values as evidence (e.g., first-pass rate, rework, and cost per class), making the loop self-improving on numbers rather than self-documenting on prose (doc 04 challenge 7; doc 06 potential 2's eval pairing remains 7b scope).
- **R-6**: **Tests** cover: the routing-aware first-pass definition including routed-away-gate cases and desk/metrics agreement on the same fixtures (R-1); rework counting for repeated-stage, re-entry, and clean single-pass tasks (R-2); cross-run cost accumulation including all-null-`usd` and mixed-null archives with correct coverage counts (R-3); the CLI surface — `--json` projection shape, human report, empty-archive degradation, `--since` filtering (R-4); and an integration test over synthetic settled-history + telemetry fixtures exercising all three metrics end to end. Conventions per `tests/` (conftest archive isolation, `SourceFileLoader` for extensionless bins, temp git repos).
- **R-7**: The **exit gate is demonstrated, not asserted** — one recorded `aet-evolve` cycle (per that skill's own `docs/retros/` convention) that reads `aet metrics` output from this repo's real ledger/telemetry, cites the values obtained, and routes at least one finding (or records explicitly that none was warranted, with the numbers as the evidence). Deliberately a weak gate per the roadmap; the strong gate stays with 7b.

## User Stories

- As the owner at the weekly retro, I want to ask "are we actually getting better?" and get numbers — first-pass merge rate, rework, and cost per merged task, overall and per work class — instead of re-reading anecdotes, so that trust in the night shift is earned on evidence (satisfies: R-1, R-2, R-3, R-4).
- As the `aet-evolve` cycle, I want the current metric values in my input diet, so a proposed skill or workflow edit cites "first-pass rate is X%, rework Y, cost Z per merged task" as its justification rather than a single war story (satisfies: R-5, R-7).
- As the Phase 7b implementer building the scoreboard and arming zero-review, I want the canonical first-pass/rework/cost definitions already in one shared lib location, so the ablation table and the arming decision read the same numbers the desk and CLI report (satisfies: R-1, R-2, R-3).
- As the owner glancing at `aet desk --eligibility`, I want its clean-merge counts to be the same numbers `aet metrics` reports, because two surfaces disagreeing about "clean" is the reality gap this program exists to kill (satisfies: R-1).

## Acceptance Criteria

- [ ] A settled task whose plan routed a gate to `skipped`, with all *required* verdicts passing and no rework signals, is counted first-pass-clean by the shared definition; a task with a failed required verdict, a repeated stage, or a `failed → in_progress` re-entry is not (satisfies: R-1).
- [ ] `aet desk --eligibility` and `aet metrics` report the same clean-merge count for the same work class over the same fixture set (satisfies: R-1).
- [ ] A task with two `implement` stage records counts rework ≥ 1; a task re-entering from `failed` counts a re-entry; a clean single-pass task counts 0; totals aggregate per work class (satisfies: R-2).
- [ ] Cost for a task whose stages span two runs sums records from both runs; an all-null-`usd` task reports tokens with `usd: null`; aggregate output states how many tasks contribute a known `usd` (satisfies: R-3).
- [ ] `aet metrics` prints the human report and `aet metrics --json` prints the projection (three metrics, overall + per class) with rc 0; against an empty archive it prints an explicit no-data report instead of a traceback; `--since` restricts the window; `make validate` (skills-lint) stays green with the new command documented in skill markdown (satisfies: R-4).
- [ ] `aet-evolve`'s SKILL.md and references invoke only commands present in the real argparse tree, and its documented retro/evolve procedure includes reading `aet metrics` as an evidence step (satisfies: R-5).
- [ ] The R-6 test suite passes, including the integration fixture covering all three metrics (satisfies: R-6).
- [ ] One `aet-evolve` cycle is recorded in `docs/retros/` citing actual `aet metrics` output from this repo and routing its finding(s) (satisfies: R-7).

## Technical Notes

**Current reality (grounded 2026-07-19 at `5163272`).** "The ledger" is three read sources: the git-refs store (`refs/aet/*`, live queue), the settled-history JSONL (`.agents/work-history.jsonl`, sealed task records with `cost{tokens,usd}`, `merged_at`, `history[]` transitions, `failure_signatures`), and the telemetry archive (`~/.aet/telemetry/{slug}/{date}/{run-id}/*.jsonl`: `stage`, `test_run`, `run_summary`, `environment_issue`, `learning_candidate` records — schema in `aet-work/references/telemetry-log-schema.md`, null contract: unmeasured stays `null`). Gate verdicts live in the evidence store (`~/.aet/reports/{slug}/{task}/{kind}.json`, one file per kind, overwritten each cycle — so retroactive first-pass computation relies on telemetry + history for *past* failures and reads verdicts only for the final, merged state, which is exactly what `is_clean_merge` already does). Existing computation to build on: `src/aet/track_record.py` (`is_clean_merge`, `count_clean_merges`, `class_eligibility`, `iter_telemetry_task_records`); `aet desk --eligibility` is today the only cross-store aggregation surface. Dispatcher contract: one `SUBCOMMANDS` row + a bin exposing `build_parser()`/`main()`; nested verbs are parsed by the target binary's own argparse, and skills-lint derives everything dynamically (`scripts/skills-lint`). `aet report` exists but is run-centric and text-only — a separate `metrics` noun keeps its scope clean and gives 7b's scoreboard a natural sibling surface.

**Final plan decomposition (prefix `tll`, "telemetry + learning loop"; finalized at `create-stories` 2026-07-19).** Four atomic plans — the dual-limit guardrail split the anticipated two into four; each is session-sized and they ship in one strict chain:

- `tll-01-first-pass-rework-definitions` — canonical routing-aware first-pass (`plan_parser.required_verdict_kinds` + `track_record.is_clean_merge`), `rework_count` with shared counting core, desk unified to the shared rule (R-1, R-2, R-6). M.
- `tll-02-metrics-aggregation-core` — new `aet-work/lib/metrics.py`: window filter, cross-run null-honest cost, `aggregate()` projection with data-driven class buckets (R-3, R-6). M. Blocked by tll-01.
- `tll-03-metrics-cli-surface` — `aet-work/bin/metrics` + dispatcher row, human/`--json`/`--since`, no-data degradation, telemetry-guide docs (R-4, R-6). M. Blocked by tll-02 (and required before any skill markdown invokes the command, per skills-lint ordering).
- `tll-04-evolve-metrics-learning-loop` — `aet-evolve` consumes `aet metrics` (SKILL.md + references), then the recorded cycle on real numbers = the phase exit gate (R-5, R-7). S. Blocked by tll-03.

**Architecture decisions.** One candidate ADR at scope-validation (next free number: **ADR-035** — "Canonical factory-metric definitions"): records the first-pass/rework/cost contracts, the routing-aware verdict rule, the retroactive-derivation choice (no persisted flag), and the reaffirmed analytics-only boundary. CONTEXT.md glossary additions at scope-validation: *first-pass merge*, *rework*, *cost per merged task*.

**Intake triage (recorded per protocol):** classified **feature/enhancement**, not a reproducible defect — this is roadmap Phase 7a new capability; no unexpected behavior in existing code was demonstrated.

## Resolved Decisions (scope-validation, 2026-07-19)

The three open questions are resolved and folded into the plans and ADR-035 (`docs/adr/035-canonical-factory-metric-definitions.md`):

1. **Retroactive derivation, no persisted flag.** First-pass is derived at query time from settled history + telemetry + evidence. A `first_pass` stamp would be a new write path, useless for already-settled tasks, and redundant — past failures are visible in telemetry/history even though the evidence store overwrites old verdicts. Revisit only if 7b's scoreboard shows a query-cost or audit need. (ADR-035 item 5)
2. **`--since <YYYY-MM-DD>` on `settled_at`.** Date window, because the evolve loop's question is "what changed since the last retro"; task-count windows drift with queue throughput. Legacy records without `settled_at` fall back to `completed_at`, then `merged_at`. Fixed in tll-02/tll-03.
3. **Placement: `plan_parser` owns the routing rule, `track_record` the predicate and counters, `metrics` the aggregation.** `required_verdict_kinds` joins `ROUTING_GATE_KEYS` in `src/aet/plan_parser.py` (the routing contract's home); `is_clean_merge` and `rework_count` stay in `src/aet/track_record.py` (the clean-merge home); cross-task aggregation is the new `src/aet/metrics.py`. One import direction, no cycles, desk and CLI share everything. (ADR-035 item 1)

**Scope-validation findings, recorded:**

- **Definition collision found and resolved** — `track_record.REQUIRED_VERDICT_KINDS` (all four) vs. the desk's routing-aware `_required_verdicts`: two live definitions of "clean merge." Resolved by lifting the routing rule into `plan_parser` and deleting the desk's copy (tll-01); `class_eligibility` becomes routing-aware transitively. ADR-035 refines ADR-028's clean-merge definition accordingly.
- **ADR-034 consistency check (pass)** — metrics read `.agents/work-history.jsonl` strictly for *reporting*, the use ADR-034 sanctions; no scheduling or closure decision derives from it.
- **Terminology** — *first-pass merge*, *rework*, and *cost per merged task* added to the CONTEXT.md glossary (new "Factory Metrics (ADR-035)" section), with *cost per merged task* explicitly distinguished from the ledger's settling-run **Per-Task Cost** field.
- **UI Coverage Lens: not applicable** — CLI-only phase, no user-facing interface (same basis as Phase 5).
- **Pipeline fields** — tll-01/02/03 `standard`, tll-04 `minimal` (docs-only + recorded procedure; not high-risk). All values valid.
- **Decomposition finalized at four plans** (guardrail split from the anticipated two): tll-01 → tll-02 → tll-03 → tll-04, one strict chain.

## Divergence Summary

*Recorded: 2026-07-19 — Branch: tll-01-first-pass-rework-definitions*

### Changed from plan

- `Validation Steps` → merge verification: the plan listed `git merge-base --is-ancestor HEAD origin/main`, which would only be true after the branch is already merged. The actual verification used `git merge-base --is-ancestor origin/main HEAD` to confirm the branch is cleanly based on `origin/main`. No code changed; only the documented command operand order was corrected.

---

*Stage: synced*
*Next step: run `aet-ship`*
