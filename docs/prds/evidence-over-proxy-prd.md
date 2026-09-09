# PRD: Evidence Over Proxy

## Overview

ADR-064 settled one question in 2026-08-22: *ancestry is not merge evidence*. A
branch created from the trunk tip and never committed to is an ancestor of its
own base, so it passes the same test a genuinely merged branch passes — and
`derive_status` returned `merged` for it, with `resolve_merge_commit`
manufacturing a `merge_commit` out of the absence of work.

That ADR fixed one site. The reasoning behind it was never applied anywhere
else, and the same shape is live in six more places. In each, a signal that is
cheap to read stands in for the evidence a decision actually needs, and the two
are indistinguishable to the code that reads them:

| Decision | Proxy it trusts | Evidence it needs |
| --- | --- | --- |
| Is this run still going? | a PID number is held by *some* process | the process holding it is the one the run started |
| May the queue lease be reclaimed? | the same PID check | the same |
| Is this task in progress? | a branch exists | a session ran and left work |
| Did the gate pass on what I am merging? | `make validate` passed in the cwd | it passed on the tree being merged |
| Is this stage attested? | `summary` is of type `str` | `summary` says something |
| Should this failure be requeued? | a failure-class label | a stage, a signature, or a tail |
| Did the scan find nothing? | a bucket count of `0` | the bucket was scanned |
| Is the suite green? | `0 failed` | no red is being discounted |

Every one of these is filed in `content/backlog/` with its own evidence. This
PRD does not treat them as eight unrelated fixes. It records the rule ADR-064
implied, and makes the eight sites conform to it.

### Why this is worth doing as one piece of work

Two of the eight were observed misbehaving during the evaluation that produced
this PRD, on 2026-08-29, without anyone going looking:

- `aet status` on this repo's `main` listed five detached runs from 2026-08-19 as
  active. Two of the five PIDs resolved to `QuickLookUIService` and
  `chrome_crashpad_handler` — both started *after* the run they were attributed
  to. The other three were dropped only because nothing had yet claimed their
  numbers.
- The board showed `ppa-01` stored `in_progress` with `aet state audit` deriving
  `ready`, a stale worktree, and no branch.

Fixed one at a time, each is a small correctness patch and the class survives.
The eighth instance gets written next year by someone reading the seventh.

## Decision Record

The general rule is recorded in **ADR-072 (A Proxy Is Not Evidence)**, authored
during this PRD's scope validation, generalising ADR-064 beyond the merge
transition. Its six numbered decisions map to the requirements below: existence
is not activity (R-3), identity must be checked (R-1, R-2), a check must be about
its subject (R-4), well-formed is not attested (R-5), no evidence is not a
decision (R-6), and absence and zero are different results (R-7, R-8). It is
deliberately
**not** a numbered requirement: it is delivered by the planning session, not by
any plan, and `rtrace` reads `## Requirements` and would block the sprint on an
R-id no task can cover. The plans below cite the ADR; none of them authors it.

## Goals

1. The toolkit has a stated, ADR-backed rule for when a cheap signal may be read
   as evidence of a fact, generalising ADR-064 beyond the merge transition.
2. Run liveness is decided in one place, from evidence, and a recycled PID
   cannot present as a live run or hold the queue lease.
3. No state is derived from the mere existence of an artifact — a branch, a
   checkout, a PID — where the artifact can exist without the fact being true.
4. A gate cannot pass on an attestation that is well-formed and empty.
5. A report that scanned nothing does not render identically to a report that
   scanned everything and matched nothing — for test gates and for telemetry
   reports alike.

## Non-Goals

- **Re-deciding ADR-064.** It is accepted and correct. This PRD generalises its
  reasoning; it does not revisit the merge transition, which already conforms.
- **New capability of any kind.** No new command, no new telemetry, no new
  report. Every requirement below removes a false positive from an existing
  code path. Where a fix could be delivered either by adding a mechanism or by
  correcting an existing one, this PRD takes the second.
- **Chasing the causes of the three intermittent test failures.** Two of the
  three do not reproduce. R-7 marks them so a green gate is readable; it does
  not diagnose them. The escalation question the loadgroup report raises — can
  a real concurrent batch lose a task-record write the same way — stays open and
  is called out in Open Questions.
- **A periodic full-suite run to catch a standing red.**
  `debt-impact-scope-can-hide-a-standing-red` is the sibling of R-7 and is
  deliberately excluded: its own trigger asks for a *second* occurrence and there
  has been one. Adding the run now would also be new machinery, which this PRD
  has none of.
- **Evidence portability and ledger transport.** `evidence-portability` and
  `debt-ledger-has-no-refs-transport` concern *where* verdicts and provenance
  live. R-5 concerns whether a verdict's contents mean anything. Both of those
  need a decision this PRD does not take.
- **`aet setup verify` / skill-symlink drift.** Closed by `783ea72a` on
  2026-08-28; verified during this evaluation and marked obsolete in the backlog.

## Requirements

- **R-1**: One predicate decides whether a recorded run is live, and it reads
  positive evidence: a recorded returncode settles it; otherwise the PID must be
  held by a process whose own start time is not later than the run's recorded
  `started`. Historical bare `os.kill(pid, 0)` checks across callers are replaced
  by `is_run_alive` in `src/aet/liveness.py`.
- **R-2**: The run lease is reclaimable whenever its owning run is not live under
  R-1, so a crashed run whose PID has been recycled cannot refuse every mutating
  queue command.
- **R-3**: `derive_status` does not return `in_progress` from branch existence
  alone. It requires the same class of positive evidence the `merged` path was
  given by ADR-064; a branch sitting at its base with no recorded session derives
  as an unstarted task.
- **R-4**: `aet ship merge` runs its gate, conflict detection and commit-count
  checks against the tree it will merge, not against the ambient checkout, so
  the command cannot report "gate passed" about a tree it is not merging.
- **R-5**: A verdict field that gates a stage is value-checked, not only
  type-checked. A well-formed payload carrying a placeholder `summary` is
  refused where the `verdict` enum is already enforced.
- **R-6**: Triage does not return a decision when its evidence set is empty. With
  no stage, no signature and no tail, it falls through to the deterministic
  classifier default rather than answering from the class label.
- **R-7**: A known-intermittent test is marked as such, so `0 failed` from
  `make validate` means no red is being discounted; and a gate script that is red
  and invoked by nothing is removed rather than left tracked.
- **R-8**: A count of zero and an unscanned bucket do not render identically, in
  `aet mine-learnings` and `aet retro`; and a ranking does not present a field of
  ties as a field of firsts.

## User Stories

- As an operator reading `aet status`, I want the active-run list to show runs
  that are actually running, so that a stale board does not hide a real one
  (satisfies: R-1)
- As an operator whose batch crashed, I want the next queue command to work
  without `--force`, so that recovering does not require the flag whose own
  warning says it can corrupt a live run (satisfies: R-1, R-2)
- As an operator whose task failed with its branch left behind, I want the board
  to show it as unstarted rather than in progress, so that `aet state reset`
  clears it instead of stranding it (satisfies: R-3)
- As an operator merging from any checkout, I want "gate passed" to be a
  statement about the tree being merged (satisfies: R-4)
- As a reviewer trusting ADR-019's fail-closed verdict, I want a placeholder
  attestation refused, so that the strongest guarantee in the pipeline does not
  rest on a type check (satisfies: R-5)
- As an operator running an unattended batch, I want a failure with no evidence
  to take the deterministic default rather than an agent's guess (satisfies: R-6)
- As anyone reading a green gate, I want green to mean green (satisfies: R-7)
- As anyone reading a report of zeros, I want to know whether nothing happened or
  nothing was looked at (satisfies: R-8)

## Acceptance Criteria

- [ ] A run directory whose recorded PID is held by a process started after the
      run's `started` timestamp is reported as not live by every consumer
      (satisfies: R-1)
- [ ] A run directory with a `returncode` file is not live regardless of PID
      state (satisfies: R-1)
- [ ] A lease whose owning run is not live is reclaimed without `--force`
      (satisfies: R-2)
- [ ] A task with a branch at its base and no recorded session does not derive
      `in_progress` (satisfies: R-3)
- [ ] `aet ship merge` run from a checkout that is not the feature branch either
      gates the correct tree or refuses; it never reports a passing gate for a
      tree it is not merging (satisfies: R-4)
- [ ] A verdict payload with a placeholder `summary` is refused by
      `validate_verdict` (satisfies: R-5)
- [ ] A triage request with empty stage, signature and tail does not produce an
      agent-authored action (satisfies: R-6)
- [ ] `tests/` marks each of the three known intermittent failures, and
      `scripts/test-merge-verified-removed.sh` is gone (satisfies: R-7)
- [ ] `aet mine-learnings` and `aet retro` render distinguishably against an
      empty archive and against a scanned archive that matched nothing
      (satisfies: R-8)

## Technical Notes

`src/aet/liveness.py` already exists and is the home for R-1's predicate. Its
`_all_processes()` establishes the portability pattern this repo accepts —
`/proc` when present, `ps` as the fallback, an empty result rather than a crash
when neither answers. A process start time is reachable the same way
(`/proc/<pid>/stat` field 22, or `ps -p <pid> -o lstart=`), so R-1 needs no new
dependency. Note that the module's existing classes serve a different question —
whether an agent *session* is doing work — and R-1 is about whether a *run
process* is the one recorded. They share a file, not a definition.

R-3's evidence test already exists: `branch_has_own_commits(branch, base_commit)`
was added for the `merged` path by the ADR-064 follow-up and is called at
`derive_status` and `resolve_merge_commit` in `src/aet/cli/aet_state.py`. The `in_progress` branch of the same
function was not given it.

R-4 should gate inside `_merge_into_target`'s worktree
(`src/aet/cli/ship.py`), which already creates or reuses one for the target
branch. That preserves the checkout independence `_resolve_feature_branch` was
deliberately built for, rather than adding an operator precondition.

R-5 belongs in `validate_verdict`, alongside the `verdict` enum check, not in
`evidence.SCHEMAS` — the schema map is `dict[str, dict[str, type]]` by
construction and expressing a value constraint would change its type.

R-6 must not be implemented by having the agent refuse; the agent is what has no
evidence. The check belongs before the session is spawned.

## Open Questions

- Does R-1's predicate need to tolerate a PID whose start time is unreadable
  (a permissions failure on a foreign PID)? Fail-live and warn, or fail-dead?
  Fail-dead risks two orchestrators, fail-live risks the stuck lease this PRD is
  removing. Leaning fail-live-with-diagnostic, since the lease is reclaimable by
  an explicit operator action and a double-spawn is not.
- R-7 marks the loadgroup failure without diagnosing it. That failure is a lost
  compare-and-swap in `GitRefsBackend.save`. Whether a real concurrent batch can
  lose a task-record write the same way is unanswered; if it can, this stops
  being test hygiene and becomes a second route into the loss class that
  `20260828-fetch-discards-unpushed-record-writes` closed by replication. Marking
  it must not be read as closing that question.
- Should R-5's placeholder check be a fixed deny-list ("pending", "todo", "n/a",
  empty) or a minimum-substance rule? A deny-list is honest about being a
  heuristic; a length rule invites a longer placeholder.
