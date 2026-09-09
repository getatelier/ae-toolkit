# PRD: Local-Only Plans — Defer Plan Durability to the PR

## Overview

`aet run` currently refuses to start unless every queued plan is committed
and pushed to origin. Two gates enforce this: `aet sprint add` called
`commit_and_push_status` unconditionally (`add` in `src/aet/cli/sprint.py`) —
so even `--allow-untracked` ends up publishing the plan — and `check_base_hygiene` (`src/aet/worktree.py`)
halts the run on any untracked `docs/plans/*.md` ("Working tree is dirty") or
on local main being ahead of origin.

Codebase verification (2026-08-05) shows the strictness is protecting against
a failure the toolkit can now handle directly. `copy_untracked_files`
(`src/aet/worktree.py`, called in `src/aet/cli/orchestrator.py`)
already mirrors untracked planning docs into the task worktree before the
plan-existence check; the verdict `tree_hash` (`working_tree_hash` in `src/aet/verifier.py`)
stages untracked files via `git add -A`, so evidence is unaffected; the
worktree copy of the plan is the operative document during the run
(in `src/aet/cli/orchestrator.py`); and no code reads plan content through git
objects or origin refs. The push requirement is a plumbing constraint —
worktrees base off `origin/<ref>` (in `src/aet/cli/orchestrator.py`) — wearing a
durability costume.

This PRD makes local-only plans **the behavior**, not an opt-in mode, scoped
narrowly to `docs/plans/*.md`. A plan goes from `aet sprint add` to merged PR
without an intermediate commit, landing in the task branch's PR diff. PRDs,
ADRs, and every other planning document keep today's commit-and-push posture
unchanged.

### Why no mode toggle

ADR-027 introduced the hygiene gate to fix one concrete bug: plans queued
against an unpushed working tree silently went missing and the worktree came
up empty. Its Alternatives section rejected a surgical per-plan check as
"more code for the same coverage" — an economy argument, not a safety one.
The overlay (R-3) plus fail-closed plan resolution (R-6) *is* that surgical
mechanism, and it is strictly stronger than the gate it replaces: the gate
prevents the bug by forbidding the state, the overlay makes the state work
and halts loudly if the plan is still absent.

ADR-027 and ADR-045 both defend the durability of **agent-produced code on
unpushed branches**. Neither addresses a plan document. At plans-only scope
the deferred artifact is a single `status: queued` marker on a regenerable
execution script, and the queue that mirrors it (`.agents/work-queue.json`)
is already gitignored — mid-sprint liveness was never durable. ADR-034's
actual guarantee, settled-ness derived from committed plan data, is written
at closure and is preserved and strengthened here (R-5, R-6).

With nothing load-bearing deferred, there is no posture worth maintaining a
second code path for. A clean cut matches the project's no-backward-compat
principle and removes the largest chunk of the build (the `integration_mode`
toggle spans 13 files: 4 source, 9 test).

## Goals

- A plan goes from `aet sprint add` to merged PR with no intermediate commit
  or push of the plan file; it lands in the task branch's PR diff alongside
  the implementation.
- One canonical definition of the durability-deferred path set
  (`docs/plans/`), consumed by intake, hygiene, worktree materialization, and
  worktree cleanup — no call site keeps its own list.
- The implementing agent provably works from the latest local plan text,
  never a stale committed copy.
- Base hygiene still halts on genuine code-freshness problems, with no new
  path for a stale-base run.
- Closure still produces a durable, pushed, `merged`-status plan — or fails
  loudly.

## Non-Goals

- No change to the worktree base model: worktrees still branch from
  `origin/<integration>` (ADR-044/045). Plans move into the worktree by copy,
  not by rebasing onto local refs.
- No change to PRDs, ADRs, audits, retros, or product-briefs. Their existing
  untracked-mirroring into worktrees (`copy_untracked_files`) is unchanged,
  and they continue to be committed and pushed by the operator as today.
- No multi-clone or multi-teammate coordination. AET is one-plan-one-operator;
  ADR-034's multi-clone rationale is out of scope for the mid-sprint window,
  not defended.
- No configuration surface. There is no mode, no config key, no CLI flag, and
  no env var — this is the behavior.
- No migration or backfill of historical plans. Plans already committed
  continue to work unchanged.

## Requirements

- **R-1**: The durability-deferred path set is defined exactly once as a
  shared constant covering `docs/plans/`, consumed by intake (R-2), worktree
  materialization (R-3), base hygiene (R-4), branch seeding (R-5), and
  worktree cleanup (R-7). No call site keeps its own path list. The existing
  six-directory untracked mirror in `copy_untracked_files` is a separate,
  unchanged concern and keeps its own list.
- **R-2**: Queue intake (`aet sprint add`, `aet backlog`) writes plan status
  to the file only — no `git add`, commit, or push. The gate is applied at
  the single choke point `write_queue` (`src/aet/queue.py`),
  not at each caller. Because that function serves both intake
  (`status: queued`) and closure (`status: merged`,
  `cmd_record_merge` in `src/aet/cli/aet_state.py`) over the same paths, the gate keys on
  **status terminality, not path alone**: for a path in the R-1 set, commit
  and push only when the status is terminal (`merged`, `abandoned`);
  otherwise write the file and return. This is the ADR-034 revision expressed
  in code — mid-sprint status is local, settled status is durable. The
  untracked-plan refusal and its `--allow-untracked`
  escape hatch in `src/aet/cli/sprint.py` are removed: an untracked plan is now the normal case.
- **R-3**: Worktree materialization syncs the working-tree version of the
  task's plan into the worktree regardless of git state — untracked,
  tracked-but-modified, or tracked-but-absent-from-base — replacing
  `copy_untracked_files`' untracked-only logic for `docs/plans/`. The
  implementing agent always reads the latest local plan text.
- **R-4**: Base hygiene distinguishes code freshness from plan availability:
  (a) paths under `docs/plans/` — untracked *or* modified — no longer trip
  the dirty-tree check; (b) the ahead-of-origin check passes when the
  diverging local commits touch *only* `docs/plans/` paths. Any commit
  touching a non-plan path still halts, as does any non-plan dirty path.
  Hygiene remains fail-closed in both execution modes (ADR-027).
- **R-5**: The task branch's first commit adds **only the task's own plan
  file**, by explicit path — never `git add -A`, and never other tasks'
  plans or the untracked PRDs/ADRs that `copy_untracked_files` mirrors. The
  commit is skipped when the plan path already exists on the local
  integration branch (checked with `git cat-file -e <integration>:<path>`),
  so a plan carried by an unpushed local commit under R-4(b) cannot produce
  an add/add conflict at merge. Merge closure then updates plan status as
  today (`cmd_record_merge` in `src/aet/cli/aet_state.py`).
- **R-6**: Closure never silently skips the final plan commit. The current
  guard in `cmd_record_merge` (`src/aet/cli/aet_state.py`) skips `commit_and_push_status` when the plan
  path is absent from disk yet still prints "Recorded merge" and returns 0.
  If the plan file cannot be resolved from the checkout or the merged branch,
  closure fails closed and names the fix.
- **R-7**: Worktree cleanup ignores a plan-only commit when deciding whether
  a worktree is empty. `remove_worktree` (`src/aet/worktree.py`)
  currently removes only when `rev-list --count <base>..HEAD` is 0; R-5
  guarantees at least one commit, so the emptiness test must exclude commits
  whose diff touches only the R-1 path set, or worktrees will accumulate
  under `.worktrees/` forever.
- **R-8**: Evidence and verification are unaffected by untracked plans.
  Verdict `tree_hash` behavior is pinned by regression tests with untracked
  plans present in the worktree; `aet plans lint`, `aet status`, and
  `aet queue sync` operate on untracked plans without drift reports (they
  read the filesystem today — tests make that contractual).
- **R-9**: The operator can see the posture: `aet sprint add` reports that
  the plan was queued without publishing, and the orchestrator prints a
  one-line notice at run start that plan durability is deferred to the PR.
- **R-10**: Every document that instructs or describes the superseded
  behaviour is corrected in the same change that supersedes it. This is not a
  cosmetic sync: the planning skills are symlinked and live, so a stale
  instruction keeps producing the old workflow and the delivered feature is
  never exercised. Specifically:
  (a) `skills/aet-plan/SKILL.md` (two places) and
  `skills/aet-pipeline-plan/SKILL.md` step 3 stop instructing "commit the plan
  files before queueing" and stop citing an intake guard that no longer exists;
  (b) `skills/aet-work/references/queue-commands.md` corrects the `sprint add`
  procedure ("Set `status: queued`, commit, and push") and the base-hygiene
  paragraph, which currently states that a dirty-or-ahead trunk always halts;
  (c) `docs/CONVENTIONS.md` and `AGENTS.md` record the narrowed hygiene
  contract and the removal of `--allow-untracked`;
  (d) new operator guidance states that untracked plans are now load-bearing —
  `git clean -fdx`, and any backup or sync that follows git, will discard
  in-flight work that git no longer knows about.

## User Stories

- As a solo operator, I want to queue and run plans that exist only on my
  machine, so that I commit intent documents once — with the PR — instead of
  pushing bookkeeping commits to main before any code exists (satisfies:
  R-2, R-5).
- As a solo operator, I want the implementing agent to read the plan I just
  edited, not a stale committed copy, so that mid-sprint plan corrections
  take effect without a publish step (satisfies: R-3).
- As an operator running unattended batches, I want hygiene to still halt on
  unpushed *code* commits and dirty *code* paths, so that local-only plans
  never smuggle in a stale-base run (satisfies: R-4).
- As a reviewer of the task PR, I want the plan in the same diff as the
  implementation — and *only* that task's plan — so that I review intent and
  code together without unrelated documents in the diff (satisfies: R-5).
- As an operator at merge time, I want closure to either record the final
  plan status durably or refuse loudly, so that a missing plan file can never
  produce a silently unclosed task (satisfies: R-6).
- As an operator between runs, I want finished worktrees cleaned up as
  before, so that seeding the plan commit does not leak disk (satisfies:
  R-7).

## Acceptance Criteria

- [ ] An untracked `docs/plans/x.md` passes `aet sprint add` with no
  `--allow-untracked` flag, creates no commit and no push (`git log
  origin/main` unchanged, working tree still shows the file as untracked),
  and a subsequent `aet run` completes with the plan present in the worktree
  (satisfies: R-1, R-2, R-3).
- [ ] Editing a *tracked* plan locally and re-running materializes the edited
  text into the worktree — diffing the worktree copy against the working tree
  shows no difference (satisfies: R-3).
- [ ] Local main ahead of origin by a commit touching only `docs/plans/`
  passes hygiene; adding any non-plan path to that commit, or dirtying any
  non-plan path, halts the run (satisfies: R-4).
- [ ] An untracked PRD in `docs/prds/` still reaches the worktree but does
  *not* trip hygiene's dirty check — it is refused as before, unchanged
  (satisfies: R-1, R-4).
- [ ] A task run produces a task branch whose first commit adds exactly one
  file, that task's plan; with a second untracked plan and an untracked PRD
  present in the repo, neither appears in the branch or the PR diff
  (satisfies: R-5).
- [ ] With the plan already present on the local integration branch via an
  unpushed commit, the run creates no duplicate plan commit and the branch
  merges without conflict (satisfies: R-4, R-5).
- [ ] Deleting the plan file from the main checkout before closure makes
  closure fail with a named remedy instead of printing "Recorded merge"
  (satisfies: R-6).
- [ ] A worktree whose only commit is the R-5 plan commit is removed by
  `remove_worktree`; a worktree with any implementation commit is retained
  (satisfies: R-7).
- [ ] Verdict `tree_hash` computed in a worktree with untracked plans matches
  the evidence-comparison path; `aet plans lint` and `aet status` report no
  drift for untracked queued plans (satisfies: R-8).
- [ ] No document instructs committing a plan before `aet sprint add`, and no
  document describes a `--allow-untracked` flag or an intake guard that
  refuses untracked plans: `grep -rn "allow-untracked\|refuses untracked\|
  commit the plan files" skills/ docs/ AGENTS.md` returns only historical
  records (`docs/bugs/`, `docs/adr/`, `CHANGELOG.md`) (satisfies: R-10).
- [ ] The `git clean` hazard is documented where an operator will meet it, not
  only in the ADR (satisfies: R-10).

## Technical Notes

- **Verified facts this design relies on** (2026-08-05 trace, two prior
  analyses corrected): `copy_untracked_files` runs before the plan-existence
  check, so untracked plans already reach the worktree — the blockers are
  intake's forced commit+push and the hygiene dirty check, not worktree
  visibility. `working_tree_hash` in `src/aet/verifier.py` seeds a temp index
  from HEAD and runs `git add -A`, so untracked files are included and
  evidence is unaffected. `enforce_base_hygiene` in `src/aet/cli/orchestrator.py`
  is fail-closed in both execution modes — the 2026-07-14 learning about
  unattended warn-and-continue is outdated. No code reads plan content via
  `git show`/`cat-file`/origin refs.
<!-- aet-lint: off -->
- **Single choke points**: durability gating happens in
  `commit_and_push_status` (`src/aet/queue.py`) and `check_base_hygiene`
  (`src/aet/worktree.py`); materialization in the successor of
  `copy_untracked_files` (`src/aet/worktree.py`); cleanup in `remove_worktree`
  (`src/aet/worktree.py`). Callers (`src/aet/cli/sprint.py`, `src/aet/cli/backlog.py`, `src/aet/cli/aet_state.py`,
  `src/aet/cli/orchestrator.py`) stay ignorant of the rule.
- **Closure ordering**: closure runs from the main checkout after merge
  (`cmd_record_merge` in `src/aet/cli/aet_state.py`), so R-5's seeded commit guarantees the plan file
  exists on the integration branch for the final status update. R-6 covers
  the residual hole.
<!-- aet-lint: on -->
- **R-5 commit hygiene**: the worktree contains untracked PRDs/ADRs mirrored
  by `copy_untracked_files`, so the seeding commit must stage an explicit
  path. A bare `git add -A` or `git commit -a` would sweep them into the PR.
- **Mid-run edits**: the overlay (R-3) syncs at worktree creation and
  refresh; editing a plan in the main checkout *during* a run does not
  propagate. This is acceptable (the run is a snapshot) and must be
  documented in the aet-work skill reference.
- **ADR trail** (mandatory per AGENTS.md): **ADR-054**
  (`docs/adr/054-plan-documents-are-outside-the-durability-gate.md`), authored
  during scope validation. It establishes that plan documents are outside
  ADR-027's durability class, narrows ADR-027 for plan paths, and revises
  ADR-034 **decision 3** so that terminal status writes stay committed and
  pushed while non-terminal ones do not. Per `docs/adr/README.md`, ADRs are
  immutable once accepted — ADR-027 and ADR-034 are **not** edited in place;
  ADR-054 declares the revision, exactly as ADR-027 extended ADR-005 and
  ADR-034 revised ADR-013. ADR-013's decisions survive intact (closure still
  writes the terminal status). ADR-044 and ADR-045 are untouched.

## Resolved at Scope Validation (2026-08-05)

- **R-5 seeding commit shape** — resolved: a standalone `Add plan for <task>`
  commit, not folded into the first implementation commit. It gives the PR a
  clean narrative and makes R-7's emptiness classification trivial.
- **`single-pr` epic mode (ADR-045)** — resolved: no special case needed. Both
  hygiene call sites in `src/aet/cli/orchestrator.py` already pass
  `integration.ref`, so epic mode inherits the R-4 narrowing unchanged. One
  latent defect surfaced and was folded into `lop-02` task 3:
  `create_worktree`'s rebase-recovery calls `remove_worktree` in
  `src/aet/worktree.py` without forwarding its `base_branch`, so the emptiness
  predicate is evaluated against `origin/main` under a non-trunk integration
  branch.
- **`content/backlog/` and `docs/bugs/`** — resolved: out of scope, no change.
  `copy_untracked_files`' six-directory mirror is untouched by this PRD, per
  the Non-Goals. The omission is pre-existing and stays as it is.

## Risks

- **Durability gap by design**: an uncommitted plan is lost on machine
  failure. Accepted and bounded — the loss is one `status: queued` marker on
  a script regenerable from its PRD, and mid-sprint liveness was already
  non-durable because the queue is gitignored. R-9 surfaces the posture at
  intake and run start.
- **Removing ADR-027's gate on the default path**: this is a real reduction
  in preventive strictness for every user, night-shift included. The
  mitigation is that R-3 + R-6 close ADR-027's originating bug more precisely
  than the gate did — but they must be built correctly, not merely specified.
  R-3 and R-6 carry mandatory regression tests covering the empty-worktree
  scenario ADR-027 was written for.
- **Hygiene narrowing masks a real change**: a commit mixing plan and code
  paths must still halt. Mitigated by R-4's "any non-plan path → violation"
  rule with regression tests on mixed commits.
- **Seeding commit leaks unrelated documents**: the worktree holds mirrored
  untracked PRDs/ADRs at commit time. Mitigated by R-5's explicit-path
  staging and an acceptance criterion that asserts a one-file first commit.
- **Worktree/repo-root divergence**: two copies of the plan exist during a
  run (working tree and worktree overlay). Only closure mutates status
  post-run, and it operates on the post-merge checkout — no write conflict.

## Divergence Summary

*Recorded: 2026-08-06 — Branch: lop-01-unpublished-plan-intake-and-hygiene*

**Changed from plan (lop-01)**

- **R-3 (worktree materialization)**: Verified that `copy_untracked_files` already mirrors untracked `docs/plans/*.md` into the worktree before the plan-existence check, so the end-to-end path works without modifying materialization logic. The operative plan copy behavior is preserved by existing code.

**Deferred (lop-01)**

- **R-5 (branch-seeding plan commit), R-6 (closure fail-closed hardening), R-7 (plan-only worktree cleanup)**: These requirements are not implemented in this branch. They are scoped to follow-up plan `lop-02` per the locked design and floor check in `lop-01`, which explicitly cannot share a branch with the behaviour change.

---

*Recorded: 2026-08-06 — Branch: lop-03-closure-fails-closed-on-missing-plan*

**Changed from plan (lop-03)**

- No material changes. The fail-closed guard, merged-branch resolution helper, and regression test coverage were implemented as specified.

**Added unplanned (lop-03)**

- Test fixture cleanup in `tests/backends/test_aet_state_backend.py` and `tests/orchestrator/test_orchestrator.py`: removed or corrected stale `plan_file` references so unrelated tests do not accidentally resolve a plan file and so the missing-plan refusal paths exercise the intended fallthrough case.

**Deferred (lop-03)**

- Merge to main and integration verification: deferred to the `aet-ship` stage.

*Stage: synced*
*Next step: run `aet-ship`*
