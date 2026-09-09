---
subject: remove-aet-discover
---

# Remove aet-discover from AE Toolkit

## Status

Accepted

## Context

`aet-discover` is a product-management diagnostic. It runs YC-style forcing questions to validate demand and narrow the wedge, producing a product brief rather than a PRD. The skill was originally positioned as the first step in the AE Toolkit pipeline, before `aet-plan`.

Over time, the toolkit's focus sharpened around agentic engineering: planning, design, implementation, review, security, QA, shipping, and evolution. Product-definition diagnostics are valuable, but they are not agentic engineering. They sit upstream of the engineering workflow and do not share the same artifacts, success criteria, or user. Keeping `aet-discover` inside the toolkit created several problems:

- **Scope confusion:** The toolkit's promise is a coherent engineering pipeline, yet it included a skill whose output is explicitly "no code" and whose gate is product validation, not engineering readiness.
- **Pipeline friction:** `aet-pipeline-plan` had already removed the mandatory `aet-discover` step, leaving the skill as a standalone pre-step that no longer integrated cleanly with the rest of the system.
- **Maintenance overhead:** Every README, planning skill, and setup reference had to explain when to use `aet-discover` and when to skip it. This defensive prose complicated onboarding.
- **Honest positioning:** Distributing `aet-discover` as part of AE Toolkit implied it was an agentic engineering skill. Removing it makes the toolkit's boundaries clear.

Historical records — PRDs, retros, audits, changelog entries, and product briefs produced by the skill — remain in place. They document past decisions and are not invalidated by this removal.

## Decision

Remove `aet-discover` from AE Toolkit entirely:

1. Delete the `aet-discover/` skill directory.
2. Delete the generated `aet-discover.skill` artifact.
3. Remove `aet-discover` from the README skill table, workflow tagline, "What you get" bullets, and pipeline description.
4. Remove `aet-discover` references from `PRODUCT.md`, `aet-plan/SKILL.md`, `aet-design-system-creation/SKILL.md`, and `aet-setup/references/README.md`.
5. Keep historical docs unchanged: `CHANGELOG.md`, past PRDs, retros, audits, and product briefs.
6. Update this ADR as the authoritative record of the removal.

## Consequences

- **Clearer scope:** AE Toolkit is now strictly an agentic engineering pipeline. Users know they are getting engineering workflow skills, not product-management tools.
- **Simpler onboarding:** README and planning skills no longer need to explain the discover/plan boundary.
- **Reduced maintenance:** One fewer skill to format, lint, package, and keep under the 400-line limit.
- **Loss of discoverability:** Users with raw, unvalidated ideas no longer have a toolkit-provided diagnostic. They must validate ideas outside AE Toolkit before invoking `aet-plan` or `aet-pipeline-plan`.
- **Historical docs remain:** Past decisions that reference `aet-discover` stay readable. We do not rewrite history.

## Alternatives Considered

- **Keep `aet-discover` as a standalone skill.** Rejected. It blurred the toolkit's scope and no longer fit the pipeline narrative.
- **Move `aet-discover` to a separate product-management skills repo.** Not pursued here. If a PM-focused skill suite is created later, `aet-discover` can be resurrected from git history.
- **Rewrite `aet-discover` to be engineering-focused.** Rejected. The skill's core value is product validation; retooling it would produce a weaker, less honest tool.
