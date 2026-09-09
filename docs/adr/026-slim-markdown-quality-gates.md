---
subject: markdown-quality-gates
---

# Slim Markdown Quality Gates

## Status

Accepted (2026-07-14). Implements PRD `docs/prds/validate-gate-review-prd.md` R-4; delivered by plans `vgr-01-slim-markdown-gates` and `vgr-02-gate-docs-adr`.

## Context

The AE Toolkit repo is Markdown-native: skills, docs, plans, and ADRs are all `.md` files with YAML frontmatter. For a long time the quality surface treated cosmetic formatting (prettier) as a first-class gate: `make format-check` ran in `make validate` and the pre-commit hook ran both `make lint` and `make format-check`.

Measurement showed the cost profile was poor:

- **Prettier produced churn, not signal.** Most prettier diffs were whitespace, line-wrapping, and quote-normalization changes that did not affect correctness, readability, or structure. Reviewers routinely accepted them without reading; agents re-ran `make format` to silence a red check rather than to improve the doc.
- **Markdownlint caught real defects** (broken internal links, malformed tables, inconsistent heading levels) but was heavy in its default configuration and slow enough to discourage running it on every commit.
- **The full `make validate` was reorder-sensitive.** It ran `lint`, `format-check`, and `lint-py` before the structural validators that catch the most expensive mistakes (`skills-lint`, `validate-workflows`, `validate-skills`). Failing fast on cheap, high-value checks shortens the feedback loop.
- **Gate evidence (ADR-019) added a freshness path** that trusts an earlier QA verdict when only non-code files changed. That path includes a `LINT_ONLY` mode intended to re-lint markdown; if markdownlint is no longer part of `make validate`, that mode loses markdown coverage. Pre-commit already lints staged markdown files, so the gap is acceptable.

The question, then, was not whether to keep every tool, but which tools catch real problems at what cost.

## Decision

1. **Drop prettier from the quality surface.** The `make format-check` command is removed from the documented command table and from `make validate`. Cosmetic formatting is no longer a gating check. The `make format` convenience target may remain, but it is not part of the required path.
2. **Slim and pin markdownlint.** Keep markdownlint as a light, staged-only guard in the pre-commit hook. Run it only on staged markdown files, not the entire repo, and pin the CLI version in `Makefile` so the rule set is stable.
3. **Fail-fast reorder in `make validate`.** Run the cheap, high-value structural and semantic checks before pytest: `lint-py` → `validate-workflows` → `skills-lint` → `validate-skills` → `test`.
4. **Keep the real validators.** Structural correctness (`validate-skills`), semantic skill lint (`skills-lint`), workflow correctness (`validate-workflows`), Python lint (`ruff`), and the pytest suite remain mandatory.

## Consequences

- Markdown cosmetic formatting is no longer enforced. Authors are responsible for readable structure; reviewers judge formatting by eye instead of by tool.
- YAML/JSON blocks embedded in Markdown lose automatic cosmetic formatting. Frontmatter and code examples must be kept valid by author care and by the structural validators.
- `make validate` no longer re-lints all markdown. The ADR-025 `LINT_ONLY` freshness path therefore does not re-lint markdown either. Pre-commit covers staged markdown files, so the combined coverage is acceptable; full-repo markdown lint remains available via `make lint` when needed.
- The pytest-xdist trade-off (plan `vgr-04`, if adopted) interacts with this decision: faster pytest execution reduces the pain of keeping `test` last in the fail-fast order, while the structural checks that run first remain cheap.
- The documented quality surface is now structure + semantics + code, not structure + formatting.

## Alternatives Considered

- **Drop both prettier and markdownlint** — rejected: markdownlint catches real defects (broken links, malformed tables) that are hard to spot in review and cheap to run on staged files.
- **Keep prettier and fix the churn** — rejected: the churn is inherent to cosmetic formatting in a Markdown-only repo. A stricter prettier config would reduce variance but not the fundamental cost of enforcing style that does not affect correctness.
