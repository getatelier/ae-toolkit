# PRD: Non-Trunk Integration Workflow

## Overview

AET assumes the branch it builds on is named `main`, and that a task is done
when its commit reaches trunk. Neither assumption was ever decided — both are
defaults that spread by copy. Together they make AET unusable in a repository
whose plans live on a feature branch, which is the normal shape of a shared team
repository.

The failure was found by running AET in a shared repository whose branching
policy integrates `feat/*` into `dev`. Every task failed with `Plan not found in
worktree` and, under the default `--on-failure triage`, requeued in a loop —
spawning agent sessions that cost money and could not make progress. Working
around it surfaced a worktree-hijack bug that moved the operator's own checkout
onto a task branch, and recovering from *that* surfaced a queue that could
neither be healed nor regenerated.

This PRD covers the two incidents recorded in
`docs/bugs/2026-07-22-orchestrator-base-branch-hardcoded.md` and
`docs/bugs/2026-07-22-queue-reset-dead-end.md`, and implements ADR-044 and
ADR-045.

**Intake classification.** This intake is mixed, and the split is deliberate.
Four items are reproducible defects: the worktree hijack, the self-tripped
dirty-tree hard-stop, the `init-queue` fail-closed rebuild, and the `state heal`
gap. They are planned here rather than under `aet-bug-report` because each is
the *same edit* as the generalization it sits inside — routing them separately
would produce two competing designs for one function signature. Their diagnoses
are not re-derived here; they are recorded in the two bug reports, both of which
were re-verified against this codebase during planning and carry a verification
section noting three corrections and two additional defects found. The remaining
scope — the epic/integration layer — is a feature and is planned as one.

**Scenario vocabulary**, used throughout and in both ADRs:

- **Scenario A** — solo, trunk-based. Each plan is independently shippable; many
  small PRs land on trunk. Today's behavior. Must not regress.
- **Scenario B** — one engineer in a shared repository delivering one ticket.
  The plans decompose one deliverable; the host policy requires one feature
  branch and one PR.

## Goals

- **G1** — AET runs in a repository whose trunk is not named `main`, with no
  configuration.
- **G2** — AET runs against plans that live on a feature branch rather than
  trunk.
- **G3** — AET never moves the operator's own working tree.
- **G4** — A wedged queue is always recoverable; deleting it is a supported
  reset, not a one-way door.
- **G5** — In a shared repository, a multi-plan ticket produces exactly one
  branch and one PR.
- **G6** — Scenario A is unchanged, and is the same code path as Scenario B
  rather than a preserved legacy branch.

## Non-Goals

- **Coordination between people.** AET remains one plan, one operator. The
  integration lock (R-14) orders one operator's own concurrent pipelines and is
  local and advisory. No claim-checks, no leases visible to other operators, no
  shared queue. This is a standing boundary, not a phase-1 simplification.
- Teaching AET any specific host branching policy. AET reads configuration; it
  does not model GitFlow, trunk-based development, or any named methodology.
- Multi-epic concurrency. One integration branch is active per queue at a time.
- Changing the forge integration for `pr-per-task`. That mode's serialization
  stays the forge's job (ADR-045 decision 5).
- Migrating existing projects. Detection plus the `main` fallback means existing
  repositories need no action.
- Making the epic a persisted entity. Rejected in ADR-045; the integration
  branch plus the referenced PRD carry the state.

## Requirements

### Branch resolution (ADR-044)

- **R-1** — `trunk_branch` resolves as: config → `git symbolic-ref
  refs/remotes/origin/HEAD` → `main`. No code path names a branch literally.
- **R-2** — `integration_branch` resolves as: `--base` flag →
  `AET_WORK_BASE_BRANCH` env → config `integration_branch` → `trunk_branch`. It
  is a per-run input, not primarily project configuration, because a project has
  one trunk but many epics.
- **R-3** — `trunk_branch` and `integration_mode` resolve through the
  external-first chain already implemented in `src/aet/backends/factory.py`
  (`AET_WORK_CONFIG` → `~/.aet/{slug}/config.json` → `.agents/aet-work.json` →
  defaults). No second config reader is introduced.
- **R-4** — Every consumer of a base or trunk ref reads the resolver:
  `create_worktree` (`src/aet/worktree.py`), `remove_worktree`,
  `check_main_hygiene`, `_session_diff_stats`
  (`src/aet/cli/orchestrator.py`), and `is_ancestor_of_target`
  (`src/aet/cli/aet_state.py`). `check_main_hygiene` is renamed to `check_base_hygiene`
  and `is_ancestor_of_main` is renamed to `is_ancestor_of_target` to name the check rather than the branch.
  Per the project's no-backward-compat rule these are renames, not aliases. In
  `single-pr` mode (ADR-045 decision 6) the hygiene and telemetry consumers read
  the integration branch rather than the trunk, so a run is gated on the epic's
  branch being clean and in sync — not on trunk, which the operator may not be
  able to push to.
- **R-5** — `aet setup verify` reports the resolved trunk branch and how it was
  derived (config, detected, or fallback), so a stale or unset
  `refs/remotes/origin/HEAD` is visible rather than silently resolving to `main`.

### Failing safely (ADR-044)

- **R-6** — When the resolved base does not contain a task's plan file, the
  orchestrator reports the resolved base, the expected plan path, and the
  override mechanism, and does **not** requeue the task. A misconfiguration must
  halt, not churn.
- **R-7** — No AET code path runs a git command in `repo_root` that changes
  `HEAD` there. Worktree refresh operates inside the task worktree or moves refs
  without a checkout.
- **R-8** — The dirty-tree hygiene gate ignores every path AET itself writes,
  derived from one shared constant rather than restated per call site. The
  constant covers at minimum the four queue sidecars, `.agents/runs/`, and
  `.worktrees/` (which `create_worktree` writes inside `repo_root`,
  `src/aet/worktree.py`); the plan audits every in-repo write path against it.
- **R-9** — `aet setup` **writes** the ignore entries to `.gitignore` as code,
  from the same shared constant as R-8 so the gate and the setup writer can
  never disagree. The prose lists in `skills/aet-setup/SKILL.md`,
  `checklist.md`, and `references/README.md` are corrected and made
  consistent with what the code writes.

### Queue recoverability (ADR-044)

- **R-10** — `init-queue` scopes validation to the plans being included.
  Invalid unrelated plans are warned and skipped. The queue file is never left
  unwritten because of a plan the caller did not ask to include. This requires
  moving validation after the `is_settled_plan` (`src/aet/plan_parser.py`) and
  `is_sprint_member` skips. Whether `queue sync` gets the same treatment is an open question
  below.
- **R-11** — `aet state heal` detects and repairs a task whose stored state is
  `in_progress` or `awaiting_merge` and whose recorded branch does not exist,
  resetting it to its git-derived state. This is the pair
  (`derived ∈ {ready, blocked}`, `stored == in_progress`) that matches no rule
  in `cmd_heal` today. `state audit` reports the same pair — it shares
  `derive_status`, so detection is free; the requirement is that the report
  names it.
- **R-12** — Heal and reset clear stale `branch` and `worktree` fields. No code
  path in `aet_state.py` clears runtime fields today.
- **R-13** — A task-level reset primitive un-starts a task: recompute state from
  git and blockers, set `ready`/`blocked`, clear runtime fields.

### Epic integration (ADR-045)

- **R-14** — `integration_mode` selects `pr-per-task` (default) or `single-pr`.
  Scenario A is the configuration `integration_mode: pr-per-task` with
  `integration_branch == trunk_branch`, running the same code path — not a
  special case beside it.
- **R-15** — In `single-pr` mode no per-task branch reaches `origin`. Each is
  created, integrated, and deleted locally. Only the integration branch is
  pushed and only it gets a PR.
- **R-16** — In `single-pr` mode a task completes by squash-merging into the
  integration branch locally, and ADR-011 dependency-unblocking fires on that
  event rather than on trunk arrival.
- **R-17** — In `single-pr` mode a task worktree is cut from the integration
  branch's live tip at the time the task starts, after its blockers have
  integrated — not from a snapshot taken when the run began.
- **R-18** — In `single-pr` mode the integration step (rebase onto current tip →
  re-validate → squash-merge) is serialized behind a local advisory lock while
  implementation stays concurrent up to `--max-jobs`. Re-validation after rebase
  is mandatory: a task that passed against an older tip has not been shown to
  pass against the tip it lands on.
- **R-19** — A failed integration (rebase conflict or post-rebase validation
  failure) is a distinct failure category from task failure — an
  engine-level outcome, not a member of the ADR-030 agent-session failure-class
  menu — and is not triaged as one. The task passed; the combination did not.
- **R-20** — In `single-pr` mode the integration branch is pushed on every
  integration, so unpushed work does not accumulate locally. Its PR still opens
  once. This carries ADR-027's durability property into the mode.
- **R-21** — ADR-029's trunk merge-verification runs once per epic, when the
  integration branch's PR merges, and retains its fail-closed and no-self-merge
  properties.
- **R-22** — In `single-pr` mode per-task gate evidence (`qa` and `review`
  always; `cso` unless `security_review: skipped`; `sync-docs` unless
  `docs_sync: skipped`) is enforced at integration time, before the
  squash-merge lands. The pre-push hook cannot carry this check — per-task
  branches never reach `origin` (R-15), so it never fires — and without a
  replacement `single-pr` would silently drop the gate-evidence requirement
  that `pr-per-task` enforces on every push. The serialized integration step
  (R-18) verifies the recorded `pass` verdicts before integrating.

### Documentation

- **R-23** — The trunk-based assumption is documented as explicit configuration
  rather than left implicit: what `trunk_branch`, `integration_branch`, and
  `integration_mode` mean, their resolution order, and a worked Scenario B
  setup.

## User Stories

- As an engineer in a repository whose trunk is `dev`, I want AET to work
  without patching it, so that adopting the toolkit does not start with a fork
  (satisfies: R-1, R-4).
- As an engineer whose plans live on a feature branch, I want tasks cut from
  that branch, so that the AFK loop can find the plans it was given
  (satisfies: R-2, R-3).
- As an operator, I want a misconfigured base to stop the run with an actionable
  message, so that I do not pay for a requeue loop that cannot make progress
  (satisfies: R-6).
- As an operator, I want AET to never move my checkout, so that running the tool
  cannot lose my place in my own work (satisfies: R-7).
- As an operator whose first run halted on a dirty tree, I want AET not to trip
  over files it wrote itself (satisfies: R-8, R-9).
- As an operator with a wedged queue, I want heal to fix it or delete-and-rebuild
  to work, so that recovery does not require hand-editing JSON
  (satisfies: R-10, R-11, R-12, R-13).
- As an engineer delivering one ticket in a shared repository, I want the whole
  ticket to produce one branch and one PR, so that my colleagues see one
  reviewable unit instead of a dozen (satisfies: R-14, R-15, R-16).
- As an engineer using `single-pr`, I want each task validated against the tip it
  actually lands on, so that serialized integration is not just serialized
  hope (satisfies: R-17, R-18).
- As an engineer using `single-pr`, I want an integration conflict reported as
  its own thing, so that I do not re-run a task that already passed
  (satisfies: R-19).
- As an engineer using `single-pr`, I want my work pushed as it integrates, so
  that a laptop failure does not lose an epic (satisfies: R-20).
- As a maintainer, I want trunk merge verification to keep its fail-closed
  property in both modes (satisfies: R-21).
- As a maintainer, I want per-task quality gates enforced even when task
  branches never leave the operator's machine, so that `single-pr` is not a
  gate-evidence bypass (satisfies: R-22).
- As a new adopter, I want the branch model documented, so that I can tell
  whether AET fits my repository before running it (satisfies: R-5, R-23).

## Acceptance Criteria

- [ ] In a repository whose `origin/HEAD` points at `dev` and with no config,
      `aet run` cuts worktrees from `dev`, and telemetry, worktree cleanup, and
      merge detection all agree on that base (satisfies: R-1, R-4).
- [ ] With `AET_WORK_BASE_BRANCH` set to a feature branch, tasks whose plans
      exist only on that branch run to completion (satisfies: R-2).
- [ ] `trunk_branch` set in `~/.aet/{slug}/config.json` overrides detection and
      is overridden by `AET_WORK_CONFIG`, with no config reader added outside
      `backends/factory.py` (satisfies: R-3).
- [ ] `aet setup verify` prints the resolved trunk and its derivation on a repo
      with an unset `refs/remotes/origin/HEAD` (satisfies: R-5).
- [ ] A run whose base lacks the plan file exits with the base, expected path,
      and override named, and the task's requeue count does not increase
      (satisfies: R-6).
- [ ] After a refresh of a diverged task branch, `git -C <repo_root> rev-parse
      --abbrev-ref HEAD` is unchanged (satisfies: R-7).
- [ ] A first run in a repo with no AET entries in `.gitignore` reaches task
      execution rather than halting on its own artifacts (satisfies: R-8, R-9).
- [ ] `init-queue` writes a complete queue in a plans directory containing
      unrelated plans that fail validation, warning about each
      (satisfies: R-10).
- [ ] `state heal --apply` on a task that is `in_progress` with a deleted branch
      moves it to its derived state and leaves `branch`/`worktree` cleared
      (satisfies: R-11, R-12).
- [ ] The reset primitive un-starts a task and the queue then round-trips
      through `init-queue` unchanged (satisfies: R-13).
- [ ] With `pr-per-task` and `integration_branch == trunk_branch`, the
      orchestrator's git command sequence is unchanged from before this work
      (satisfies: R-14, R-6 regression guard).
- [ ] A full `single-pr` epic leaves `git ls-remote --heads origin` containing
      the integration branch and no task branch, and exactly one PR
      (satisfies: R-15).
- [ ] In `single-pr`, a dependent task's worktree contains its blocker's
      committed changes at creation time (satisfies: R-16, R-17).
- [ ] With `--max-jobs 3` in `single-pr`, integration steps do not interleave,
      while implementation stages do (satisfies: R-18).
- [ ] A task whose post-rebase re-validation fails is reported as an integration
      failure and is not triaged as a task failure (satisfies: R-19).
- [ ] After each integration, the integration branch tip exists on `origin`;
      only one PR is opened across the epic (satisfies: R-20).
- [ ] Epic-level merge verification refuses to self-merge and refuses to mark
      done without verified merge evidence (satisfies: R-21).
- [ ] In `single-pr`, a task missing a required gate's recorded `pass` verdict
      is refused at integration; in `pr-per-task` the same gap is still caught
      by the pre-push hook as today (satisfies: R-22).
- [ ] Documentation states the resolution order for all three settings and
      contains a worked Scenario B setup (satisfies: R-23).

## Technical Notes

- **The deepest hardcoding is in the state machine, not the plumbing.**
  `is_ancestor_of_target` in `src/aet/cli/aet_state.py` feeds `derive_status`,
  which decides `merged`. In a non-`main` repository a genuinely
  merged task can never derive as `merged`, so ADR-011 never records the
  terminal transition, dependents never unblock, and heal's primary repair
  is unreachable. This is why R-4 must land as one change: fixing the
  git plumbing alone converts a loud failure into a silent deadlock.
- **The heal gap is two lines, not a missing capability.** `derive_status`
  computes the discrepancy correctly. `cmd_heal` in `src/aet/cli/aet_state.py` matches only
  (`ready`, {`failed`,`blocked`,`planned`}) and (`failed`,
  `in_progress`). The incident pair — (`ready`|`blocked`,
  `in_progress`) — matches neither, so heal reported "No healable discrepancies
  found" against a visibly wrong queue. R-11 adds the rule that consumes what
  heal already computes.
- **The `init-queue` ordering defect has precedent.** Validation aborting at
  `:230-238` before the skips at `:253`/`:260` is the same defect already
  recorded for `frh-17`/`frh-18`. The shared-repository case is a worse instance:
  there the invalid plans belong to other people's features and will never be
  fixed by this operator, so the queue is permanently unregenerable — and it is
  gitignored, so git cannot restore it either. Fixing the ordering resolves both
  instances.
- **The bug report's `--force` / `--only` sketch is resolved by scoping, not a
  flag.** `docs/bugs/2026-07-22-queue-reset-dead-end.md` recommends
  `init-queue --force` or `--only <glob>` as the supported reset path. R-10's
  scoped validation makes plain delete-and-rebuild sufficient, so G4 is met
  without a new flag. If planning surfaces a real need for subset rebuilds,
  that is a new requirement, not part of this PRD.
- **`--dist=loadgroup` interaction.** The suite pins orchestrator tests to one
  xdist worker. R-18's serialization tests are orchestrator tests and will land
  in that group; they must not add wall-clock time to an already-serialized
  group. Prefer asserting lock ordering over sleeping.
- **Why `single-pr` re-validates.** In `pr-per-task` the forge re-runs checks on
  the merge result. `single-pr` removes the forge from the per-task path, so
  without R-18's re-validation AET would integrate combinations nothing has
  tested. The re-validation is not belt-and-braces; it replaces a check that
  currently exists outside AET.

## Open Questions

- Should `single-pr` mode open the epic PR automatically on the last task, or
  leave it to the operator? ADR-045 does not decide. The plans assume operator
  action (`aet ship` at epic level); revisit once the mode has been used.
- Does `queue sync` need the same warn-and-skip treatment as `init-queue`, or
  does scoping validation in the shared helper cover both? R-10 requires the
  behavior; the plan makes the structural call with the code in front of it.
- Is one integration branch per queue sufficient, or will an operator want two
  epics in flight? Resolved by [ADR-076](../adr/076-an-epic-is-declared-not-inferred.md):
  one active epic is declared in the queue envelope at a time; tasks stamped with
  a different integration branch halt execution fail-closed with a mismatch error.

## Divergence Summary

*Recorded: 2026-07-23 — Branch: epi-05-init-queue-scoped-validation (R-10)*

### Changed from plan

- None. Tasks 1–2 of `epi-05-init-queue-scoped-validation` were implemented as
  locked: the included-set is computed before validation in `init_queue.py`,
  excluded plans warn-and-skip, included plans fail closed.

### Added (unplanned)

- Test fixture updates in `tests/plan/test_intake_gate.py` and
  `tests/queue/test_init_queue_sync.py`: bad-plan fixtures gained
  `status: queued` so they remain in the included set and keep exercising the
  fail-closed path after scoping. Without this they would be excluded as
  non-sprint plans and only warned on.

### Deferred

- None.

### Open question resolved

- The `queue sync` open question above is answered: `src/aet/cli/sync.py`
  already computes the included set (settled/sprint skips at `:69-72`) before
  calling `plan_validate.validate` at `:98`, so it never had the
  abort-before-skip defect. No shared-helper change was needed and `sync.py`
  was not modified.

## Divergence Summary (epi-02-thread-resolver-through-consumers)

*Recorded: 2026-07-23 — Branch: epi-02-thread-resolver-through-consumers (R-4)*

### Changed from plan

- None. Tasks 1–5 were implemented as locked: `create_worktree`,
  `remove_worktree`, `check_base_hygiene`, `_session_diff_stats`, and
  `is_ancestor_of_trunk` all receive the resolved refs.

## Divergence Summary: epi-04-orchestrator-run-preconditions

*Recorded: 2026-07-23 — Branch: epi-04-orchestrator-run-preconditions (R-6, R-8, R-9)*

### Changed from plan

- Task 2 (`aet setup` writes ignore entries): implemented as a dedicated
  `aet setup bootstrap` subcommand rather than embedding the writer in the main
  setup flow. The shared `AET_IGNORED_PATHS` constant is still the single source
  of truth for both the hygiene gate and the writer.

### Added (unplanned)

- None.

### Deferred

- Task 6 (epi-02 merge branch to main and verify integration): the merge and
  final integration verification are out of scope for the sync-docs stage and
  will happen at the ship stage.
- Broad "no hardcoded `main`" grep validation: the plan's validation step
  `grep -rn "origin/main\|main\.\.\|main\.\.\." src/aet/` returning no matches
  remains incomplete outside the five scoped consumers. Literal refs persist in
  `ship.py`, `sprint.py`, `change_scope.py`, `verifier.py`, and `init_queue.py`,
  which were not part of this plan's locked scope; they are deferred to the
  mode-keyed work in `epi-08` or a dedicated trunk-generalization hygiene sweep.
- Task 5 (epi-04 merge branch to main and verify integration): deferred to the
  ship/merge stage; `git merge-base --is-ancestor HEAD origin/main` is not yet
  true.

## Divergence Summary (epi-11-branch-model-docs-and-verify)

*Recorded: 2026-07-24 — Branch: epi-11-branch-model-docs-and-verify*

### Changed from plan

- None.

### Added (unplanned)

- None.

### Deferred

- Task 3 (merge branch to main and verify integration): deferred to the
  `aet-ship` stage; `aet-sync-docs` does not perform merges.

## Divergence Summary: epi-08-single-pr-completion-loop

*Recorded: 2026-07-24 — Branch: epi-08-single-pr-completion-loop (R-15, R-16, R-17, R-4)*

### Changed from plan

- **R-18 (advisory lock + post-rebase re-validation):** Not implemented. The
  integration step is a simple squash-merge into the integration branch without
  serialization or re-validation against the live tip.
- **R-19 (integration failure as distinct failure category):** Not implemented
  as a distinct category. A failed integration returns `False` from
  `process_task` and is handled through the existing task-failure path.
- **R-22 (per-task gate evidence at integration time):** Gate evidence is
  enforced during stage advancement but not re-verified inside the integration
  step itself.
- **R-7 (no repo-root HEAD changes):** `squash_merge_task_branch` checks out the
  integration branch in `repo_root`, changing `HEAD` there. This contradicts the
  hard requirement that AET never changes the repo-root checkout.

### Added (unplanned)

- None.

### Deferred

- **Epic merge to trunk and final integration verification** — out of scope for
  the sync-docs stage; will happen at the ship stage.

## Divergence Summary: epi-06-state-heal-gap-and-reset

*Recorded: 2026-07-24 — Branch: epi-06-state-heal-gap-and-reset*

### Changed from plan

- None. Tasks 1–3 were implemented as locked: the missing heal rule for (`ready`/`blocked`, `in_progress`/`awaiting_merge`) was added to `cmd_heal`, stale `branch`/`worktree` fields are cleared by `_clear_stale_runtime_fields` during repair transitions, and `aet state reset` recomputes a single task and un-starts it.

### Added (unplanned)

- `tests/cli/test_build_parsers.py` was updated to register the new `reset` subcommand in the command registry. This is the standard parser collateral implied by adding a new `aet state` subcommand.

### Deferred

- Task 4 (merge branch to main and verify integration): the merge and final integration verification are out of scope for the sync-docs stage and will happen at the ship stage.

## Divergence Summary: epi-09-serialized-integration

*Recorded: 2026-07-24 — Branch: epi-09-serialized-integration (R-18, R-19)*

### Changed from plan

- None. Tasks 1–3 were implemented as locked: `src/aet/integration_lock.py`
  provides a local advisory `FileLock`, and `_integrate_single_pr_task`
  serializes the rebase → re-validate → squash-merge step while leaving
  implementation stages concurrent. Re-validation failures and rebase conflicts
  raise `IntegrationFailureError` and are recorded as engine-level Integration
  Failures outside the ADR-030 task-failure menu.

### Added (unplanned)

- `src/aet/worktree.py`: `.agents/integration.lock` was added to
  `AET_IGNORED_PATHS` so the hygiene gate ignores the new lock sidecar, matching
  the treatment of the queue lock sidecars.
- `src/aet/cli/orchestrator.py`: the repo-root checkout is remembered before the
  integration-branch checkout and restored in the `finally` block that releases
  the lock. This closes the R-7 gap noted in the `epi-08` divergence summary.
- Test mock updates in `tests/orchestrator/test_pr_per_task_unchanged.py` and
  `tests/orchestrator/test_single_pr_loop.py` to match the updated
  `run_stage`/`run_stage_group` return signatures.

### Deferred

- Task 4 (merge branch to main and verify integration): the merge and final
  integration verification are out of scope for the sync-docs stage and will
  happen at the `aet-ship` stage.

## Divergence Summary: epi-10-epic-durability-and-closure

*Recorded: 2026-07-24 — Branch: epi-10-epic-durability-and-closure (R-20, R-21, R-22)*

### Changed from plan

- None. Tasks 1–3 were implemented as locked: `src/aet/gate.py` factors the
  verdict helper so `src/aet/cli/hooks.py` and `_integrate_single_pr_task`
  share one implementation of task-branch detection, required-stage resolution,
  and verdict-path derivation; the integration step pushes the integration
  branch after each successful squash-merge (R-20) and verifies required gate
  evidence before the squash-merge lands (R-22); `aet ship close` accepts a
  `--target-branch` override and refuses self-merge while delegating merge
  evidence verification to the existing `cmd_record_merge` path (R-21).

### Added (unplanned)

- None.

### Deferred

- Task 4 (merge branch to main and verify integration): the merge and final
  integration verification are out of scope for the sync-docs stage and will
  happen at the `aet-ship` stage.

---

*Stage: synced*
*Next step: run `aet-ship`*
