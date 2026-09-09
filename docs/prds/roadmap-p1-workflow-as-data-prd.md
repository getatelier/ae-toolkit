# PRD: Roadmap Phase 1 — Workflow-as-Data (the Extraction Pilot)

## Overview

Phase 1 of the AET roadmap (`content/fable-review/09-2026-07-10-roadmap.md`): the software pipeline stops being engine code and becomes data. The hardcoded stage table in `aet-work/lib/pipeline.py` is extracted into a versioned workflow file; the two runtime lambdas — the last judgment embedded in the engine — dissolve into plan-frontmatter routing decided at triage; session grouping and harness/model routing become separate config axes in the same file; and a CI lint makes a malformed workflow file unmergeable. Brief: `docs/product-briefs/roadmap-p1-workflow-as-data-brief.md` (R-ids carried from there).

## Goals

- **G1**: The pipeline is defined by data — stage sequence, skill bindings, evidence bindings load from a workflow file; the engine's hardcoded table is deleted (R-1, R-2, R-3, R-7).
- **G2**: Judgment leaves the engine — `security_review` and `docs_sync` are routed once at plan time with recorded reasons, enforced deterministically forever (R-4, R-5, R-6). Implements ADR-020's route-once principle.
- **G3**: The config axes exist before their consumers — `execution_policy` and `routing` are parsed, validated, and stored while only Claude is conformant, so Phase 6 plugs adapters into config that already exists (R-2, R-8).
- **G4**: The flexibility is guarded and proven — workflow lint in `make validate`; parity and team-variant tests demonstrate the exit gate (R-9, R-10, R-11).

## Non-Goals

- No `aet` multicall binary (Phase 2); no gate-submit CLI, hooks, or git-refs default flip (Phase 3); no adapters or routing dispatch (Phase 6); no second workflow class shipped (Phase 8 trigger — the variant is a test fixture only).
- No new evidence kinds: workflow files bind the fixed menu (`qa`/`review`/`cso`/`sync-docs`). New kinds require kernel schemas, deliberately outside data's reach.
- Standing fences hold: no runtime condition DSLs, no DAGs, no per-workflow state vocabularies, no plugin verifiers. Lifecycle states and `LEGAL_TRANSITIONS` stay frozen code.
- No retrofit of already-queued plans.

## Requirements

_Carried verbatim from the brief — the second brief→PRD→plan demonstration of the R-trace discipline (P0 exit gate)._

- **R-1**: A versioned JSON workflow schema and a packaged default `aet-work/workflows/software.json` describe the current software pipeline completely: an ordered, linear stage sequence with per-stage skill bindings and evidence bindings (from the fixed verdict menu), entry stage and terminal succession explicit in the data.
- **R-2**: Session grouping lives in a separate `execution_policy` axis of the workflow file, not on stages; `minimal` / `standard` / `full` isolation semantics are preserved exactly. Unknown extension keys are tolerated (room reserved for context-fidelity settings).
- **R-3**: The engine loads the pipeline exclusively from workflow data. Resolution order: repo-level `.agents/workflows/<name>.json`, else the packaged default; the plan frontmatter key `workflow:` selects the workflow by name (default `software`). The hardcoded `STAGES` table and the `Stage.conditional` field are deleted.
- **R-4**: Plan frontmatter gains `security_review: required|skipped` and `docs_sync: required|skipped`; a `skipped` value requires a recorded reason (`security_review_reason` / `docs_sync_reason`); intake validation enforces this contract for newly added plans only (already-queued plans are grandfathered).
- **R-5**: The orchestrator resolves stage skips from plan frontmatter only; `_security_sensitive` and `_divergences_found` are deleted; a missing key is treated as `required` — fail-safe is running the stage.
- **R-6**: `aet-plan` prose instructs triage to set both routing keys deliberately on every new plan, with the reason recorded in the plan.
- **R-7**: Every engine consumer of stage vocabulary reads the loaded workflow: orchestrator entry stage and stage-membership checks, session grouping, and per-stage verdict kinds (retiring the skill→verdict map); `bin/review`'s board projection tolerates arbitrary stage vocabularies.
- **R-8**: A `routing` section (`default` / `by_stage` → harness + model; the per-workflow `default` is the by-class axis, since routing lives inside each workflow file) is schema-validated, parsed, and exposed on the loaded workflow object; no dispatch behavior changes while only Claude is conformant.
- **R-9**: A workflow lint runs inside `make validate` and fails on: invalid JSON or schema, duplicate or unknown stage references, skill bindings that resolve to no skill directory, evidence kinds absent from the fixed verdict menu, malformed execution-policy or routing sections.
- **R-10**: Parity is proven by tests: the loaded packaged default reproduces today's stage sequence, session groups, and verdict kinds exactly, and a full task lifecycle runs from pure data (stub adapter) with the same traversal as today.
- **R-11**: The team-variant test passes: a second workflow file — different stages, different gates, different evidence bindings, different routing — drives grouping and traversal through the engine with **zero engine changes**.

## User Stories

- As the owner, I change my own gates — add a stage, rebind a skill, reorder checks — by editing a data file, never engine code (R-1, R-3, R-11); the team-variant test is the proof.
- As a planning agent at triage, I decide security-review and docs-sync routing per task with a recorded reason, and the engine enforces my decision deterministically at runtime (R-4, R-5, R-6).
- As a reviewer, I trust that a malformed workflow file cannot reach main because `make validate` fails on it (R-9).
- As the Phase 6 implementer, I find `routing` already parsed, validated, and stored, so adapters plug into config that exists rather than inventing it (R-8).

## Acceptance Criteria

- [ ] `aet-work run` / `run-one` traverses stages loaded from `aet-work/workflows/software.json`; `pipeline.py`'s `STAGES` literal no longer exists anywhere in the engine (R-1, R-3, R-7).
- [ ] A plan with `security_review: skipped` + reason skips the security stage; the same plan without the key runs it; `_security_sensitive` and `_divergences_found` are gone from the codebase (R-4, R-5).
- [ ] A plan entering the queue with `security_review: skipped` and no reason is rejected at intake; `rdm-01`/`rdm-02` (already queued, no keys) run unmodified under the fail-safe default (R-4, R-5).
- [ ] `make validate` goes red when a workflow file names an unknown stage, an unresolvable skill, or an unknown evidence kind (R-9).
- [ ] Tests prove sequence/group/verdict-kind parity with today's table and a full stub-adapter lifecycle from pure data (R-10).
- [ ] A fixture variant workflow — different stages, gates, evidence, routing — passes loader, grouping, and traversal tests with zero engine edits (R-11) — the roadmap's team-variant exit gate.

<!-- aet-lint: off -->
- **Current couplings (planning-time ground truth, `a6efe17`)**: `STAGES`/`STAGE_MAP` and the two lambdas in `aet-work/lib/pipeline.py:24-63`; sole importer is `aet-work/bin/orchestrator:41` (membership check :566, grouping :578, conditional checks :601-604 and :696-699, skill→verdict map `CHECKING_SKILL_TO_VERDICT` :307, entry-stage literal `"plan-approved"` :150 and :1450); board-column map in `aet-work/bin/review:22-30`. `aet-state set-stage` is stage-vocabulary-agnostic — no change needed (states stay frozen; stages generalize).
<!-- aet-lint: on -->
- **Schema sketch (locked by wfd-02)**: `{"version": 1, "name": "software", "done_state": "done", "stages": [{"name", "skills": [], "evidence": <kind|null>, "gate_key": <str|null>}...], "execution_policy": {"session_groups": [[...], ...]}, "routing": {"default": {"harness": "claude", "model": null}, "by_stage": {}}}`. Succession is list order (linear only, per P3); the last stage advances to `done_state`. `gate_key` names the plan-frontmatter key that can skip the stage — pure data, replacing `conditional`.
- **Terminology (scope validation)**: the schema field is `name`, never `class` — `docs/PIPELINE.md` reserves "work class" for the Trivial/Normal/Critical intake tiers, a different axis from workflow names. Plan frontmatter: `workflow:` selects _which_ stage sequence; the existing `pipeline:` key selects _how_ its sessions are batched (isolation). Routing has no `by_class` sub-key — the per-workflow `default` is that axis.
- **Interim step (wfd-01)**: `Stage.conditional` is first replaced by the serializable `gate_key` field while the table still exists — dissolving judgment before extraction, so wfd-02/03 serialize only data.
- **Loader**: `aet-work/lib/workflow.py`, stdlib-only, frozen dataclasses, strict validation (`WorkflowError`). Resolution: `<repo>/.agents/workflows/<class>.json` → packaged `aet-work/workflows/<class>.json`. `pipeline.py` is deleted in wfd-03; its API is absorbed by `workflow.py` (orchestrator loads once per run and threads the object).
- **Intake grandfathering**: `intake_validation_errors` already supports `limit_to` — the new key checks apply only to newly added plans.
- **Testing**: `tests/test_workflow.py` (loader + parity constants), rewritten orchestrator coverage in `tests/test_orchestrator.py` (existing `patch.object(run_stage…)` machinery), `tests/test_workflow_lint.py`, `tests/test_workflow_variant.py`. `tests/test_pipeline.py` retires with the module it tests.
- **CI**: this repo's CI is `make validate`; the lint lands there (plus standalone `aet-work/bin/validate-workflows`).
- Intake triage: enhancement — no reproducible defect involved; classification recorded here.
- Sizing: 4 plans (`wfd-01…04`) matching the roadmap's ~4-task estimate; `wfd-01`/`wfd-02` are parallel-safe entry tasks, both blocked on the rdm pair to enforce phase ordering in a single overnight batch.

## Open Questions

None blocking. Flagged choices for owner review at this gate:

1. **Packaged default with per-repo override** (vs. requiring `.agents/workflows/` in every repo) — zero-migration; rejected alternative recorded in the brief.
2. **Missing routing keys default to `required`** — fail-safe runs the stage; means already-queued docs-only plans (rdm-01) will run one security-review session today's heuristic would have skipped. Deliberate, documented deviation inside "behavioral parity."
3. **Phase ordering via queue edges** — wfd-01/wfd-02 are `blocked_by` rdm-01 + rdm-02, so P0 → P1 ordering is enforced by the queue itself in one batch.
4. The four wfd plans carry the new `security_review`/`docs_sync` keys themselves (all `required`, reasons noted) — dogfooding the discipline the moment wfd-01 makes it live.

---

_Stage: scope-validated_
_Validated: 2026-07-11_
_Next step: run `aet-work` (single-plan or multi-task queue)_
