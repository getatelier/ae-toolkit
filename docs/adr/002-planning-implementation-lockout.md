---
subject: planning-implementation-lockout
---

# Planning Implementation Lockout

## Status

Accepted

## Context

Users frequently invoke `aet-plan` or `aet-pipeline-plan` with imperative requests such as "remove the global Timeline page" or "adapt this to work in project scope." Despite explicit skill triggers, the agent drifts into implementation mode — editing source files, running tests, and creating branches — because imperative language strongly activates implementation heuristics in the model.

The existing skills had hard gates between planning phases, but they lacked an explicit behavioral constraint at the session level. The skills described what to do but did not sufficiently describe what **must never** happen during planning.

## Decision

Introduce an **Implementation Lockout** pattern across all planning skills. The lockout has three layers:

1. **Declarative lockout banner** — The first output of any planning skill must be a visible "Planning Mode Active / No code changes" banner. This acts as a self-anchor for the model.

2. **Explicit negative constraints** — Each planning skill now contains a "What This Skill Does NOT Do" (or "Planning Lockout") section that forbids:

   - Creating, editing, or deleting application source files
   - Running application tests, linting, or type-checking
   - Creating branches or commits for implementation work
   - Generating spikes, proofs of concept, or "quick fixes"

3. **Imperative-input reframing** — When the user describes a change imperatively ("make X do Y", "remove Z", "adapt W"), the agent must explicitly restate it as a planning target before proceeding. The rule is: _"Do X" means "Plan how to do X."_

### Skills updated

- `aet-plan` — Added "Planning Lockout" section, "No implementation" rule in `clarify-goal`, and lockout principles in Key Principles
- `aet-pipeline-plan` — Added "What This Skill Does NOT Do" section, "Step 0 — Planning Lockout" in the `plan` command, and lockout principles in Key Principles
- `aet-discover` — Added "Planning Lockout" section reinforcing the existing Hard Gate
- `aet-validate-scope` — Added "Planning Lockout" section preventing validation from drifting into implementation

## Consequences

- Planning sessions now begin with an unambiguous mode declaration
- Imperative user requests are reframed as planning goals, reducing implementation drift
- If a planning step accidentally requires code changes, the skill instructs the agent to stop and redirect to `aet-pipeline-implement`
- Slightly more verbose skill files, but the trade-off is justified by the reduction in wasted implementation work

## Alternatives Considered

- **Rely on hard gates only** — Rejected. Hard gates between phases do not prevent the agent from jumping straight to implementation if it misinterprets the user's initial request.
- **Add a separate `aet-guardrails` skill** — Rejected. Lockout must live inside the planning skills themselves so it is loaded into context whenever planning is triggered. A separate skill might not be invoked.
- **Tool-level restrictions (e.g., "do not use WriteFile")** — Rejected. Skills must remain agent-agnostic and not assume specific tool names or invocation mechanisms.
