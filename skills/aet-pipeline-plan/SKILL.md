---
name: aet-pipeline-plan
description: End-to-end planning pipeline. Takes a validated idea and runs it through aet-plan → aet-validate-scope in sequence. Stops at human gates. Produces a scope-validated PRD and plan files ready for implementation. Triggers on requests like "pipeline plan this," "run the full planning flow," or "plan and validate this feature."
---

# aet-pipeline-plan

Planning pipeline for agentic engineering. One entry point — from validated idea to scope-validated, implementation-ready plan. Chains `aet-plan` and `aet-validate-scope` in order with hard human gates between them. UI/UX coverage validation is included as a conditional lens within `aet-validate-scope`.

## When to Use

- You have a validated idea and want to run the full planning sequence without manually invoking each skill
- You want to ensure no planning step is skipped
- When you want to go from concept → validated PRD → approved plans in a single session

## What This Skill Does NOT Do

This skill produces **plans and PRDs only**. It never writes, modifies, or deletes application source code.

- Do not create, edit, or delete application source files
- Do not run application tests, linting, or type-checking
- Do not create branches or commits for implementation work
- Do not generate "quick proofs of concept" or spike code

If the user describes a change imperatively ("remove X", "adapt Y", "change Z to W"), treat it as a **planning target**, not a command to execute immediately.

## Context

Run `aet context` and parse its JSON for session context (branch, repo
state, AGENTS.md, learnings, active plan/PRD stage); print the stage
banner it emits. Do not ask the user for this context manually.

- `EXISTING_BRIEFS` — any `docs/product-briefs/*.md` (list titles + dates) — context only; discover is not run
- `EXISTING_PRDS` — any `docs/prds/*.md` (list titles + dates)

## Intake Triage

Before planning, confirm this is a **feature or enhancement**, not a **reproducible defect** in existing code.

**Question:** Can you demonstrate unexpected behavior in existing code?

- **Yes** → This is a bug. Stop and redirect to `aet-bug-report`:
  _"This appears to be a reproducible defect in existing code. Use `aet-bug-report` for structured investigation and targeted fixes."_
- **No** → Continue with the planning pipeline

## Resuming from a Stage

If `ACTIVE_PRD_STAGE` or `ACTIVE_PLAN_STAGE` is found, skip already-completed steps:

| Stage found                          | Resume from                          |
| ------------------------------------ | ------------------------------------ |
| `prd-approved` or `prd-draft`        | Step 2 (aet-validate-scope)          |
| `scope-validated` or `plan-approved` | Pipeline complete → suggest aet-work |

## Commands

### `plan`

Run the full planning sequence from validated idea to scope-validated plan.

**Sequence:**

```
Step 1: aet-plan
    ↓ [HARD GATE: user approves PRD]
Step 2: aet-validate-scope
    ↓ [OUTPUT: scope-validated PRD + plan-approved plans]
```

**Procedure:**

**Step 0 — Planning Lockout:**

Print the planning lockout banner:

```
🔒 PLANNING MODE ACTIVE
This session produces PRDs and plans only. No code changes.
```

If the user's request contains implementation directives (e.g., "make", "change", "adapt", "remove", "refactor", "fix", "update", "implement", "build"), explicitly restate the goal in planning terms before proceeding.

**Step 1 — aet-plan:**

1. Follow the `aet-plan` → `clarify-goal` + `create-prd` + `create-stories` + `plan` procedures
   - `create-stories` and `plan` enforce task size guardrails automatically (2-of-N signal model, context-budget + coherence, auto-split, `⚠️ ATOMIC OVERSIZED` marking). See `docs/CONVENTIONS.md` for the current model; size is measured after implementation, not gated at intake (ADR-046).
   - R-trace discipline (numbered R-ids carried brief → PRD → plan task, with a coverage lint) is enforced by `aet-plan` here and demonstrated at the P0 exit gate, ahead of Phase 4's mechanized <!-- aet-lint: off -->`aet plan validate`<!-- aet-lint: on -->
2. Produce: `docs/prds/{feature}-prd.md`, `docs/plans/*.md` files
3. **Queue preservation guardrail:** When plans are admitted to the sprint, new tickets must be merged into the existing queue rather than replacing it. Existing tasks must survive the planning session unchanged.
4. **HARD GATE:** Present PRD to user for review. Ask:

   ```
   "The PRD is ready. Please review docs/prds/{feature}-prd.md.
   Approve to continue or request changes."
   ```

   Do NOT proceed until the user explicitly responds.

   - If the user approves → proceed to Step 2
   - If the user requests changes → stop and return to Step 1

**Step 2 — aet-validate-scope:**

1. Follow the `aet-validate-scope` → `validate` command procedure
2. Surface conflicts, fuzzy language, code contradictions
3. Apply the UI Coverage Lens if the PRD describes user-facing interfaces
4. Update CONTEXT.md and propose ADRs as needed
5. The stage transition is recorded on the task record by code; do not edit
   plan footers — plan files are transient working copies (gitignored)

**Step 3 — aet sprint add + sync:**

1. Run `aet sprint add <plan-file>` for each newly created atomic `docs/plans/*.md` file to add it to the sprint. `aet sprint add` accepts untracked plans; it does not set a `status` key in frontmatter, and it does not commit or push at intake. Plan durability is deferred to terminal closure (`merged`/`abandoned`). Only explicitly added plans enter the queue; non-atomic documents stored in `docs/roadmaps/` or `docs/audits/` are ignored.
2. Run `aet queue sync` to reconcile existing queue entries, recompute reverse `blocks` edges, and report plan drift. Sync never auto-adds new plans.
3. Preserve all existing queue entries and their states
4. Run `aet status` and verify:
   - No plan drift is reported.
   - At least one newly created task appears in the queue summary.
5. If drift, orphaned entries, or missing tasks are surfaced, resolve them before declaring the pipeline complete

**Output:**

- `docs/prds/{feature}-prd.md` — stage: `scope-validated`
- `docs/plans/*.md` — stage: `plan-approved`
- Task records — curated via `aet sprint add` and reconciled via `aet queue sync`, ready for aet-work

## Completion Protocol

After the pipeline completes all steps:

1. Confirm the intake triage guard was applied (bug vs. feature) and documented in the PRD or plan notes.
2. Print:

   ```
   ✓ Planning pipeline complete.

   Artifacts:
   - PRD:       docs/prds/{feature}-prd.md (scope-validated)
   - Plans:     docs/plans/*.md (plan-approved)
   - Queue:     Sprint board (sync verified, no drift)

   Next step:
   - Single task: run `aet run-one {ticket-id}`
   - All tasks (AFK): run `aet run`
   ```

## Key Principles

- **Hard gates are non-negotiable** — the pipeline stops at PRD review and scope validation; never auto-advance
- **Resumable** — if a stage is found in the footer, skip completed steps
- **Same quality as individual skills** — the pipeline chains skills, it does not shortcut them
- **AFK-safe** — the only human touchpoints are the defined gates; everything else runs unattended
- **Implementation lockout** — Never edit application source files during planning. If a step would require code changes, stop and redirect to aet-work
- **UI validation is a lens, not a stage** — UI/UX coverage is checked as part of `aet-validate-scope` when the PRD describes user-facing interfaces. It is not a separate pipeline step.
- **Imperative requests are planning targets** — "Do X" means "Plan how to do X"
- **Session-sized output** — The pipeline delegates to `aet-plan`, which shapes plans against the advisory guardrail model in `docs/CONVENTIONS.md`. Plans that enter the queue are intended to be implementable in a single agent session; actual size is measured at closure (ADR-046).
