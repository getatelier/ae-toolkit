---
blocked_by:
  - ned-01-declare-the-epic-in-the-envelope
docs_sync: required
id: ned-03-open-the-epic-pull-request
pipeline: standard
security_review: required
size: M
work_class: normal
---

# Plan: Open the epic pull request

## Context

PRD: `docs/prds/named-epic-declaration-prd.md` (R-10 – R-13).

`single-pr` mode integrates tasks into an epic branch and pushes it on every
integration, but nothing opens the epic's PR. The documented flow
(`skills/aet-ship/SKILL.md:56-71`) goes from `aet run --base <branch>` straight
to `aet ship merge <branch> --branch main`, so the PR is either created by hand
with `gh` or skipped in favour of a direct merge. `ned-01` gives the epic a
declared title and body with no consumer.

`cmd_open` (`src/aet/cli/ship.py:954`) already composes the pieces this needs —
`_run_gate`, `_check_release_guard`, `_generate_changelog_entry`,
`_push_branch`, and `_create_pr` (`:906`) — each parameterised by branch and
workspace. It differs in two ways: it derives its title from a task's plan spec
(`:990-991`) and it requires a task id. The epic command supplies the title from
the declaration and operates on a branch.

`non-trunk-integration-workflow-prd.md:316-318` left the epic PR as a deliberate
human action rather than something the last task triggers. This plan keeps that:
it adds a command, not a hook.

Prior decisions this plan operates under:

- **ADR-029** — autonomous merge is a fail-closed gate, and ADR-045 moves that
  gate up to the epic level, evaluated once when the epic PR merges. This plan
  opens that PR; it does not merge it and does not close the epic's tasks.
- **ADR-027** — unpushed work is work that can be lost. The push happens before
  the PR is created, and a gate failure leaves the branch pushed.

## Intake Triage

- [x] Confirmed this is a **feature or enhancement**, not a reproducible defect
- [x] If a reproducible defect was described, redirected to `aet-bug-report`

## Task List

1. Add `aet ship open-epic [<branch>]` resolving the branch from the argument or
   the active declaration, failing closed with an error naming `aet epic set`
   when neither supplies one — S (traces: R-12)
2. Run the pre-merge gate and the release guard against the integration branch
   and push it, reusing `_run_gate`, `_check_release_guard`, and `_push_branch`
   unchanged — M (traces: R-10)
3. Compose the PR title and body — declared title, or the branch name when none
   was declared; declared body file, or a body generated from the integrated
   commit subjects via `_generate_changelog_entry` — S (traces: R-13)
4. Create the PR against the resolved trunk with `_create_pr`, and record the
   `cut` ledger event with the epic branch as its subject — S (traces: R-10)
5. Look up an existing PR for the branch with `gh pr list --head <branch>`
   before creating one; when found, print its URL and exit zero — S
   (traces: R-11)
6. Merge branch to main and verify integration — S

### Floor Check

- [ ] Expected diff is below the calibrated floor threshold (≤ 50 headline lines)
- [ ] The change is limited to one subsystem and maintains no architectural invariant
- [ ] `Files to Modify` substantially overlaps a sibling this plan is linearly ordered against
- [ ] This is docs-only and its sole consumer is a single sibling

No boxes. The plan shares no files with `ned-02` and delivers the only consumer
of the declared PR title.

## Rejected Alternatives

- **Open the epic PR automatically when the last task integrates** — rejected:
  `non-trunk-integration-workflow-prd.md` declared the epic PR a deliberate
  human action, and "last task" is not knowable from a queue that accepts
  additions mid-epic.
- **Extend `cmd_open` with an `--epic` flag** — rejected: `cmd_open` is
  organised around a task id it resolves, gates, and reports against
  (`_resolve_ship_task`, `src/aet/cli/ship.py:956`); threading an epic through
  it would make every one of those steps conditional.
- **Close the epic's tasks on success** — rejected: merge evidence for the epic
  exists only once its PR merges to trunk, so closing at PR-open time would
  assert a fact that is not yet true. Closure stays `aet ship close
  --target-branch`.
- **Reopen or update the existing PR's title and body on a second invocation** —
  rejected: it would overwrite edits a reviewer made on the forge. Reporting the
  existing PR is enough.

## Files to Modify

- `src/aet/cli/ship.py`
- `tests/ship/test_open_epic.py`
- `tests/cli/test_ship_verify.py`

## Validation Steps

- [ ] Lint passes
- [ ] Tests pass
- [ ] R-trace coverage: R-10 (tasks 2, 4), R-11 (task 5), R-12 (task 1), R-13
      (task 3)
- [ ] New source files: none. `cmd_open_epic` lands in `src/aet/cli/ship.py`
      beside `cmd_open` and is covered by a new `tests/ship/test_open_epic.py`
- [ ] Unit test: with no active epic and no argument, the command exits non-zero
      and names `aet epic set`
      (`tests/ship/test_open_epic.py::test_no_active_epic_fails_closed`)
- [ ] Unit test: an epic declared without a title produces a PR title equal to
      the branch name, and a body listing the integrated commit subjects
      (`::test_title_defaults_to_branch_name_and_body_to_commit_subjects`)
- [ ] Unit test: a declared title and body file reach `gh pr create` verbatim
      (`::test_declared_title_and_body_are_used`)
- [ ] Integration test: a successful run leaves exactly one PR against the
      resolved trunk, and a second invocation prints that PR's URL and exits
      zero without a second `gh pr create`
      (`::test_second_invocation_reports_the_existing_pr`)
- [ ] Integration test: a failing gate exits non-zero and creates no PR
      (`::test_gate_failure_creates_no_pr`)
- [ ] Merge verified: `git merge-base --is-ancestor HEAD origin/main`

## Rollback Plan

Revert the commit. The command disappears; epics ship through `aet ship merge`
or a hand-written `gh pr create` as they do today. PRs opened while it was live
are ordinary PRs and are unaffected.

## Pipeline

`standard`. The change pushes to `origin` and creates pull requests from
operator-supplied content, which is the documented risk override regardless of
size.
