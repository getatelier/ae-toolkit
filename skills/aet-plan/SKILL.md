---
name: aet-plan
description: PRD creation, goal clarification, story breakdown, plan.md generation, and optional issue tracker publishing. Use when starting a new feature, sprint, or project. Prevents misalignment by building shared understanding before any code is written. Triggers on requests like "design this feature," "create a PRD," "break this into tickets," or "publish these to GitHub issues."
---

# aet-plan

Planning and alignment for agentic engineering. The #1 failure mode is starting implementation before shared understanding exists. This skill prevents that.

## When to Use

- Starting a new feature, sprint, or project
- You have an idea but no structured plan yet
- The agent built something different from what you imagined (go back to clarify-goal)
- Breaking a PRD into implementable tickets

## Context

Run `aet context` and parse its JSON for session context (branch, repo
state, AGENTS.md, learnings, active plan/PRD stage); print the stage
banner it emits. Do not ask the user for this context manually.

## Intake Triage

Before planning, confirm this is a **feature or enhancement**, not a **reproducible defect** in existing code.

**Question:** Can you demonstrate unexpected behavior in existing code?

- **Yes** → This is a bug. Stop and redirect to `aet-bug-report`:
  _"This appears to be a reproducible defect in existing code. Use `aet-bug-report` for structured investigation and targeted fixes."_
- **No** → Continue with planning

## Planning Lockout

This skill is **planning-only**. No application source code is written, modified, or deleted.

- `clarify-goal`: Research and codebase exploration are allowed; file edits are forbidden
- `create-prd`: Produce documents only; do not generate source code, migrations, or config
- `create-stories`: Do not implement "quick spikes" or proofs of concept
- `plan`: Architecture notes and pseudocode are allowed; production code is forbidden

If the user states a goal imperatively ("I want X removed"), treat it as a planning target.

## Task Size Guardrails

Every task produced by this skill must fit within a single agent coding session. Oversized tasks cause context bloat, quality degradation, and abandoned sessions. Enforce the context-budget + coherence model at both the story and task level.

### Guardrail Model

A plan/task is a candidate for splitting when **two or more** of the following signals are true. One tripped signal is a prompt to justify the shape in writing, not an order to split. Plan size is measured after implementation, not gated at intake; see ADR-046.

1. **Expected diff guidance** (skill-level only, not validator-enforced):
   - Task: > 600 expected diff lines.
   - Story: > 1,200 expected diff lines.
2. **Human-time sanity check** (skill-level guidance, not validator-enforced):
   - Story: > 2 human-days.
   - Task: > 1 human-day.
3. **Subsystem coherence** (skill-level guidance):
   - Touches files in more than 2 distinct implementation subsystems. A _subsystem_ is a bounded module or layer with its own ownership boundary — in this repo, for example: `src/aet/` (CLI code + its tests), `skills/` (skill content), `.agents/` (workflow infrastructure). `docs/` changes and the tests that belong to a code change do not count as additional subsystems; code + its tests are one concern.
   - Requires maintaining more than one major architectural invariant at a time.
4. **Context budget** (skill-level guidance):
   - Loading the plan + all files to modify + relevant tests would exceed ~60k tokens for a task or ~100k tokens for a story.

No plan-time proxy for diff size is enforced at intake. `validate_size()` no longer rejects on task-list length; it only surfaces the `⚠️ ATOMIC OVERSIZED` marker for downstream skills.

### Auto-Split Procedure

When a task exceeds two or more signals from the model:

1. Identify natural vertical-slice boundaries:
   - By user-visible behavior (e.g., "user can register" vs "user can reset password")
   - By data entity (e.g., "user schema" vs "order schema")
   - By layer dependency (e.g., "backend API" before "frontend form")
   - By subsystem boundary (e.g., `src/aet/` changes separate from `skills/` changes)
2. Split the task into independently implementable children.
3. Re-evaluate each child against the full model. Repeat recursively.
4. **Max split depth = 3.** If a child still fails after 3 splits, mark it `⚠️ ATOMIC OVERSIZED` and surface it for explicit user approval.
5. Document parent/child relationships with `Split from: {parent-id}` and suffix IDs (`01a`, `01b`).

### Floor Test

The opposite mistake is also possible: splitting a coherent feature into plans that are each too small to justify their own branch, worktree, and review overhead. Before creating a new plan, confirm it stands alone as an independently shippable, reviewable behaviour change and that its diff materially exceeds the branch/PR/review overhead. If it does not, merge it with a sibling plan. This check is advisory — it prompts a written justification, it does not block at scope validation.

### Size Labels

Use S/M/L labels on every task. A label is an advisory prediction calibrated against measured delivery, not an intake limit.

| Label | Human Time             | Diff Lines           |
| ----- | ---------------------- | -------------------- |
| S     | ≤ 2 hr                 | ≤ 150                |
| M     | ≤ 1 day                | ≤ 600                |
| L     | > 1 day OR > 600 lines | — justify above 1500 |

An L task must be re-evaluated against the full model above and is split only if it actually exceeds a limit.

## Commands

### `clarify-goal`

The agent interviews the human until a shared design concept exists. This is the single highest-leverage step in the entire workflow.

**Procedure:**

1. Ask the user to describe what they want to build (brain dump — no structure required)
2. Ask clarifying questions one at a time. Walk down each branch of the design tree.
3. Use multiple-choice options when possible to speed up answers.
4. Continue until the agent is satisfied that a shared understanding exists. Focus on what matters — stop when the core concept is clear, not after an arbitrary number of questions.
5. Summarize the shared design concept for confirmation.

**Rules:**

- This is NOT plan mode. Do not produce artifacts yet. Build shared context first.
- **No implementation** — Never edit source files during clarification. Research only.
- Anti-sycophancy: never say "that's an interesting approach." Always take a position.
- Be efficient — ask about gaps and ambiguities, not every possible detail.
- The conversation history becomes a valuable asset — save it for reference.

### `create-prd`

Transform the grilled conversation into a structured Product Requirements Document.

**Procedure:**

1. Read the clarify-goal conversation history as input.
2. Use `.agents/templates/prd-template.md` as the structure guide.
3. Create `docs/prds/` if it doesn't exist. Produce a PRD saved to `docs/prds/{feature-name}-prd.md`.
4. Include: executive summary, mission, target users, scope (in/out), a numbered **Requirements** section (R-1…, each independently testable — carried from the brief when one exists, minted here otherwise), user stories with acceptance criteria (each citing the R-ids it satisfies), technical notes, architecture decisions, open questions, risks.
5. **Explicitly list out-of-scope items** — crucial for defining "done."
6. Ask the user to review before proceeding. Do not auto-generate stories from an unreviewed PRD.

### `create-stories`

Break the PRD into vertically-sliced, independently implementable tickets.

**Procedure:**

1. Read the approved PRD from `docs/prds/`.
2. Create `docs/plans/active/` if it doesn't exist. Create tickets as markdown files in `docs/plans/active/` or push via MCP if configured. Atomic task plans MUST be saved to `docs/plans/active/{ticket-id}-plan.md`. Roadmaps, audits, and meta-plans MUST be saved to `docs/roadmaps/` or `docs/audits/` and will NOT be added to the work queue.
3. **Force vertical slices**: each ticket must cross all layers (schema + API + minimal UI), not horizontal layers (all DB → all API → all UI).
4. **Apply task size guardrails**. Evaluate each story against the full guardrail model (≤ 2 days human time; ≤ 1,200 expected diff lines; ≤ 2 implementation subsystems; ~100k-token context budget). Auto-split stories that trip two or more signals recursively (max depth 3). Mark `⚠️ ATOMIC OVERSIZED` if unsplittable.
5. Define blocking relationships between tickets (directed acyclic graph).
6. Each ticket gets: title, user story, acceptance criteria, technical notes, estimated effort, size label (S/M/L), and the R-id(s) it satisfies (cited on each user story and acceptance criterion so coverage is visible at review time).
7. **Plan file frontmatter contract.** Every `docs/plans/active/{ticket-id}-plan.md` must begin with YAML frontmatter:

   ```yaml
   ---
   id: { ticket-id }
   size: S/M/L
   work_class: normal
   blocked_by:
     - { blocker-id }
   pipeline: standard
   security_review: required
   security_review_reason: { one line }
   docs_sync: required
   docs_sync_reason: { one line }
   ---
   ```

   - `id` must match the plan filename stem and must be unique within the PRD.
   - `blocked_by` is a list of blocking task IDs; an empty list means no blockers.
   - `size` is the S/M/L complexity label. `stage` lives only in the task record, never in frontmatter.
   - `pipeline` controls orchestrator isolation. Declare it explicitly in every plan; there is no orchestrator auto-switch. See ADR-047 (`docs/adr/047-pipeline-mode-by-plan-size.md`) for the full rationale.
     - Size-based advisory default:
       - **S** (≤ 2 hr human time / ≤ 100 expected diff lines) → `minimal`
       - **M** (≤ 1 day human time / ≤ 200 expected diff lines) → `standard`
       - **L** (> 1 day OR > 200 expected diff lines) → `standard` or `full`; pick based on risk
     - Risk override: regardless of size, use `standard` or `full` when the change touches authentication/authorization, data models or persisted state, public/internal API contracts, dependencies/frameworks/infrastructure, or security-sensitive surfaces (secrets, trust boundaries, injection paths).
     - `minimal` runs all skilled stages in one session; `standard` uses the default stage groups; `full` uses one session per stage.

8. **Set gate routing keys deliberately.** `security_review`, `docs_sync`, and `verify` route the aet-cso, aet-sync-docs, and aet-verify stages at plan time, so the engine never judges at run time. Default `security_review` and `docs_sync` to `required`. `verify` defaults to `critical-only` derived from `work_class` (runs for `critical` plans, skipped for `normal` and `trivial` without needing a reason). Set `skipped` explicitly only when the gate is unnecessary for the plan, and always pair a skip with a one-line reason (`<key>_reason`) recording why — intake rejects an explicit `skipped` key without its reason, and an omitted key falls back to the stage's default (`required` for CSO/sync-docs, `critical-only` for verify).

9. **Queue handoff.** After all plan files are written, do not add them to the sprint automatically. Plans are the durable source of truth; mid-sprint tasks are stored on the open-work board. `aet sprint add` now accepts untracked `docs/plans/active/*.md` files and queues them without publishing (plan durability is deferred to the PR). Instruct the user to add plans explicitly with `aet sprint add`. Do not write queue files directly from this skill.

**Vertical slice rule:**

- Bad (horizontal): "Create user table" → "Add user API" → "Build user profile page"
- Good (vertical): "User can register" (schema + endpoint + form) → "User can view profile" (query + page)

**Work queue handoff:**

- `aet-plan` produces `docs/plans/active/*.md` only
- Queue management is owned by aet-work. The user curates the sprint with `aet sprint add <plan-file>`; plans may be untracked at intake
- This keeps queue format, merge logic, and state management in a single skill
- See [references/work-queue-format.md](references/work-queue-format.md) for the task record schema

### `publish-issues`

Push locally-created stories to an external issue tracker (GitHub, GitLab, etc.). This is optional — local plan files remain the source of truth for intent and closure.

**Procedure:**

1. Read `docs/plans/active/*.md` and the approved PRD from `docs/prds/`.
2. Determine the target tracker from user input, environment config, or AGENTS.md.
3. For each story, create an issue with:
   - **Title**: short descriptive name
   - **Type**: HITL (requires human interaction) or AFK (can be implemented without human input)
   - **Blocked by**: references to blocking issues (publish blockers first so real IDs exist)
   - **Parent**: reference to the parent issue/PRD if applicable
   - **What to build**: concise description of the vertical slice
   - **Acceptance criteria**: checklist of verifiable behaviors
4. Apply a triage label (e.g., `needs-triage`) so each issue enters the normal triage flow.
5. Do NOT close or modify any parent issue.
6. Update the local plan files with tracker issue IDs for reference.

**Issue template:**

```markdown
## Parent

Reference to the parent issue or PRD (omit if none).

## What to build

A concise description of this vertical slice. Describe the end-to-end behavior, not layer-by-layer implementation.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## Blocked by

- Reference to the blocking ticket (if any)

Or "None — can start immediately" if no blockers.
```

**Rules:**

- Publish in dependency order (blockers first) so real issue IDs can be referenced
- External issues are a mirror; the local work queue remains the source of truth for aet-work
- If the tracker is not configured, skip this step and document the gap in AGENTS.md

### `plan`

From a ticket/story, produce a structured `plan.md` for implementation.

**Procedure:**

1. Read the ticket and relevant PRD section.
2. Use `.agents/templates/plan-template.md` as the structure guide.
3. Create `docs/plans/active/` if it doesn't exist. Produce `docs/plans/active/{ticket-id}-plan.md` containing: (atomic task plans only; save roadmaps, audits, and meta-plans to `docs/roadmaps/` or `docs/audits/`)
   - Summary and user story
   - Locked-in architecture decisions (cannot change without re-planning)
   - Files to create and modify
   - Ordered, granular task list with size labels (S/M/L)
   - Self-validation strategy (lint, type-check, unit tests, e2e)
   - **Never create `docs/plans/plans/` or any nested duplicate directory.** Always write directly to `docs/plans/active/{filename}`.
4. **Validation strategy gate.** The self-validation strategy must list, for each new source file or module introduced by the plan, at least one specifically named test that will cover it. A strategy that only says "add tests" or "write tests for new behavior" without naming what is tested is flagged as incomplete and must be revised before the plan is saved as `plan-draft`.
   - Distinguish test types: **unit tests** (single layer), **integration tests** (cross-layer within backend or frontend), and **API boundary tests** (frontend ↔ backend contract for vertical slices that introduce both sides).
   - _Cross-Cutting Completeness framing:_ When a plan introduces new source files, verify each has a named test in the validation strategy.
5. **Apply task size guardrails** to the task list. Evaluate each task against the full guardrail model (≤ 1 human-day; ≤ 600 expected diff lines; ≤ 2 implementation subsystems; ~60k-token context budget). Auto-split tasks that trip two or more signals into subtasks with explicit dependencies. Mark `⚠️ ATOMIC OVERSIZED` if unsplittable.
6. **Self-consistency lint.** Before saving the plan, run these checks on the produced plan.md. Print the result for each check as `PASS`, `WARN`, or `FAIL`.

   - **Check 1 — Prose constraints in code blocks:** Scan the plan for constraints, requirements, or business rules stated in prose (outside code blocks). Verify each one is represented inside a code block, task list item, or explicit file edit. If a prose constraint has no corresponding code artifact, flag it.
   - **Check 2 — Files assigned to tasks:** Extract every file path from the "Files to create and modify" section. Verify each path appears in at least one task. Unassigned files are a `FAIL`.
   - **Check 3 — Observable acceptance criteria:** For each acceptance criterion, verify it describes an observable user behavior (e.g., "user sees an error message") rather than restating a task (e.g., "add error handling"). Criteria that merely restate tasks are `WARN`; criteria that are unverifiable are `FAIL`.
   - **Check 4 — R-trace coverage:** Collect the R-ids declared in scope (from the PRD/brief Requirements section) and the `(traces: R-n)` citations on the task list. An in-scope R-id with no covering task (and not explicitly deferred with a reason) is a `FAIL`; a task that cites an R-id not present in scope is a `FAIL`.

   **Gate:** Any `FAIL` → stop and print the inconsistency. Do not advance to `plan-draft` until resolved. Any `WARN` → print the warning and continue.

7. Ask the user to review and iterate. This is the last chance to steer before implementation.

**Context discipline:**

- During exploration (before plan is locked), sub-agents may research the codebase or web.
- Sub-agents consume 100k+ tokens but return only concise summaries.
- Once plan.md is produced, the planning conversation context should be cleared.

## Completion Protocol

After the `plan` command completes and the plan.md is ready for review:

1. Ensure the PRD file footer reads:

   ```
   *Stage: prd-approved*
   *Next step: run `aet-validate-scope`*
   ```

2. Plan files do not require a footer. Admission onto the board is governed
   by the operator's invocation (`aet sprint add`) or GitHub label
   (`aet sprint intake`), with validation enforced by the single admission
   operation (ADR-066). Existing footers are treated as breadcrumbs only.

3. Confirm the intake triage guard was applied (bug vs. feature) and document the classification in the PRD or plan notes.
4. The new plan files are ready to queue. Because mid-sprint queue state is local-only, remind the user that untracked plans are load-bearing: `git clean -fdx` or git-following backups will discard in-flight work.
5. Do not run `aet sprint add`, and do not report on whether intake happened. Intake belongs to the operator, or to `aet-pipeline-plan` Step 3 when this skill runs inside that pipeline. This mirrors step 9 of `create-stories`; the two must not diverge.
6. Print: `"✓ Stage: prd-approved / plan-draft → Next step: run \`aet-validate-scope\`, then \`aet-work\`"`

## Key Principles

- **Shared design concept first** — never skip clarify-goal. Misalignment is the #1 cause of wasted work.
- **PRD is the north star** — every session starts by checking "what does the PRD say?"
- **Vertical slices** — AI naturally codes horizontal layers; force vertical slices for immediate feedback.
- **Human reviews every artifact** — PRD, stories, plan. Never chain automatically.
- **Separate planning from implementation** — plan.md must be comprehensive enough to require zero additional context at execution time.
- **Planning lockout** — Never edit application source files during planning. Research and exploration are allowed; code changes are not.
- **Imperative input = planning target** — When the user says "do X," interpret it as "help me plan X."
- **Session-sized tasks only** — Aim each task at one independently shippable unit of behaviour. Split when the model says the plan is overloaded, not by reflex.
- **No nested plan directories** — Never write to `docs/plans/plans/`. The correct path is always `docs/plans/active/{ticket-id}-plan.md`.
