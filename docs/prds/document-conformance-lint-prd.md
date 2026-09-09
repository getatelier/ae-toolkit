# PRD: Document-Conformance Lint

## Overview

Documents in this repository carry facts that code owns: retired data paths, ADR
relations, and file/line anchors into source. Nothing validates the copy, so each
one decays silently and is discovered only when a person happens to open the file
for an unrelated reason.

The mechanism to fix this already exists twice over, and both instances are
already gated by `make validate`:

- `scripts/skills-lint` validates documented `aet` invocations against the **real
  tree** — it imports the Typer app and builds command grammars from it, so the
  source of truth is the code and the lint cannot itself go stale. It carries a
  span extractor, an escape hatch (`<!-- aet-lint: off -->` … `on`), and a
  severity switch (`--legacy=warn|error`).
- `aet docs lint` (`src/aet/docs_lint.py`) is a declarative rule engine reading
  `.agents/doc-rules.yaml`, with ADR-aware helpers (`_load_adr_frontmatter`,
  `_adr_id_from_path`, `_normalize_adr_id`) and one corpus-wide rule type,
  `unique_live_subject`.

This work adds the missing rules to those two engines. It builds no new tool.

### The gap is narrower and sharper than "there is no lint"

`unique_live_subject` — the rule ADR-056 added specifically to make the ADR corpus
self-checking — contains this:

```python
if data is None:
    # ADRs without frontmatter are ignored.
    continue
```

**39 of 72 ADRs carry no frontmatter, so the rule that guards the corpus skips
more than half of it by explicit instruction.** And because the rule is keyed on
`subject`, the two records numbered 072 (`a-proxy-is-not-evidence` and
`partitioned-plan-directory-layout`) declared *different* subjects and passed it
cleanly — nothing keys on the ADR number at all. Meanwhile `aet context`'s digest
resolver **does** detect a dangling `supersedes:` and printed
`CONFLICT supervision-uniformity: dangling supersedes: 53` on every session start
for weeks. It prints; it does not gate.

So the toolkit has two ADR readers with different strictness, and the strict one
only warns while the gating one is half-blind.

### Why this is worth doing as one piece of work

On 2026-08-30 two instances of this class were fixed by hand in `39d84e6e`. In the
same afternoon, in the same files, the class produced two fresh instances: the
authoring PRD cited an ADR number that record never got, in three places, and
carried eleven markdownlint errors because nothing had validated it since those
hooks landed. Both were found only because a person opened the file for an
unrelated reason.

Two items fixed, two instances created, same day. Sweeping is not a fix for this
class; a validator is.

## Decision Record

Two decisions must be recorded before intake, and both are forced by existing ADRs
rather than invented here:

1. **ADR-056 states the rule grammar is a public contract: "adding a new rule type
   requires a new ADR."** This work adds two (`adr_corpus_integrity`,
   `code_anchor_resolves`).
2. **ADR-056 decision 1 makes `subject:` and `supersedes:` optional** ("Every ADR
   *may* declare"). Refusing an ADR that carries no `subject:` contests that
   directly, and is the difference between a corpus that is checked and one that
   is half-checked.

The ADR authored alongside this PRD extends ADR-040 and ADR-056 and settles both.

## Goals

1. **A fact the code owns is never asserted in prose without a check.** Three
   classes — retired data paths, ADR relations, and code anchors — join the
   command tokens `skills-lint` already covers.
2. **The source of truth stays in code.** Rules read `AET_RETIRED_IGNORED_PATHS`
   and the ADR corpus itself, never a copy maintained beside them.
3. **The corpus becomes fully checked, not half-checked.** The
   frontmatter-less-ADR skip is removed rather than worked around.
4. **The existing sweeps land behind the rules that keep them landed**, so this is
   the last time each is done by hand.

## Non-Goals

- **A new lint tool or binary.** Both engines exist and are gated; this extends
  them. A third entry point would be a fourth thing to keep in sync.
- **Moving CLI flag semantics into `--help`.** That is the same root cause with a
  different fix and its own byte budget; it stays in the backlog as
  `enrich-cli-help-at-the-source`.
- **Markdown style.** `markdownlint-cli2` already runs in pre-commit. The eleven
  errors found on 2026-08-30 are evidence of coverage gaps in the *hook's* file
  set, not a rule this work owns.
- **Rewriting history.** Archived plans under `docs/plans/archive/` record what a
  task said at the time and are excluded from every rule here.

## Requirements

### R-1: The ADR corpus is checked as a whole

`aet docs lint` gains an `adr_corpus_integrity` rule type targeting a directory of
ADR files. It fails on: two records sharing a number; a `supersedes:` or `relates:`
entry naming a record that does not exist; a `relates:` entry naming a record that
another ADR supersedes; and — per the decision record — an ADR carrying no
`subject:`. `000-template.md` and `README.md` remain excluded per ADR-056
decision 4.

### R-2: Retired data paths are refused in prose

`aet docs lint` gains a `retired_path_absent` rule type refusing references to
paths the toolkit has retired, reading the set from `AET_RETIRED_IGNORED_PATHS` in
`src/aet/worktree.py` by import so the lint cannot diverge from the code that
declares them. It honours R-4's escape, which is what the migration references
legitimately need.

**Placed by ADR-040's boundary, not by convenience.** This rule was first drafted
into `scripts/skills-lint` because that is where the escape hatch already lives.
Scope validation rejected that: ADR-040 records that `skills-lint` checks
documentation against the **CLI surface** while `aet docs lint` checks
**governance invariants**. A retired data path is content governance, not a
command. `skills-lint`'s existing path rule covers `aet-*/bin/…` *invocations*,
which is the CLI surface. `scripts/skills-lint` is therefore untouched by this
work, and all three rules land in one engine with one escape mechanism.

### R-3: Code anchors resolve to a symbol, not a line

`aet docs lint` gains a `code_anchor_resolves` rule type that refuses a `path:NN`
line anchor and requires a symbol name that resolves in the named file. Line
numbers are unmaintainable by construction: the file moves and the prose does not.

### R-4: A deliberate historical citation can opt out

`docs_lint` has no escape mechanism today, and both R-2 and R-3 need one: the
migration references name the retired path deliberately, and a PRD may legitimately
cite the code as it stood when a decision was made. The escape is explicit and
greppable and reuses the marker `skills-lint` spells
(`<!-- aet-lint: off -->` … `on`), so there is one convention in the repository
rather than two.

**R-4 is a prerequisite for R-2 and R-3, not a peer.** Landing either rule before
the escape exists would refuse legitimate prose with no way to say so.

### R-5: New rules ship at warning severity, then ratchet

Each new rule lands non-blocking, its sweep lands, and only then does it become an
error in `make validate`. `skills-lint`'s `--legacy=warn|error` switch is the
precedent and the shape to copy. A rule that fails the build on the day it lands
gets switched off rather than obeyed.

### R-6: The standing corpus is swept to zero

Three sweeps, each behind its own rule: ~50 retired-path references across 13 files
in six skills; 132 line anchors across 20 PRDs and 10 other documents; and
`subject:` frontmatter for the 39 ADRs that carry none. Each sweep needs per-file
judgment — the migration references name the old path deliberately, and ADR-053's
supersession of ADR-031 is partial and prose-only, so declaring it as data would
create a *new* dangling edge.

## User Stories

**As a maintainer reading a skill,** I want a documented path to be one the code
still writes, so I do not follow a reference to a file the backend abandoned.

**As an agent resolving an ADR citation,** I want "ADR-072" to identify exactly one
record, so a decision I am asked to conform to is the decision that was made.

**As a reviewer running `aet-sync-docs`,** I want a PRD's code anchors to resolve,
so a sync run reports real divergence rather than four anchors landing on unrelated
code.

**As the person who fixes one of these by hand,** I want the fix to be the last
one, so the class does not produce a fresh instance the same afternoon.

## Acceptance Criteria

- `aet docs lint` fails on a corpus containing two records with the same number, a
  dangling relation, a relation to a superseded record, or an ADR with no
  `subject:`. Each is asserted by **constructing the violating corpus in a
  fixture** — ADR-072 requires conformance be shown by the divergent case, and this
  work exists because the agreeing case passed for months.
- `scripts/skills-lint` fails on a new reference to `.agents/work-queue.json` in a
  linted document, and passes on one inside an `aet-lint: off` span.
- `scripts/skills-lint` picks up a path added to `AET_RETIRED_IGNORED_PATHS`
  without any edit to the lint, proven by a test that adds one.
- `aet docs lint` fails on a `path.py:123` anchor in a targeted document and on a
  symbol name that does not resolve; it passes on one that does.
- `make validate` is green with every rule at error severity and every sweep landed.
- `aet context` prints no `CONFLICT` line for the ADR corpus.

## Technical Notes

**Code anchors, by symbol.** This PRD deliberately carries none of the `path:NN`
anchors R-3 refuses. The relevant symbols: `unique_live_subject` and
`_load_adr_frontmatter` in `src/aet/docs_lint.py`; `LEGACY_NAMES`,
`LEGACY_PATH_RE`, `extract_spans` and `lint_file` in `scripts/skills-lint`;
`AET_RETIRED_IGNORED_PATHS` in `src/aet/worktree.py`; `resolve_rules` and
`_conflict_rule` in `src/aet/context_digest.py`.

**Two readers, one corpus.** `context_digest.resolve_rules` already computes
dangling `supersedes:` and renders it as a CONFLICT marker. R-1 should consume that
resolver rather than reimplement supersession logic beside it — a second
implementation of the same rule is the defect class this work is about (see
`content/backlog/README.md` RC-4). Whether `docs_lint` imports `context_digest` or
both delegate to a shared resolver is an implementation choice for the plan.

**`relates:` is currently read by nothing.** `context_digest` reads `subject` and
`supersedes` only. R-1 is the first consumer, which means the key's semantics are
being fixed by this work rather than merely enforced.

**The escape hatch is not symmetric.** `skills-lint` extracts code spans and
tracks `off`/`on` markers per line in `extract_spans`; `docs_lint` reads whole
files and sections. R-4 cannot copy the implementation, only the marker's spelling.

## Resolved During Scope Validation

- **R-2's engine.** Moved from `scripts/skills-lint` to `aet docs lint`, per
  ADR-040's recorded boundary. See R-2.
- **R-3's target set.** The rule takes a `target` like every other rule type, so
  the corpus it covers is **data in `.agents/doc-rules.yaml`, not code**. It lands
  pointed at `docs/prds/` — the 20 files and 132 anchors `aet-sync-docs` actually
  consumes — and widening to ADRs, `CONTEXT.md` and `CONVENTIONS.md` later is a
  rules-file edit plus a sweep, with no new code. This is the whole point of a
  declarative engine and it dissolves the question rather than answering it.
- **Symbol resolution strictness.** A Python anchor must resolve to a **definition**,
  found with an `ast` walk over the named file: a grep would accept a symbol
  surviving only in a comment or a docstring, which is precisely the half-dead
  state that makes a stale anchor misleading rather than absent. Non-Python targets
  fall back to occurrence matching, and the rule says which mode it used.
- **Missing vs malformed relation.** Both are errors, with distinct messages: a
  relation naming a record that has never existed is a typo, and one naming a
  record that has been superseded is drift. Collapsing them into one message would
  lose the distinction that tells an author which fix applies.

## Open Questions

- Does `unique_live_subject` keep its "ADRs without frontmatter are ignored" skip
  once R-1 refuses that state outright? Leaving it is harmless but leaves a
  misleading comment in the tree; removing it changes a rule this work does not own.
  The plan should decide explicitly rather than leave both behaviours standing.

## Divergence Summary — dcl-02

*Recorded: 2026-09-09 — Branch: dcl-02-adr-corpus-integrity-rule*

The `dcl-02` implementation slice (R-1, R-5) matches the planned behavior.

### Changed from plan

- **Task 4 / Open Questions:** Retained `unique_live_subject`'s frontmatter skip and updated the comment to clarify separation of concerns: `adr_corpus_integrity` enforces frontmatter presence and corpus completeness, while `unique_live_subject` evaluates uniqueness among declared subjects.

### Added (unplanned)

- **`src/aet/cli/docs.py` & `docs/CLI.md`:** Added `--severity` option to `aet docs lint` CLI to allow filtering and enforcing rules at `error` (default) or `warning` severity, supporting warning-level rule evaluation in CLI workflows.

### Deferred

- **Task 7 (Merge to main):** Merging to main and integration verification deferred to `aet-ship`.

---

*Stage: synced*
*Next step: run `aet-ship`*
