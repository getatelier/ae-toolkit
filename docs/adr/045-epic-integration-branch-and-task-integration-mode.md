---
subject: integration-mode
---

# Epic Integration Branch and Per-Task Integration Mode

## Status

Accepted. Builds on ADR-044 (base branch is configured, not assumed), which is a
hard prerequisite. Generalizes ADR-029 (autonomous merge is a fail-closed gate)
and the unblocking semantics of ADR-011 (forward-only work state). Interacts
with ADR-004 (unify `aet run`) and ADR-013 (queue as ephemeral sprint board).
Amended by [ADR-076](076-an-epic-is-declared-not-inferred.md) regarding epic identity representation.

Adapted from a design proposed alongside
`docs/bugs/2026-07-22-orchestrator-base-branch-hardcoded.md`. The proposal was
drafted as a single ADR numbered 041; that number was taken, and the
generalization it depended on was separable and independently shippable, so it
was split into ADR-044 (this ADR's prerequisite) and this one.

## Context

ADR-044 makes AET build on a configured branch instead of a literal `main`. That
is necessary but not sufficient, because AET collapses three distinct concepts
into one identity:

> **one plan = one branch = one PR = one merge to trunk.**

That identity is not just in the git plumbing ADR-044 fixes. It is in what
"done" means: the queue unblocks a task's dependents, and `aet ship` calls a
task complete, only once its commit is verified on trunk (ADR-029).

The identity holds in **Scenario A — solo, trunk-based.** A PRD decomposes into
plans, each plan is independently shippable, and many small PRs land on trunk.
This is the workflow AET was built for and it works well.

It breaks in **Scenario B — one engineer in a shared repository delivering one
ticket.** The PRD covers a single ticket; the plans are *internal decomposition*
of it. The host repository's branching policy requires one feature branch and
one PR. Opening a branch and a PR per subtask puts a dozen artifacts into a repo
other people are reading, for work that is one reviewable unit.

With ADR-044 alone, Scenario B is *runnable* but wrong in two ways: per-task
branches are still created and pushed, and "done" still means merged-to-trunk —
which for this engineer requires a protected-branch PR per subtask, i.e. exactly
what the branching policy forbids.

The gap is a missing layer: an **epic** that owns an integration branch and a
trunk target, sitting above the tasks that decompose it.

**Scope boundary.** Scenario B is one engineer delivering one ticket. It is
still one operator driving one queue, so this ADR does not cross the line
established for AET's scope: coordination *between people* is management, not
engine scope. The serialization in decision 5 is intra-operator — it orders one
operator's own concurrent pipelines, which is what `--max-jobs` already implies.
It is not a claim-check, not a lease, and not visible to anyone else. Nothing
here makes AET aware of other humans, and nothing here should be extended to.

## Decision

Introduce an epic/integration layer and make the trunk-based identity the
**degenerate case** of a more general model, not a special case beside it.

### 1. Two integration modes

`integration_mode` is project configuration, resolved through the ADR-044 chain:

- **`pr-per-task`** (default) — today's behavior. Each task gets a branch and a
  PR, and lands on trunk independently.
- **`single-pr`** — tasks integrate into the epic's integration branch locally.
  One PR is opened, at the epic level, for the integration branch.

Scenario A is `integration_mode: pr-per-task` with
`integration_branch == trunk_branch`. It is not special-cased anywhere; it is
the configuration in which the general machinery reduces to what exists today.
This is the property that keeps the default path from regressing: there is one
code path, and Scenario A is a set of values through it.

### 2. The base is the integration branch's live tip

Dependent tasks integrate into the same branch, so a task must be cut **after**
its blockers have integrated, from the advanced tip — not from a snapshot taken
when the run started. The engine is: *task completes → integration branch
advances → next unblocked task is cut from the new tip*. Worktree refresh
rebases onto the current tip.

This is a real change to when a worktree may be created, not only to what it is
based on. In `pr-per-task` the forge serializes merges and each task is
independent of its siblings' branches; in `single-pr` the queue's dependency
graph and the branch's history must agree.

### 3. "Done" means integrated

In `single-pr` mode a task completes by squash-merging into the integration
branch **locally**. ADR-011's dependency-unblocking fires on that event.
ADR-029's trunk merge-verification moves **up to the epic level** and runs
**once**, when the integration branch's PR merges into trunk.

ADR-029's fail-closed property is preserved, not weakened: the gate still
requires verified merge evidence before anything is called done, and it still
refuses to self-merge. What changes is the granularity at which it is
evaluated — once per epic instead of once per task — because in this mode the
epic is the unit that reaches trunk.

### 4. Per-task branches are ephemeral and local

In `single-pr` mode AET guarantees no per-task branch reaches `origin`. Each is
created, integrated, and deleted locally. Only the integration branch is pushed,
and only it gets a PR. This is the property that keeps a shared repository
clean, and it is a guarantee rather than a default — the push path is not
reachable in this mode.

### 5. Parallel implementation, serialized integration

`pr-per-task` gets merge serialization free from the forge. `single-pr` makes
AET own it: pipelines run concurrently up to `--max-jobs`, but the *integration*
step — rebase onto current tip, re-validate, squash-merge — is gated behind a
**local lock**, one task at a time.

This is the one genuinely new mechanism; everything else generalizes existing
code. It is deliberately the same shape as the existing queue lock
(`.agents/work-queue.json.lock`, fcntl), and it is local, single-operator, and
advisory. Re-validation after rebase is not optional: a task that passed against
an older tip has not been shown to pass against the tip it is landing on, and
without that step `single-pr` would integrate untested combinations — which is
precisely the guarantee the forge provides in `pr-per-task`.

### 6. Hygiene and telemetry read the configured branches

Per ADR-044, `check_base_hygiene` and `_session_diff_stats` already take
resolved refs. In `single-pr` mode they take the integration branch, so a run
is gated on the epic's branch being clean and in sync — not on trunk, which this
operator may not be able to push to at all.

## Consequences

- **Easier:** One engineer can drive a multi-plan ticket in a shared repository
  and produce exactly one feature branch and one PR.
- **Easier:** AET stops requiring a team to change its branching policy in order
  to use AET.
- **Easier:** The solo/trunk workflow is unchanged — it is the default and the
  degenerate case, not a preserved legacy path.
- **Harder:** "Done" has two meanings keyed by `integration_mode`. The queue,
  `aet ship`, and telemetry must all read the mode. This is the cost of the
  model and the most likely source of future bugs; it is why decision 1 insists
  Scenario A be the same code path rather than a branch beside it.
- **Harder:** `single-pr` introduces a local merge queue and integration
  re-validation — more orchestrator state than delegating serialization to the
  forge.
- **Harder:** A failed integration (rebase conflict, or re-validation failing
  against the new tip) is a new failure class. It is not the task's failure —
  the task passed — and it must not be triaged as one.
- **Risk:** In `single-pr` mode work exists only locally until the epic PR is
  opened. ADR-027's durability reasoning — unpushed work is work that can be
  lost — applies to the integration branch, which must therefore be pushed on
  every integration even though its PR opens once.
- **Neutral:** `AET_WORK_BASE_BRANCH` remains a valid per-run override for the
  integration branch, subsumed by ADR-044's resolution chain.

## Alternatives Considered

- **ADR-044 alone; accept per-task PRs on a feature branch** — rejected as the
  complete answer, though it is a genuine improvement and ships first. It leaves
  N branches and N PRs visible in a shared repository, which is the specific
  cost the host branching policy exists to avoid.
- **Stacked PRs: one PR per task targeting the feature branch** — rejected. It
  is the tidiest forge-native option and it still produces N visible branches
  and N PRs. The goal is one deliverable, one PR.
- **Keep trunk-only; require plans merged to trunk first** — rejected for the
  same reason as in ADR-044: it forces planning documents through a
  protected-branch PR before implementation starts and inverts the host
  repository's workflow.
- **Run the loop, then squash into the feature branch by hand** — rejected.
  Manual, error-prone, and it discards the dependency-ordered integration the
  queue already models. It also moves the one step that needs re-validation
  outside the tool.
- **Serialize by setting `--max-jobs 1` in `single-pr` mode** — rejected. It
  would remove the need for the lock by removing concurrency, trading the
  feature's main benefit for a mechanism the queue lock already demonstrates is
  cheap to build.
- **Make the epic a first-class persisted entity** — rejected for now. It is the
  cleanest model and probably where this ends up, but it adds an entity beside
  the queue whose regeneration story under ADR-013 is unclear. The epic is
  represented by its integration branch plus the PRD the plans already
  reference, which is sufficient for both modes and adds no new persisted state.
