---
blocked_by:
docs_sync: required
id: ned-01-declare-the-epic-in-the-envelope
pipeline: standard
security_review: required
size: M
work_class: normal
---

# Plan: Declare the epic in the queue envelope

## Context

PRD: `docs/prds/named-epic-declaration-prd.md` (R-1 – R-6, R-14, R-15).

In `single-pr` mode `resolve_integration_branch_for_task`
(`src/aet/branch_ref.py:146`) derives a task's integration branch from the stem
of the PRD the task references, via `derive_integration_branch_from_prd`
(`:81`). A task with no PRD falls through to config `integration_branch` and
then to trunk, so a group of tasks that is not backed by a PRD integrates
straight into trunk unless the operator sets a project-wide config value or
repeats `--base` on every invocation. Neither carries a PR title.

The queue envelope already holds caller metadata such as `source_prd` in a
git-refs-backed blob at `refs/aet/meta/queue`
(`src/aet/backends/git_refs_backend.py:36`), written through `save(wrapper=...)`
and read by `_read_envelope` (`:571`). `queue.read_queue` preserves wrapper keys
it does not recognise (`src/aet/queue.py:420`), which is what makes an added key
backward-compatible without a schema bump.

This plan makes the epic a declaration in that envelope and rewrites the
resolution chain to read it, with filename-stem derivation demoted to a
fallback. It does not stamp the resolved branch onto task records — that is
`ned-02`, and until it lands the chain's stamp step is absent rather than
wrong.

Prior decisions this plan operates under:

- **ADR-045** — an epic is represented by its integration branch plus the PRD
  the plans reference, and `pr-per-task` is the degenerate case running the same
  code path. This plan replaces the PRD half of that representation and
  preserves the degenerate-case property.
- **ADR-044** — the base branch is configured, not assumed. The new step is one
  more layer in that resolution chain, reported with provenance like the rest.
- **ADR-058** — migration populates before it removes. The envelope key is
  additive and no existing key changes meaning.

## Intake Triage

- [x] Confirmed this is a **feature or enhancement**, not a reproducible defect
- [x] If a reproducible defect was described, redirected to `aet-bug-report`

## Task List

1. Add envelope accessors for the epic declaration — read returning `None` when
   the key is absent, write merging through the existing `save(wrapper=...)`
   path — validating that `branch` is present and that `body_file` resolves to
   an existing file — S (traces: R-1, R-15)
2. Add `src/aet/cli/epic.py` with `set <branch> [--title] [--body-file]
   [--create]`, `show`, and `clear`, registered on the top-level app in
   `src/aet/cli/main.py` beside the other noun-scoped groups; `show` prints
   branch, title, body file, and `set_at`, or reports no active epic — M
   (traces: R-2)
3. Refuse `set` when the branch resolves neither locally nor on `origin`,
   naming `--create`; with `--create`, write the declaration and create no
   branch, leaving `resolve_base_ref` to resolve it at first integration — S
   (traces: R-18)
4. Rewrite `resolve_integration_branch_for_task` to the full ordering — cli,
   env, task record stamp, parent document declared branch, envelope epic, PRD
   stem, config, trunk — returning a distinct `BranchRef.provenance` for each
   new step and reading the stamp field defensively so the chain is correct
   before `ned-02` writes it — M (traces: R-3, R-4, R-6)
5. Read `branch` and `pr_title` from the parent document's frontmatter in
   `_task_prd_path`'s caller, using the path that function already resolves, so
   a PRD that declares a branch outranks its own filename stem — S (traces: R-5)
6. Report the active epic's branch and title with provenance in `aet setup
   verify`, beside the existing `integration_mode`, `integration_branch`, and
   `trunk` lines (`src/aet/cli/setup.py:401-407`), reading the envelope through
   the backend and degrading to a warning line when it cannot be read, since
   `verify` currently depends on config and git alone — S (traces: R-14)
7. Merge branch to main and verify integration — S

### Floor Check

- [ ] Expected diff is below the calibrated floor threshold (≤ 50 headline lines)
- [ ] The change is limited to one subsystem and maintains no architectural invariant
- [ ] `Files to Modify` substantially overlaps a sibling this plan is linearly ordered against
- [ ] This is docs-only and its sole consumer is a single sibling

No boxes. The plan owns the whole resolution chain in one pass; splitting the
envelope step from the document step would have the second task reorder what the
first wrote.

## Rejected Alternatives

- **A per-plan `epic:` frontmatter key** — rejected: repeats the branch name
  across every plan in the epic and leaves the PR title with nowhere to live.
  Considered and declined during planning in favour of a single declaration.
- **An `docs/epics/<slug>.md` document that plans point at** — rejected: the
  cleanest generalisation of today's PRD-as-epic mechanism, but it requires
  writing a document before a group of cleanup tasks can share a branch, which
  is the cost this feature exists to remove.
- **A `epic_branch_template` config key rendering a bare slug** — rejected: adds
  an indirection between the declared value and the pushed branch for a naming
  convention AET does not own.
- **A new ref beside `refs/aet/meta/queue` for the declaration** — rejected: the
  envelope already carries queue-scoped caller metadata, is already pushed and
  fetched, and already has a schema version.
- **Making the envelope epic outrank a document's declared branch** — rejected:
  it would make a declared PRD branch unreachable whenever any epic is active,
  collapsing the two concurrent-epic cases this ordering keeps separate.

## Files to Modify

- `src/aet/branch_ref.py`
- `src/aet/backends/git_refs_backend.py`
- `src/aet/cli/epic.py`
- `src/aet/cli/main.py`
- `src/aet/cli/setup.py`
- `tests/test_branch_ref.py`
- `tests/cli/test_epic.py`
- `tests/orchestrator/test_prd_derived_integration_branch.py`
- `tests/orchestrator/test_pr_per_task_unchanged.py`
- `tests/backends/test_backends.py`
- `tests/setup/test_setup_verify.py`

## Validation Steps

- [ ] Lint passes
- [ ] Tests pass
- [ ] R-trace coverage: R-1 (task 1), R-2 (task 2), R-3 (task 4), R-4 (tasks 4,
      5), R-5 (task 5), R-6 (task 4), R-14 (task 6), R-15 (task 1), R-18
      (task 3)
- [ ] New source files: `src/aet/cli/epic.py`, covered by a new
      `tests/cli/test_epic.py` with
      `::test_set_then_show_reports_branch_and_title`,
      `::test_clear_reports_no_active_epic`, and
      `::test_set_rejects_a_missing_body_file`
- [ ] Unit test: `set` on an unknown branch exits non-zero naming `--create` and
      writes no declaration; with `--create` it writes the declaration and
      creates no branch
      (`tests/cli/test_epic.py::test_unknown_branch_is_refused_without_create`,
      `::test_create_declares_without_creating_a_branch`)
- [ ] Unit test: each step of the R-4 chain wins over the steps below it, one
      case per step, asserting both `ref` and `provenance`
      (`tests/test_branch_ref.py::test_resolution_order_for_single_pr`)
- [ ] Unit test: a declared branch containing a slash resolves unaltered
      (`tests/test_branch_ref.py::test_declared_branch_is_used_verbatim`)
- [ ] Unit test: a PRD declaring `branch` outranks its filename stem, and a PRD
      declaring nothing still derives the stem
      (`tests/orchestrator/test_prd_derived_integration_branch.py::test_declared_prd_branch_outranks_stem`)
- [ ] Unit test: with `integration_mode: pr-per-task` and an epic set, every
      resolved branch matches the no-epic result
      (`tests/orchestrator/test_pr_per_task_unchanged.py::test_epic_declaration_is_inert_in_pr_per_task`)
- [ ] Integration test: an envelope blob written without the `epic` key loads
      and reports no active epic, and `ENVELOPE_SCHEMA_VERSION` is unchanged
      (`tests/backends/test_backends.py::test_envelope_without_epic_key_loads`)
- [ ] Integration test: `aet setup verify` output names the active epic branch
      and title with provenance
      (`tests/setup/test_setup_verify.py::test_verify_reports_active_epic`)
- [ ] Merge verified: `git merge-base --is-ancestor HEAD origin/main`

## Rollback Plan

Revert the commit. The `epic` envelope key becomes an unread extra field that
`read_queue` continues to preserve, and resolution returns to PRD-stem
derivation. No task record is written by this plan, so nothing outlives the
revert.

## Pipeline

`standard`. The change writes persisted state in `refs/aet/meta/queue` and
alters the branch every `single-pr` task is cut on, which is the documented risk
override regardless of size.
