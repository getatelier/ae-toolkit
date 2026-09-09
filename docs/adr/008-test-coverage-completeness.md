---
subject: test-coverage-completeness
---

# Test Coverage Completeness + API Boundary Contract

## Status

Accepted

## Context

`aet-tdd`'s `plan-tests` step listed behaviors "to test" based on what the agent imagined, not on a systematic enumeration of what the plan introduces. The completion protocol checked only that tests pass — never that every new file had coverage. The result: entire modules shipped with zero tests, passing all gates because no gate verified coverage completeness.

This is the same cross-cutting blind spot that ADR 001 identified for CSS completeness.

## Decision

Add two new domains to the Cross-Cutting Completeness framework (ADR 001):

1. **Test coverage completeness** — When a plan introduces new source files, every file must have at least one test.
2. **API boundary contract** — When a vertical slice introduces both a backend endpoint and a frontend consumer, an API boundary test must exist.

Both are **hard gates** (blocking failures) in `aet-tdd`:

- A new source file at 0% coverage blocks `tdd-complete`.
- A vertical slice without an API boundary test blocks `tdd-complete`.

## Rationale

Zero-coverage files produce silent regressions. The cost of the gate is low — coverage runs with the test suite — and the trade-off was explicitly evaluated and decided. A soft suggestion would be ignored under time pressure; a hard gate forces the test to be written or the omission to be consciously justified.

## Consequences

- `aet-tdd` `plan-tests` derives its minimum test list from the plan's file list, not intuition.
- `aet-tdd` completion protocol runs coverage and blocks on 0% files.
- `aet-tdd` references include `api-boundary-tests.md` for patterns.
- New cross-cutting domains can be onboarded using the same ADR 001 template.
