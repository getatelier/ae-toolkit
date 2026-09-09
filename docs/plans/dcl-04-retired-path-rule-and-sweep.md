---
blocked_by:
  - dcl-01-docs-lint-escape-marker
docs_sync: required
id: dcl-04-retired-path-rule-and-sweep
pipeline: standard
security_review: skipped
size: M
work_class: normal
---

# Plan: Retired Data Paths Are Refused in Prose

## Context

PRD: docs/prds/document-conformance-lint-prd.md (R-2, R-5, R-6)
Decision: ADR-074, decisions 1, 2 and 6 — a fact a document copies from code is
checked against that code.

The `git-refs` backend stores the board in `refs/aet/tasks/*` with a
`refs/aet/meta/queue` envelope. `.agents/work-queue.json` is a path it no longer
writes, and `aet setup verify` already warns when `.gitignore` names it. Skill
prose still names it ~50 times across 13 files in six skills, heaviest in
`skills/aet-work/references/queue-commands.md` (14) and `skills/aet-work/SKILL.md` (6).

The set of retired paths already exists in code as `AET_RETIRED_IGNORED_PATHS` in
`src/aet/worktree.py`, which carries four entries and exists so `aet setup` can
report a project still holding them. The rule imports it. A copy in the rules file
would be the same defect this initiative closes.

**The occurrences are not uniformly wrong.**
`skills/aet-work/references/migration-aet-state.md` and
`upgrading-existing-project.md` describe migrating *from* that layout, where naming
the old path is the point. `worktree.py` names it deliberately in the constant
itself. dcl-01's escape marker is what distinguishes these from drift; a blind
replace would corrupt all three.

## Intake Triage

- [x] The references are demonstrably stale — the backend stopped writing that path
- [x] Routed here because the deliverable is a rule type plus a judged sweep, not a
      targeted fix; a sweep alone was rejected in the PRD's Overview

## Task List

1. Add `retired_path_absent` to `VALID_RULE_TYPES` and implement the evaluator,
   importing `AET_RETIRED_IGNORED_PATHS` from `src/aet/worktree.py` so the source
   of truth stays the code. Honour dcl-01's escape marker — M (traces: R-2)
2. Test that a path added to `AET_RETIRED_IGNORED_PATHS` is refused with no edit to
   the lint, and that a reference inside an escape span passes. The first is the
   requirement's actual content: the rule must not carry its own copy
   — S (traces: R-2)
3. Add the rule to `.agents/doc-rules.yaml` targeting `skills`,
   `.agents/templates`, `.agents/commands` and `AGENTS.md`, at warning severity
   — S (traces: R-5)
4. Sweep the drifted references to the current board vocabulary, per file. The
   2026-08-23 learning is specifically about sweeps reported complete while wrong
   copies survive in reference files and templates, so reference files are swept
   before `SKILL.md` files, not after — M (traces: R-6)
5. Wrap the migration guides' deliberate references in the escape marker with a
   one-line note saying why — S (traces: R-6)
6. Ratchet the rule to error and confirm `make validate` is green — S (traces: R-5)
7. Merge branch to main and verify integration — S

### Floor Check

- [ ] Expected diff is below the calibrated floor threshold
- [ ] The change is limited to one subsystem and maintains no architectural invariant
- [ ] `Files to Modify` substantially overlaps a sibling it is ordered against
- [ ] This is docs-only and its sole consumer is a single sibling

No boxes checked. A grammar change plus a 13-file judged sweep.

## Files to Modify

- `src/aet/docs_lint.py`
- `.agents/doc-rules.yaml`
- `tests/scripts/test_docs_lint.py`
- `skills/aet-work/**`, `skills/aet-setup/**`, `skills/aet-plan/**`,
  `skills/aet-pipeline-plan/SKILL.md`, `skills/aet-validate-scope/SKILL.md`,
  `skills/aet-evolve/SKILL.md`, `AGENTS.md`

## Rejected Alternatives

**Put the rule in `scripts/skills-lint`.** Drafted that way and rejected during
scope validation: ADR-040 records that `skills-lint` checks documentation against
the CLI surface while `aet docs lint` checks governance invariants. A retired data
path is content governance. `skills-lint`'s existing path rule covers
`aet-*/bin/…` invocations, which *are* the CLI surface. The only argument for
`skills-lint` was that the escape hatch already lived there, which dcl-01 removes.

**Hardcode the retired paths in `.agents/doc-rules.yaml`.** Rejected by ADR-074
decision 1: a rules-file copy of a set the code owns is the defect being closed,
and would go stale the first time a fifth path is retired.
