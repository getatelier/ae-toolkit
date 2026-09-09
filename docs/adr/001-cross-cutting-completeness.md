---
subject: cross-cutting-completeness
---

# Cross-Cutting Completeness Framework

## Status

Accepted

## Context

Renderer components shipped with `className` attributes but zero CSS definitions. Tickets went through the full pipeline (plan, implement, QA, review, security, merge) and every gate passed because all checks were compile-time or test-time. TypeScript succeeds with undefined `className` values. No visual completeness check existed in any skill.

This revealed a broader pattern: changes that touch one domain (e.g., a React component) often have implicit obligations in another domain (e.g., CSS). These cross-cutting obligations slip through because no single skill owns them end-to-end.

## Decision

Introduce the **Cross-Cutting Completeness** framework. For every domain where a diff creates implicit obligations in another domain, we will:

1. Define the completeness property (what "done" looks like)
2. Assign a verification mechanism (which skill, which step)
3. Document the pattern as a reusable template

The pattern template is:

> When a diff touches **[domain]**, verify **[completeness property]** by **[mechanism]**.

### First proven example: CSS completeness

- **Domain:** Renderer components with custom `className` values
- **Completeness property:** Every custom `className` has a corresponding CSS definition
- **Mechanism:** `aet-review` CSS completeness lens (see `aet-review/references/css-completeness-check.md`)

### Future domains

- **i18n** — every user-facing string has a translation key
- **Assets** — every referenced image/font/icon exists in the build output
- **Icons** — every icon name maps to a loaded icon set
- **Feature flags** — every new feature is gated behind a documented flag

## Consequences

- Plan templates now include a Renderer/UI Tasks section reminding authors to verify CSS
- `aet-implement` validates CSS completeness before declaring implementation done
- `aet-review` runs a CSS completeness lens on every diff touching renderer code
- New cross-cutting domains can be onboarded using the same template

## Alternatives Considered

- **Add a new dedicated skill** — Rejected. The framework is more powerful when embedded into existing skills (plan, implement, review) rather than adding yet another gate.
- **Lint rule only** — Rejected. Lint can catch undefined CSS modules, but not completeness of design intent (e.g., a className that exists in CSS but is visually wrong). Human-judgment lenses remain necessary.
