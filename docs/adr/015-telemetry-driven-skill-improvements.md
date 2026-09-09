---
subject: telemetry-driven-skills
---

# Telemetry-Driven Skill Improvements

## Status

Accepted

## Context

`aet-evolve mine-learnings` scans the local telemetry archive (`~/.aet/telemetry/`) for recurring patterns across projects that use the AE Toolkit. The first mining runs surfaced five high-frequency pain points:

1. Dependency-related environment issues (missing `node_modules`, `vendor`, etc.).
2. Repeated validation/retry loops during implementation.
3. Full-suite test runs when impact-scoped tests would suffice.
4. Stage failures without structured triage before human escalation.
5. Review noise from project-level files (`.gitignore`, `AGENTS.md`, etc.).

The question is whether the toolkit should treat telemetry mining as an input to skill design and periodically harden skills based on observed patterns.

## Decision

Yes. The AE Toolkit will use telemetry mining as a first-class input to skill improvements.

1. `aet-evolve mine-learnings` remains the manual trigger for cross-project analysis.
2. Recurring patterns with clear skill-level mitigations become PRDs and atomic plans.
3. Skill changes are validated with `make validate` and repackaged as `.skill` files.
4. No external telemetry service is introduced; the analysis stays local-first on `~/.aet/telemetry/`.
5. Telemetry patterns inform documentation and guardrails, not autonomous skill edits.

## Consequences

- **Easier:** Skills improve based on observed friction rather than anecdotal reports.
- **Easier:** Recurring environment and validation issues are caught earlier in the pipeline.
- **Harder:** Telemetry quality depends on projects actually running `aet-work` and keeping the archive. Mitigated by direct archive writes (ADR-012) and clear local retention rules.
- **Harder:** Proposed skill edits must still pass planning, review, and validation like any other change.

## Relation to ADR-012

ADR-012 established the direct, per-task telemetry archive that makes this analysis possible. This ADR records the decision to act on that data by feeding mined patterns back into skill design.

## Alternatives Considered

1. **Keep telemetry as diagnostics only, never change skills from it.** Rejected: it leaves recurring friction unaddressed.
2. **Autonomously edit skills from telemetry patterns.** Rejected: skill changes still require human review, planning, and validation.
3. **Build a dashboard or external analytics pipeline.** Rejected: conflicts with the toolkit's local-first, infra-agnostic design.
