---
name: aet-validate-scope
description: Validate a plan or PRD against the existing domain model, terminology, and documented decisions. Use when the user wants to stress-test a plan against CONTEXT.md, resolve terminology conflicts, check for code contradictions, or update ADRs during a planning session. Triggers on requests like "does this plan make sense with our domain model," "check this against our glossary," or "validate this scope."
---

# aet-validate-scope

Post-PRD validation for agentic engineering. Before implementation begins, ensure the plan aligns with the project's existing domain language, documented decisions, and actual code. Surface contradictions early, when they are still cheap to fix.

## When to Use

- A PRD or plan.md exists and the user wants to validate it before implementation
- The user describes a feature using terms that may conflict with the existing glossary
- The user wants to update CONTEXT.md or create ADRs during a planning discussion
- The agent notices a contradiction between the plan and existing code or docs
- Before `aet-implement` starts — as a final alignment gate

## Planning Lockout

This skill is **validation-only**. No application source code is written, modified, or deleted.

- Do not create, edit, or delete application source files
- Do not run application tests, linting, or type-checking
- Do not implement "quick fixes" found during validation

If validation reveals that code changes are needed, stop and redirect to `aet-plan` or aet-work.

## Context

Run `aet context` and parse its JSON for session context (branch, repo
state, AGENTS.md, learnings, active plan/PRD stage); print the stage
banner it emits. Do not ask the user for this context manually.

- `CONTEXT_MD` — presence and last-modified date of CONTEXT.md (or CONTEXT-MAP.md)
- `DOCS_ADR` — presence of docs/adr/ and count of ADRs

## Commands

### `validate`

Check the current plan/PRD against existing documentation and code. Surface contradictions, fuzzy language, and terminology conflicts.

**Procedure:**

1. Read the plan/PRD the user wants to validate
2. Read CONTEXT.md (or CONTEXT-MAP.md + relevant context files)
3. Read ADRs in docs/adr/ that relate to the plan's scope
4. Explore relevant code to cross-check stated behavior
5. Identify conflicts:
   - Terms in the plan that conflict with CONTEXT.md glossary
   - Vague or overloaded language that should be sharpened
   - Stated behavior that contradicts existing code
   - Architectural decisions that contradict existing ADRs
6. **Pipeline field validation** — if a plan frontmatter contains `pipeline`, verify the value is one of `minimal`, `standard`, or `full`. Any other value is a validation failure. Warn if a high-risk change (auth, data models, API, dependencies) uses `minimal`.
7. **Closure Check** — before declaring scope validated, verify the handoff artifact exists:
   - At least one `docs/plans/*.md` file references the PRD (via Context or frontmatter).
   - If the check fails, stop and redirect: do not update the PRD footer to `scope-validated`.
   - Do **not** check the queue here. Queue intake happens after this skill runs via `aet sprint add`; plans may be untracked at intake.
8. Present findings as a concise list (not a 20-question interview)
9. Ask **targeted questions** about the gaps found — one at a time

**Rules:**

- Focus on conflicts and gaps, not generic discovery
- One question at a time, but only about real problems found
- Anti-sycophancy: never say "that's an interesting approach." Always take a position.
- If a question can be answered by exploring the codebase, explore the codebase instead

**Example questions:**

- "Your glossary defines 'cancellation' as X, but this plan seems to mean Y — which is it?"
- "You say 'account' here — do you mean Customer or User? Those are different things per CONTEXT.md."
- "Your code cancels entire Orders, but this plan says partial cancellation is possible — which is right?"

### UI Coverage Lens (conditional)

If the plan or PRD describes any user-facing interface, apply the UI Coverage Lens as part of `validate`.

1. Check whether the plan explicitly marks the feature as "no UI" (API-only, CLI-only, pure backend). If so, skip this lens.
2. Follow the procedure in [references/ui-coverage-lens.md](references/ui-coverage-lens.md)
3. For each of the seven categories (Accessibility, Responsive Design, Component Library Alignment, Form Validation & Error States, Motion & Animation, Information Architecture / Navigation, Content Strategy), rate `PASS`, `FAIL`, or `UNKNOWN` and assign severity `blocking` or `warning`
4. Present findings as a concise per-category list with specific quotes from the source document
5. **Gate:** If any category is rated `blocking`, stop validation and surface the gaps. Do not advance the stage until blocking gaps are addressed or explicitly accepted.

### `update-context`

Update CONTEXT.md with resolved terms and relationships.

**Procedure:**

1. After terms are resolved during validation, update CONTEXT.md immediately
2. Don't batch these — capture them as they happen
3. Use the format in [references/CONTEXT-FORMAT.md](references/CONTEXT-FORMAT.md)
4. Only include terms that are meaningful to domain experts
5. Don't couple CONTEXT.md to implementation details

**Lazy creation:**

- If no CONTEXT.md exists, create one at the repo root when the first term is resolved
- If no docs/adr/ exists, create it when the first ADR is needed

### `propose-adr`

Offer to create an ADR when a decision meets all three criteria.

**Procedure:**

1. When a significant decision emerges during validation, check the three criteria:
   - **Hard to reverse** — the cost of changing your mind later is meaningful
   - **Surprising without context** — a future reader will wonder "why did they do it this way?"
   - **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons
2. If all three are true, propose creating an ADR
3. Use the format in [references/ADR-FORMAT.md](references/ADR-FORMAT.md)
4. Number sequentially by scanning docs/adr/ for the highest existing number

**Skip the ADR if any criterion is missing.** Not every decision needs a document.

## Domain Awareness

### File structure

Most repos have a single context:

```
/
├── CONTEXT.md
├── docs/
│   └── adr/
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
└── src/
```

If a `CONTEXT-MAP.md` exists at the root, the repo has multiple contexts. The map points to where each one lives:

```
/
├── CONTEXT-MAP.md
├── docs/
│   └── adr/                          ← system-wide decisions
├── src/
│   ├── ordering/
│   │   ├── CONTEXT.md
│   │   └── docs/adr/                 ← context-specific decisions
│   └── billing/
│       ├── CONTEXT.md
│       └── docs/adr/
```

Infer which structure applies:

- If `CONTEXT-MAP.md` exists, read it to find contexts
- If only a root `CONTEXT.md` exists, single context
- If neither exists, create a root `CONTEXT.md` lazily when the first term is resolved

When multiple contexts exist, infer which one the current topic relates to. If unclear, ask.

## Closure Check Failure Messages

If the closure check fails, print the following and stop:

- **No plan files:**
  > "Scope validation cannot complete: no plan files reference this PRD. Break the PRD into `docs/plans/*.md` files (e.g., via `aet-plan`), then re-run `aet-validate-scope`."

## Completion Protocol

After `validate` completes, conflicts are resolved, and the closure check passes:

1. Update the PRD file footer to:

   ```
   *Stage: scope-validated*
   *Next step: run `aet-work` (single-plan or multi-task queue)*
   ```

2. Do not touch the plan.md footer. Plan files are transient working copies
   (gitignored); the task's stage is recorded on the queue/ledger by code.

3. Print: `"✓ Stage: scope-validated / plan-approved → Next step: run \`aet-work\`"`

## Key Principles

- **Validate, don't discover** — this skill checks alignment with existing docs, it does not gather new requirements
- **Targeted questions only** — ask about conflicts found, not generic exploration
- **Update docs inline** — capture resolved terms and decisions as they happen, not in a batch at the end
- **ADRs are sparing** — only document decisions that are hard to reverse, surprising, and the result of real trade-offs
- **Code is the ground truth** — when docs and code disagree, surface it immediately
