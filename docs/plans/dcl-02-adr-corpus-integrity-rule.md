---
blocked_by:
docs_sync: required
id: dcl-02-adr-corpus-integrity-rule
pipeline: standard
security_review: skipped
size: M
work_class: normal
---

# Plan: The ADR Corpus Is Checked as a Whole

## Context

PRD: docs/prds/document-conformance-lint-prd.md (R-1, R-5)
Decision: ADR-074, decisions 2, 5 and 6 — the grammar gains
`adr_corpus_integrity`; supersession logic has one implementation; a new rule
lands at warning severity.

`unique_live_subject` in `src/aet/docs_lint.py` was added by ADR-056 to make the
ADR corpus self-checking. It contains:

```python
if data is None:
    # ADRs without frontmatter are ignored.
    continue
```

39 of 72 records carry no frontmatter, so the rule skips more than half its corpus
by instruction. Because it keys on `subject`, the two records numbered 072 declared
different subjects and passed cleanly — nothing keys on the number.

Meanwhile `resolve_rules` in `src/aet/context_digest.py` already computes dangling
`supersedes:` and renders `_conflict_rule` for it. It printed
`CONFLICT supervision-uniformity: dangling supersedes: 53` on every session start
for weeks and gated nothing. Decision 5 forbids a second implementation: the rule
consumes that resolver.

`relates:` is read by nothing today. This rule is its first consumer.

## Intake Triage

- [x] The four instances were demonstrable and were repaired by hand in `39d84e6e`
- [x] Routed here because the deliverable is a new rule type in a grammar ADR-040
      declares a public contract, not a repair

## Task List

1. Extend `context_digest`'s resolver, or expose a helper beside it, so a caller
   can obtain dangling relations, duplicate numbers and superseded-target
   relations without re-walking frontmatter — S (traces: R-1)
2. Add `adr_corpus_integrity` to `VALID_RULE_TYPES` and implement the evaluator,
   consuming that helper: duplicate numbers, dangling `supersedes:`/`relates:`,
   relations naming a superseded record, and missing `subject:`. Keep ADR-056's
   template/README exclusion and its malformed-frontmatter fail-closed behaviour,
   both carried forward by ADR-074 decision 4 — M (traces: R-1)
3. Distinguish the two relation failures in the message: a relation naming a
   record that never existed is a typo, one naming a superseded record is drift
   — S (traces: R-1)
4. Decide `unique_live_subject`'s frontmatter skip explicitly — remove it now that
   R-1 refuses that state, or leave it and correct the comment. Do not leave both
   behaviours standing unexplained (PRD Open Questions) — S (traces: R-1)
5. Fixture tests constructing each violating corpus: two records sharing a number,
   a dangling `supersedes:`, a `relates:` to a superseded record, an ADR with no
   `subject:`, and a clean corpus that passes. ADR-072 requires conformance be
   shown by the divergent case — this rule exists because the agreeing case passed
   for months — M (traces: R-1)
6. Add the rule to `.agents/doc-rules.yaml` targeting `docs/adr`, at warning
   severity — the corpus still has 39 records without `subject:` and dcl-03 has
   not swept them — S (traces: R-5)
7. Merge branch to main and verify integration — S

### Floor Check

- [ ] Expected diff is below the calibrated floor threshold
- [ ] The change is limited to one subsystem and maintains no architectural invariant
- [ ] `Files to Modify` substantially overlaps a sibling it is ordered against
- [ ] This is docs-only and its sole consumer is a single sibling

No boxes checked. The rule crosses `docs_lint` and `context_digest` and lands a
grammar change ADR-040 treats as a public contract.

## Files to Modify

- `src/aet/docs_lint.py`
- `src/aet/context_digest.py`
- `.agents/doc-rules.yaml`
- `tests/scripts/test_docs_lint.py`

## Rejected Alternatives

**Implement supersession resolution inside `docs_lint`.** Rejected by ADR-074
decision 5. Two implementations of the same rule beside each other is the defect
class this initiative exists to close, and the corpus already demonstrates the
cost: one reader warned about a dangling edge the other could not see.

**Gate `aet context`'s CONFLICT output instead of adding a rule.** Rejected: the
digest is a session-context tool, not a gate, and making it exit non-zero would
couple session startup to corpus health. ADR-040 puts governance invariants in
`aet docs lint`.
