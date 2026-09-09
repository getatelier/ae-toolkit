---
subject: documentation-invariants-as-data
---

# Documentation Invariants Are Data

## Status

Accepted

## Context

Source: [docs/prds/prose-lint-decoupling-prd.md](../prds/prose-lint-decoupling-prd.md) (R-1).

`make validate` is the only safety net in this repo — CI is ruled out on cost — so it must be both complete and fast. The prose-only fast path achieves the speed by enumerating the test modules that read repo Markdown, policed by an AST guard. That enumeration exists only because documentation invariants are written as pytest assertions.

The invariants are declarative. Every prose assertion in the current suite reduces to one of four patterns: a substring must be present, a substring must be absent, a substring must be present (or absent) under a named section, or a file path must exist (or be absent). Encoding these patterns as data, and evaluating them in a lint stage, removes pytest's dependency on Markdown entirely. The fast path then becomes safe *by construction* — prose-only changes run no pytest at all — instead of safe *by enumeration*.

This decision records the principle and the rule grammar before the engine is built, matching the precedent set by ADR-039 (namespace taxonomy) landing before the CLI rewrite that implements it.

## Decision

### Principle

Documentation invariants are declared as data and enforced by a lint stage. They are never asserted in the unit-test suite.

- Governance rules live in a repo-controlled rules file (`.agents/doc-rules.yaml`).
- `aet docs lint` loads the rules and evaluates them against the checkout.
- `make validate` runs `aet docs lint` before pytest, preserving fail-fast ordering.

### Rule grammar

A rule is a YAML mapping with a `type` field. The evaluator supports exactly four types:

1. **`must_contain`** — the target file must contain the given substring.
2. **`must_not_contain`** — the target file must not contain the given substring.
3. **`section: must_contain`** and **`section: must_not_contain`** — the substring assertion is scoped to the content under the named Markdown heading. The `section` field narrows matching to that heading's body; the rest of the file is ignored for that rule.
4. **`path_exists`** and **`path_absent`** — the rule asserts the presence or absence of a file or directory in the repo. These cover layout checks that are not prose but currently ride alongside content assertions.

Every rule carries a required `reason` field. A failure is rendered as `<file>: <reason>` together with the offending expectation, so messages stay at least as diagnostic as the assertions they replace. A bare "substring not found" is a regression.

Rules are parsed with `yaml.safe_load`. The evaluator must not execute rule content; a rules file is data, not code.

### Boundary against `scripts/skills-lint`

`scripts/skills-lint` already has one clear job: validating documented `aet` invocations against `SUBCOMMANDS` and each target's `build_parser()`. Governance content invariants do not move into it.

- `skills-lint` checks that documentation matches the CLI surface.
- `aet docs lint` checks that documentation satisfies governance invariants.

The two stages may share conventions (severity levels, `<!-- aet-lint: off -->` escape hatches), but they remain separate concerns.

### Posture for missing targets

A rule whose target file is missing fails closed by default. A `path_absent` rule covers deliberately retired files, so a stale rule pointing at a removed file blocks work explicitly rather than silently passing.

## Consequences

- **Easier:** Adding a new documentation invariant is a line in a rules file, not a new Python test module.
- **Easier:** The prose-only fast path needs no allowlist or AST guard; it is correct by construction once pytest no longer reads Markdown.
- **Easier:** Failure messages name the file, the expectation, and why it matters, matching today's assertion quality.
- **More difficult:** A malformed or stale rule can block unrelated work, so rule retirement must be explicit (`path_absent` or rule deletion with intent).
- **More difficult:** The rule grammar is a public contract; changing it requires a new ADR and migration of existing rules.

## Alternatives Considered

- **Fold governance rules into `scripts/skills-lint`.** Rejected. That script has one clear job (validating documented `aet` invocations against real parsers); adding unrelated content invariants to a 328-line script conflates two concerns.
- **Skip the ADR and encode the grammar only in code.** Rejected. The rule format is the contract every future invariant is written against; leaving it implicit invites drift and re-litigation.
- **Marker-based pytest selection (`@pytest.mark.prose`).** Rejected. It still requires enumeration plus a guard to catch unmarked tests, so it preserves the maintenance surface this workstream exists to delete.
