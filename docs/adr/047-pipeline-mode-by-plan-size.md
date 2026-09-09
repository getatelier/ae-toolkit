---
subject: pipeline-mode-by-plan-size
---

# Pipeline Mode Selection by Plan Size

## Status

Accepted

## Context

The AE Toolkit pipeline (`aet-work`) can run a plan in three isolation modes:

- `minimal` — all skilled stages in one agent session.
- `standard` — the workflow's default stage groups (e.g. `[plan-approved, implemented]`, `[qa-complete]`, `[reviewed, secure]`).
- `full` — one agent session per stage.

Every plan declares the mode in its frontmatter (`pipeline: standard`). Until now the choice has been ad hoc: authors defaulted to `standard` and only switched to `minimal` or `full` after manual risk judgment.

Telemetry from the toolkit's own usage (`~/.aet/telemetry/aiskills/`) shows that the post-planning pipeline is where most effort is spent, but the bulk of that effort is implementation and QA, not the later review/security/sync gates:

| actual stage | skills | % of pipeline time | % of pipeline tokens | observed failure rate |
| --- | --- | --- | --- | --- |
| `plan-approved` | `aet-tdd`, `aet-implement` | 35% | 33% | ~27% |
| `implemented` | `aet-qa` | 33% | 30% | ~25% |
| `qa-complete` | `aet-review` | 19% | 20% | ~5% |
| `reviewed` | `aet-cso` | 5% | 6% | ~0% |
| `secure` | `aet-sync-docs` | 8% | 12% | ~0% |

Implementation and QA together consume about two-thirds of pipeline time and fail frequently, which means the work is genuinely hard and the QA gate catches real defects. The later gates rarely fail because earlier gates filter most issues, but audits show they still catch real problems (e.g. mirror verification, archive-root confinement, PRD footer drift).

The real overhead is not the existence of the gates; it is the cost of repeatedly re-deriving context and re-running validations across separate agent sessions. A prior pipeline-flow audit (`docs/audits/2026-07-13-pipeline-flow-efficiency.md`) measured full test suites running 4–5 times per pipeline and every stage session re-reading the plan, ADRs, and diff from scratch.

When small (`S`) plans use `pipeline: minimal`, telemetry shows the same failure rate as `standard` (~12% vs ~11%) with less session-split overhead. For larger plans the staged gates still provide value.

## Decision

Adopt a **size-based advisory default** for `pipeline` in plan frontmatter, with a **risk override** that always takes precedence. This is guidance for the plan author, not an intake gate; it is consistent with ADR-046 (size is a prediction, not an enforcement mechanism).

| plan size | default `pipeline` | rationale |
| --- | --- | --- |
| **S** (≤ 2 hr human time / ≤ 100 expected diff lines) | `minimal` | Telemetry shows no reliability regression; avoids session-split overhead for trivial work. |
| **M** (≤ 1 day / ≤ 200 lines) | `standard` | Staged QA and review catch real defects without the cost of `full`. |
| **L** (> 1 day OR > 200 lines) | `standard` or `full` | Larger change surface benefits from more isolation; author picks based on risk. |

**Risk override:** Regardless of size, use `standard` or `full` when the change touches any of the following:

- authentication, authorization, sessions, or permissions
- data models, migrations, or persisted state
- public/internal API contracts or wire formats
- dependencies, frameworks, or infrastructure
- security-sensitive surfaces (secrets, trust boundaries, injection paths)

Plan authors must record the `pipeline` value explicitly; there is no orchestrator auto-switch. The default is a convention carried in the plan template and `aet-plan` skill instructions.

## Consequences

- **Easier:** Small plans run faster and with less orchestrator overhead.
- **Easier:** Authors no longer make an arbitrary choice for every plan.
- **Harder:** Authors must honestly assess risk; a careless `minimal` choice on an auth change violates the override rule.
- **Safer:** Larger and riskier plans keep the staged gates that catch defects.
- **Observable:** Because `pipeline` remains explicit frontmatter, telemetry can continue to compare failure rates across modes.

## Alternatives Considered

1. **Auto-default in the orchestrator based on `size`.** Rejected. Size is a measurement, not a hard gate (ADR-046). Making the orchestrator silently override a declared or implied value would add magic and complicate debugging. Convention-first keeps the decision visible in the plan file.

2. **Keep the status quo (`standard` for everything).** Rejected. Telemetry shows `minimal` is just as reliable for `S` plans, and the prior audit shows the session-split overhead is real and fixable.

3. **Collapse the entire pipeline for all plans (remove staged gates).** Rejected. Implementation and QA fail in about one-quarter of runs; the gates catch real defects. Removing them would shift cost from structured gates to unplanned rework.
