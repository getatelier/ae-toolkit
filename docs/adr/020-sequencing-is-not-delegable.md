---
subject: sequencing-is-not-delegable
---

# Scheduling Is Delegable; Sequencing Is Not; the CLI Is the Enforcement Boundary

## Status

Accepted (2026-07-10). Implements PRD `docs/prds/roadmap-p0-decision-records-prd.md` G1; informed by fable-review 06 (`content/fable-review/06-2026-07-10-cli-contract-engine-discussion.md`, Resolutions 2/6, the P1/P2 razors, and the multi-harness addendum) and 09 (`content/fable-review/09-2026-07-10-roadmap.md`).

## Context

fable-review 02 recommended demoting the local orchestrator to a portable fallback. Doc 06 Resolution 2 amended it: harnesses are session-scoped while AET's pipeline is lifecycle-scoped — cross-session, cross-agent, multi-day, with a ledger. Harness vendors ship mechanisms, not policy (the incentive argument, doc 06 Resolution 3). The question is therefore not whether to delegate, but where the line falls between what can be handed off and what must be enforced in the repo.

## Decision

1. Scheduling and compute (cron, CI, cloud runners) are freely delegable.
2. Sequencing, state legality, and gate evidence are never delegated; they are enforced by the CLI layer (today `aet-work`/`aet-state`; destination: the single `aet` binary).
3. Placement razor: if an agent ignoring an instruction would corrupt state or skip a gate, it goes in the CLI; if it would just produce worse work, it stays skill prose.
4. Route with judgment once at plan time, enforce with code forever — no runtime conditionals in the engine.
5. Multi-harness: inbound (any agent shells out to the CLI) is identity and universal; outbound (spawning harnesses) is a scoped adapter contract with conformance tiers — "supported" = conformance suite green in CI. Harness/model routing is workflow config, not process structure. Formulation: **substitutability, enforced in the repo, proven on the scoreboard**.

## Consequences

- Workflow-as-data becomes possible (roadmap Phase 1).
- skills-lint and git hooks are the second wall behind the CLI boundary.
- No daemon — always-on is cron + run-once.
- Per-harness support claims become CI properties, not README claims.
