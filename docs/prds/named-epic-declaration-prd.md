# PRD: Named Epic Declaration

## Overview

In `single-pr` mode AET groups tasks behind one integration branch and one PR.
The branch that identifies that group is never declared — it is inferred from a
PRD filename stem (`branch_ref.derive_integration_branch_from_prd`), read from a
project-wide static `integration_branch` config value, or passed per invocation
as `--base`. A group of tasks that is not backed by a PRD therefore has no
durable identity: the operator either edits project config for every epic, or
remembers to repeat `--base` on every run, and the epic's PR name exists nowhere
in the system.

This PRD makes the epic's identity an explicit, durable declaration held in the
queue envelope: a branch name, an optional PR title, and an optional PR body.
The declaration is stamped onto each task record at branch creation, so an epic
that is switched mid-flight cannot retarget work that already integrated
elsewhere. One command opens the epic's PR using the declared name.

Classification: feature. `single-pr` mode behaves as designed; the epic identity
it needs for non-PRD work does not exist.

## Goals

- A set of tasks with no PRD forms one named epic — one branch, one PR — without
  editing project config and without repeating `--base` per invocation.
- The epic's branch name and PR title are declared once and read by every
  command that needs them.
- Switching the active epic cannot retarget, strand, or orphan work that has
  already integrated into a different branch.
- PRD-backed and non-PRD epics resolve their branch through one code path, with
  filename-stem inference demoted to a fallback.
- `pr-per-task` behavior is bit-for-bit unchanged.

## Non-Goals

- Per-plan epic membership. A plan file does not declare which epic it belongs
  to; membership is a function of the active declaration at branch-creation time
  and the stamp it leaves.
- An epic as a persisted first-class entity with its own state machine. ADR-045
  rejected this and the rejection stands: the envelope declaration plus the
  per-task stamp carry the state.
- A branch-name template or naming convention enforcement. The declared value is
  the branch name.
- Interleaving two active epics within a single `aet run`. One epic is active at
  a time; a task bound to another halts rather than running.
- Automatic epic PR opening at the end of a run. Opening the epic PR stays a
  deliberate operator action, per the open question left in
  `non-trunk-integration-workflow-prd.md`.
- Coordination between operators. Consistent with ADR-045's scope boundary, the
  declaration is one operator's local state, pushed with the envelope ref, and
  carries no claim, lease, or lock semantics.

## Requirements

- **R-1** — The queue envelope carries an optional `epic` object with a required
  `branch` and optional `title`, `body_file`, and `set_at`. An absent key means
  no active epic.
- **R-2** — `aet epic set <branch> [--title <text>] [--body-file <path>]` writes
  the declaration. `aet epic show` prints it with provenance. `aet epic clear`
  removes it. All three fail closed on a queue-integrity mismatch, as every
  other envelope writer does.
- **R-3** — The declared value is used verbatim as the branch name. No template,
  prefix, slug transformation, or slash-dependent rule is applied.
- **R-4** — In `single-pr` mode a task's integration branch resolves in this
  order: `--base` → `AET_WORK_BASE_BRANCH` → the task record's stamped
  `integration_branch` → the parent document's declared `branch` → the envelope
  `epic.branch` → the PRD filename stem → config `integration_branch` → trunk.
- **R-5** — A PRD may declare `branch` and `pr_title` in its own frontmatter,
  read by the resolver in R-4. The filename stem remains the fallback for a PRD
  that declares neither.
- **R-6** — In `pr-per-task` mode the epic declaration has no effect on any
  resolved branch, and no task record is stamped.
- **R-7** — At branch creation in `single-pr` mode the resolved integration
  branch is written once to the task record as `integration_branch`, alongside
  `base_commit` in `queue.record_task_meta`, and is never rewritten by a later
  call.
- **R-8** — Closure, merge verification, and derived state read the task
  record's stamped `integration_branch`, not the active declaration.
- **R-9** — Starting or resuming a task whose stamped `integration_branch`
  differs from the branch R-4 would resolve halts in the synchronous foreground
  preflight, before detachment and before any git operation, naming both
  branches, `aet epic set <stamped>` and `aet state reset <task>` as the two
  remedies.
- **R-10** — `aet ship open-epic` runs the pre-merge gate against the
  integration branch, pushes it, and opens exactly one PR targeting the resolved
  trunk with the declared title and body.
- **R-11** — `aet ship open-epic` invoked while the epic already has an open PR
  reports that PR and exits without opening a second one.
- **R-12** — `aet ship open-epic` with no active epic and no branch argument
  fails closed with an error naming `aet epic set`.
- **R-13** — When no title was declared, the epic PR title is the branch name.
  When no body file was declared, the body is generated from the integrated
  commit subjects by the same machinery `aet ship open` already uses.
- **R-14** — `aet setup verify` reports the active epic's branch and title
  alongside `trunk_branch`, `integration_branch`, and `integration_mode`, each
  with provenance.
- **R-15** — The envelope change is additive: readers tolerate an absent `epic`
  key, `ENVELOPE_SCHEMA_VERSION` is not bumped, and no existing envelope key is
  removed or renamed.
- **R-16** — `docs/CONVENTIONS.md` documents the declaration, the R-4 resolution
  order, and the stamping rule; `aet-work` and `aet-ship` document `aet epic`
  and `aet ship open-epic` and stop describing the integration branch as a
  per-run input only.
- **R-17** — An ADR records that an epic's identity is declared rather than
  inferred, amending ADR-045's representation of an epic and resolving the
  multi-epic open question carried by `non-trunk-integration-workflow-prd.md`.
- **R-18** — `aet epic set` refuses a branch that exists neither locally nor on
  `origin`, naming `--create` as the way to declare a new epic. With `--create`
  the declaration is written and no branch is created; the first task to
  integrate creates it.

## User Stories

- As an operator with a dozen unrelated cleanup tasks and no PRD, I want to name
  the branch and PR they ship as once, so that every subsequent `aet run` puts
  them on that branch without a flag (satisfies: R-1, R-2, R-3, R-4).
- As an operator, I want the epic PR to carry a title I wrote rather than a
  filename, so that reviewers in a shared repository see a deliverable rather
  than an artifact name (satisfies: R-2, R-10, R-13).
- As an operator who switched the active epic while tasks from the previous one
  were still open, I want those tasks to close against the branch they actually
  integrated into, so that switching a declaration cannot orphan integrated work
  (satisfies: R-7, R-8).
- As an operator resuming a task from a previous epic, I want the run to stop and
  name the mismatch rather than rebase my work onto the wrong branch, so that the
  one sharp edge of a single active epic is visible instead of silent
  (satisfies: R-9).
- As an operator whose epic branch is ready, I want one command to gate, push,
  and open the PR, so that the declared PR name has a consumer and the epic does
  not ship through hand-typed `gh` (satisfies: R-10, R-11, R-12).
- As an operator of a PRD-backed epic, I want the PRD to name its own branch, so
  that the branch is not the PRD filename with a `-prd` suffix (satisfies: R-5).
- As a solo operator on trunk, I want `pr-per-task` untouched, so that the
  default path carries none of this (satisfies: R-6).
- As an operator upgrading an existing project, I want an envelope written by an
  older version to keep loading, so that the change costs no migration
  (satisfies: R-15).
- As a new adopter, I want the declaration and resolution order documented in one
  place, so that the branch a task lands on is predictable from configuration
  (satisfies: R-14, R-16, R-17).

## Acceptance Criteria

- [ ] `aet epic set feat/x --title "T"` on an existing branch, followed by
      `aet epic show`, prints `feat/x` and `T` with provenance; `aet epic clear`
      then reports no active epic (satisfies: R-1, R-2).
- [ ] `aet epic set feat/typo` on a branch that exists nowhere exits non-zero
      naming `--create`, and writes no declaration; the same command with
      `--create` writes the declaration and leaves `git branch --list feat/typo`
      empty (satisfies: R-18).
- [ ] With `integration_mode: single-pr`, an active epic `feat/x`, and a plan
      referencing no PRD, `aet run-one` creates the task worktree based on
      `feat/x` and integrates into `feat/x` (satisfies: R-3, R-4).
- [ ] A declared branch containing a slash reaches git unaltered: `git
      rev-parse --abbrev-ref` on the integration branch returns exactly the
      declared value (satisfies: R-3).
- [ ] A PRD declaring `branch: feat/y` produces integration branch `feat/y` for
      its tasks even while `feat/x` is the active epic; a PRD declaring nothing
      falls back to the stem only when no epic is active (satisfies: R-4, R-5).
- [ ] With `integration_mode: pr-per-task` and an active epic set, every
      resolved branch and every task record is identical to a run with no epic
      set (satisfies: R-6).
- [ ] After a task's branch is created in `single-pr` mode, its record carries
      `integration_branch`; a second `record_task_meta` call with a different
      branch leaves the field unchanged (satisfies: R-7).
- [ ] `aet epic set feat/other` followed by `aet ship close <task>` verifies
      merge evidence against the task's stamped branch, not `feat/other`
      (satisfies: R-8).
- [ ] Resuming a task stamped `feat/x` while `feat/other` is active exits
      non-zero, prints both branch names, and creates no worktree and no branch
      (satisfies: R-9).
- [ ] `aet ship open-epic` on a ready integration branch leaves `gh pr list`
      showing exactly one PR against the resolved trunk with the declared title;
      a second invocation prints that PR's URL and exits zero without creating
      another (satisfies: R-10, R-11).
- [ ] `aet ship open-epic` with no active epic exits non-zero naming
      `aet epic set` (satisfies: R-12).
- [ ] An epic declared without `--title` opens a PR titled with the branch name
      and a body listing the integrated commit subjects (satisfies: R-13).
- [ ] `aet setup verify` output contains the active epic branch and title with
      provenance (satisfies: R-14).
- [ ] An envelope blob written before this change loads without error and
      reports no active epic; `ENVELOPE_SCHEMA_VERSION` is unchanged
      (satisfies: R-15).
- [ ] `docs/CONVENTIONS.md` states the R-4 order verbatim, and `aet docs lint`
      passes over the changed documents (satisfies: R-16).
- [ ] A new ADR exists, is listed in `docs/adr/README.md`, and names ADR-045 as
      the decision it amends (satisfies: R-17).

## Technical Notes

**Declaration store.** The queue envelope is already a durable, git-refs-backed
blob at `refs/aet/meta/queue` carrying `schema_version` and caller metadata such
as `source_prd`, read and written by `_read_envelope` and `_write_envelope` in
`src/aet/backends/git_refs_backend.py`.
`epic` is one more key in that object, written through the existing
`save(wrapper=...)` path, so it is pushed and fetched with the rest of the
envelope and needs no new storage mechanism. `queue.read_queue` /
`write_queue` already preserve unknown wrapper keys, which is what makes R-15
free.

**Resolver.** R-4 lands in `branch_ref.resolve_integration_branch_for_task`,
which already has the `cli` → `env` → `single-pr`-derivation → `config` →
`trunk` shape and already returns provenance via `BranchRef`. The new steps are
two lookups (task stamp, envelope) and one frontmatter read, and the existing
`derive_integration_branch_from_prd` becomes the last of the derivation steps
rather than the only one. `_task_prd_path` already resolves a task's parent PRD
from either the carried spec frontmatter (`source_prd`) or the plan body, so
R-5 reads frontmatter from a path that machinery already produces.

**Stamp.** `record_task_meta` in `src/aet/queue.py` is the single function that
writes `worktree`, `branch`, and `base_commit` at branch creation, and it
already implements write-once semantics for `base_commit` with the reasoning R-7
needs — a field re-stamped later erases the divergence it exists to prove. The
stamp is the same shape and belongs beside it. Three call sites exist:
`run_batch` and `_record_run_one_in_queue` in `src/aet/cli/orchestrator.py`, and
`transition_task` in `src/aet/cli/next.py`; every
branch-creation path must supply the resolved branch or R-7 is unenforceable.

**Mismatch halt.** R-9 is a precondition check, not a run-time failure, and
ADR-075 decision 1 fixes where it runs: `aet run` and `aet run-one` perform all
preconditions synchronously in the foreground before `_spawn_detached`,
precisely so a failed check cannot leave the operator with an exit code of 0 and
a run that died in the background. The halt belongs beside the existing
worktree base-branch check there. It is an operator-configuration error rather
than a task failure: it must not increment the per-task circuit breaker and must
not be triaged under the ADR-030 failure classes, matching how ADR-045 treats
Integration Failure.

**Glossary boundary.** The Epic entry in `CONTEXT.md` currently defines an epic as
"represented by the integration branch plus the **Source PRD**; not a persisted
entity", and warns against "epic as a queue entity or a new persisted record".
The envelope declaration is persisted, so that warning is sharpened rather than
ignored: what stays forbidden is an epic with its own state, lifecycle,
blockers, or closure event. The declaration is three scalar fields scoped to the
queue, in the same category as the `source_prd` the same envelope already
carries, and it has no id, no state machine, and no tombstone. ADR-045's
rejection of a first-class epic entity survives intact.

**Posture.** The envelope ref is pushed to origin best-effort under shared
posture and suppressed entirely under shadow posture
(`push` in `src/aet/backends/git_refs_backend.py`). `docs/CONVENTIONS.md` documents the
`single-pr` scenario with shadow posture, so in the documented workflow the
declaration stays machine-local; a multi-machine operator on shared posture gets
it replicated with the rest of `refs/aet/*`. Neither case leaks anything the
epic branch itself does not, since ADR-045 already requires that branch to be
pushed on every integration.

**Epic PR.** `aet ship open-epic` reuses `_run_gate`, `_push_branch`,
`_check_release_guard`, `_generate_changelog_entry`, and `_create_pr` from
`cli/ship.py`, which are already parameterized by branch and workspace. The
difference from `cmd_open` is the title/body source (declaration rather than
plan spec) and the absence of a task id. R-11 needs an existing-PR lookup, which
`gh pr list --head <branch>` supplies.

**Ordering decision.** A document that declares its own branch outranks the
active epic, and the active epic outranks filename-stem inference.

The two sources rarely compete. Stem derivation runs only in `single-pr`, inside
`resolve_integration_branch_for_task` in `src/aet/branch_ref.py`; the declaration
is inert in `pr-per-task` (R-6), and an
operator in `single-pr` is working one epic at a time. What is exposed is the
seam between two epics rather than two epics at once: tasks from a finished
PRD-backed epic that were never started, still ready on the board when the next
epic is declared. A task that has run carries a stamp and halts (R-9); only an
unstarted one can resolve to the new branch instead of its stem.

The escapes are declaring `branch` in the PRD (R-5) or `aet epic clear`, and the
resolved branch and its provenance are printed per task at preflight. No further
guard is warranted for a seam this narrow.

**Interaction with ADR-045.** ADR-045 represents an epic as "its integration
branch plus the PRD the plans already reference" and declares multi-epic
concurrency a non-goal. This PRD keeps the first half — no new persisted
entity — and replaces the second: the branch is declared rather than derived
from a PRD, so an epic no longer requires a PRD to exist. One epic remains
active at a time; R-9 is what makes that constraint enforced rather than
assumed.

## Open Questions

- Resolved (R-18): `aet epic set` refuses an unknown branch and names
  `--create`. `--create` records the declaration without creating a branch; the
  first task's worktree creation resolves the base through `resolve_base_ref`,
  which already falls back from `origin/<ref>` to a local ref and tolerates a
  project with no remote.
- Whether `aet ship open-epic` should also close the epic's tasks on success or
  leave that to `aet ship close --target-branch`. Current assumption: leave it,
  because merge evidence for the epic exists only once the PR merges to trunk.
- Whether the active declaration should be surfaced in `aet status` and
  `aet panel`, or only in `aet epic show` and `aet setup verify`. Deferred: R-14
  covers the diagnostic path, and the run banner covers the per-task path.

---

*Stage: scope-validated*
*Next step: run `aet-work` (single-plan or multi-task queue)*
