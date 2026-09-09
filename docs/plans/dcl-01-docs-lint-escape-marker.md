---
blocked_by:
docs_sync: required
id: dcl-01-docs-lint-escape-marker
pipeline: standard
security_review: skipped
size: S
work_class: normal
---

# Plan: An Escape Marker for `aet docs lint`

## Context

PRD: docs/prds/document-conformance-lint-prd.md (R-4)
Decision: ADR-074 (A Fact a Document Copies From Code Is Checked Against That
Code), decision 7 — a deliberate divergence is declared, not tolerated.

`scripts/skills-lint` has an escape hatch: `extract_spans` tracks
`<!-- aet-lint: off -->` and `<!-- aet-lint: on -->` markers per line and exempts
the spans between them. `src/aet/docs_lint.py` has nothing equivalent — it reads
whole files (`_check_text`) and named sections (`_extract_section`).

Both rules that follow need one. `skills/aet-work/references/migration-aet-state.md`
and `upgrading-existing-project.md` describe migrating *away from*
`.agents/work-queue.json`, where naming the retired path is the entire point, and a
PRD may legitimately cite code as it stood when a decision was made. Without the
escape, dcl-04 and dcl-05 would refuse correct prose with no way to say so — which
is how a rule gets switched off rather than obeyed.

The marker's spelling is reused rather than invented, so the repository has one
convention. The implementation cannot be reused: `skills-lint` strips to code spans
first, `docs_lint` matches over raw text.

## Intake Triage

- [x] Not a defect — `docs_lint` never had an escape mechanism; nothing is
      behaving unexpectedly
- [x] Routed here because it is a prerequisite two sibling tasks are ordered
      against, recorded in ADR-074 decision 7

## Task List

1. Add a marker-stripping helper to `src/aet/docs_lint.py` that removes spans
   between `<!-- aet-lint: off -->` and `<!-- aet-lint: on -->` from a document
   before rule evaluation, treating an unclosed `off` as running to end of file
   — S (traces: R-4)
2. Route `_check_text` and `_extract_section` through it so every content rule
   type honours the escape, existing types included — S (traces: R-4)
3. Unit tests: a violation inside an escaped span passes; the same violation
   outside it fails; an unclosed `off` exempts the remainder; a document with no
   markers is byte-identical after stripping — S (traces: R-4)
4. Document the marker in `docs/CONVENTIONS.md` beside the existing lint guidance
   — S (traces: R-4)
5. Merge branch to main and verify integration — S

### Floor Check

- [ ] Expected diff is below the calibrated floor threshold
- [x] The change is limited to one subsystem and maintains no architectural invariant
- [ ] `Files to Modify` substantially overlaps a sibling it is ordered against
- [ ] This is docs-only and its sole consumer is a single sibling

One box checked. It stays a separate task because two siblings are ordered against
it and would each need it built to be testable.

## Files to Modify

- `src/aet/docs_lint.py`
- `tests/scripts/test_docs_lint.py`
- `docs/CONVENTIONS.md`

## Rejected Alternatives

**Per-rule `exempt:` lists in `.agents/doc-rules.yaml`.** Rejected: the exemption
would live away from the prose it exempts, so a reader of the migration guide would
have no way to see that its retired-path reference is deliberate. ADR-074 decision
7 requires the divergence be declared at the call site.
