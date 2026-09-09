---
subject: evolve-in-place
---

# Evolve in Place; the Greenfield Is Trigger-Gated

## Status

Accepted (2026-07-10). Implements PRD `docs/prds/roadmap-p0-decision-records-prd.md` G2; informed by fable-review 08 and 09 (`content/fable-review/09-2026-07-10-roadmap.md`).

## Context

Doc 08 recommended a greenfield Go kernel; its escape rationale (unsound concurrency, dead weight) was retired the same day it was written — the frh hardening arc (frh-03…frh-17) completed 2026-07-10. Owner decision: AET is working well and stable; keep compounding the learnings in the chassis that earned them.

## Decision

1. AET evolves the existing chassis; the doc 08 greenfield is demoted to a reference design study.
2. Four re-opening triggers, recorded verbatim: external install demand where Python distribution hurts; a second workflow class straining the chassis; the CLI identity structurally fighting Python; the embedded-skills endgame becoming strategic.
3. Convergence commitment: plumbing decisions steer toward doc 08's shape (ledger-as-git, projections over one source of truth, frozen states) so a future port is a translation, not a redesign.
4. A fired trigger re-opens the question only via a new ADR superseding this one — never silently.

## Consequences

- Roadmap phases 1–7 run on the current chassis.
- The git-refs backend flips to default in Phase 3.
- Doc 08 stays the benchmark for every storage/state decision.
