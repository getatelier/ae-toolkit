---
blocked_by:
  - dcl-01-docs-lint-escape-marker
docs_sync: required
id: dcl-05-code-anchor-rule-and-sweep
pipeline: standard
security_review: skipped
size: M
work_class: normal
---

# Plan: Code Anchors Resolve to a Symbol, Not a Line

## Context

PRD: docs/prds/document-conformance-lint-prd.md (R-3, R-5, R-6)
Decision: ADR-074, decisions 1, 2 and 6.

`aet-sync-docs` reads the code anchors PRDs carry, so an anchor that resolves to
unrelated code makes a sync run report false divergence. 132 `path.py:NN` anchors
sit across 20 PRDs; 10 further documents carry them in `docs/adr`, `CONTEXT.md` and
`docs/CONVENTIONS.md`.

The failure is not hypothetical or gradual. When the telemetry-adapter-parity
initiative closed, four of its five anchors resolved to unrelated code and **three
of the symbols those anchors named no longer existed at all** — `_TEST_RUNNER_RES`,
`_emit_wire_test_runs` and `_test_runner_args`. It was re-anchored by hand on
2026-08-30, which repaired one PRD and prevented nothing.

Line numbers are unmaintainable by construction: the file moves and the prose does
not. A symbol name is the cheap durable form, and it is checkable.

**Resolution is by definition, not occurrence** (PRD, Resolved During Scope
Validation). A grep would accept a symbol surviving only in a comment or docstring
— the half-dead state that makes an anchor misleading rather than absent. Python
targets are parsed with `ast`; non-Python targets fall back to occurrence matching
and the message says which mode was used.

**The target set is data.** The rule takes a `target` like every other rule type,
so it lands pointed at `docs/prds/` and widening to the other 10 documents later is
a rules-file edit plus a sweep, with no new code.

## Intake Triage

- [x] The stale anchors were demonstrable and were repaired by hand in `39d84e6e`
- [x] Routed here because the deliverable is a rule type plus a 20-file sweep

## Task List

1. Add `code_anchor_resolves` to `VALID_RULE_TYPES` and implement the evaluator:
   refuse `path:NN` line anchors; for a symbol anchor, parse the named file with
   `ast` and require a matching `def`, `class` or module-level assignment. Fall
   back to occurrence matching for non-Python targets and name the mode in the
   message — M (traces: R-3)
2. Fail closed and distinguishably when the anchored *file* does not exist — a
   moved module and a renamed symbol need different fixes — S (traces: R-3)
3. Honour dcl-01's escape marker so a PRD can cite code as it stood at a decision
   — S (traces: R-3)
4. Fixture tests: a line anchor is refused; a symbol resolving to a definition
   passes; a symbol present only in a comment is refused; a missing file is
   reported distinctly; an escaped anchor passes — M (traces: R-3)
5. Add the rule to `.agents/doc-rules.yaml` targeting `docs/prds`, at warning
   severity — S (traces: R-5)
6. Re-anchor the 132 occurrences across 20 PRDs on symbol names, verifying each
   resolves rather than transcribing it. Where the symbol is gone, name what
   replaced it — the parity PRD's re-anchoring is the worked example
   — M (traces: R-6)
7. Ratchet the rule to error and confirm `make validate` is green — S (traces: R-5)
8. Merge branch to main and verify integration — S

### Floor Check

- [ ] Expected diff is below the calibrated floor threshold
- [ ] The change is limited to one subsystem and maintains no architectural invariant
- [ ] `Files to Modify` substantially overlaps a sibling it is ordered against
- [ ] This is docs-only and its sole consumer is a single sibling

No boxes checked. A grammar change plus a 20-file sweep across 132 anchors.

## Files to Modify

- `src/aet/docs_lint.py`
- `.agents/doc-rules.yaml`
- `tests/scripts/test_docs_lint.py`
- `docs/prds/*.md` (20 files)

## Rejected Alternatives

**Refuse anchors entirely and require prose descriptions.** Rejected: the anchors
are load-bearing — `aet-sync-docs` consumes them — so removing them would break a
working consumer to avoid maintaining a check.

**Resolve symbols by grep.** Rejected in scope validation: a symbol named only in a
comment or docstring would pass, which is exactly the state that makes a stale
anchor misleading. `ast` is stdlib and the parse is per-anchored-file.

**Widen the target to every document immediately.** Rejected: it triples the sweep
for documents no tool reads. The rule is data-driven, so widening later costs a
rules-file edit.
