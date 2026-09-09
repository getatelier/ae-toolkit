---
subject: ephemeral-sprint-board
---

# Work Queue Is an Ephemeral Sprint Board, Plans Are the Source of Truth

## Status

Accepted. Revises ADR-011 (Forward-Only Deterministic Work State).

## Context

ADR-011 established that workflow state is recorded forward and trusted on read. It solved the squash-merge resurrection bug by recording `merge_commit` at write time and partitioning the live queue from settled history. However, it kept `.agents/work-queue.json` and `.agents/work-history.jsonl` as tracked files in the repository.

That choice has become a daily friction point:

- **Runtime state pollutes the working tree.** Every queue mutation (stage transition, `record-merge`, `sync`) shows up as an uncommitted change. The orchestrator's own main-hygiene check treats the queue mutations it just wrote as a dirty working tree and halts (`aet-work` run getting stuck).
- **Commit noise.** Queue and history files are often the only changed files in a commit, mixing runtime bookkeeping with meaningful work.
- **Auto-sync is over-eager.** `aet-work sync` scans every `docs/plans/*.md` and adds new ones to the queue automatically. A project can have many approved plans that are not yet meant to be worked on; the queue should reflect intentional curation, not every file on disk.
- **Duplicate responsibility.** `aet-ship` verifies merges, but the queue still needs a separate `record-merge` step. The boundary between shipping and queue management is unclear.

The underlying insight is that two different concerns were forced into one artifact:

1. **Permanent record of intent and outcome** — what the work is and what happened to it.
2. **Ephemeral scheduling state** — what the agent is working on right now.

Plan files already serve concern #1. The queue file should serve only concern #2.

## Decision

The work queue becomes an **ephemeral, gitignored sprint board**. Plan files remain the durable source of truth for intent, stage, and terminal closure.

1. **`.agents/work-queue.json` is gitignored.** It holds only the current sprint: tasks that are `planned`, `ready`, `in_progress`, or `awaiting_merge`. It is rebuilt or curated by the user as needed and is not source-controlled.
2. **Plan files are the source of truth.** A task is considered closed only when its `docs/plans/{id}.md` file says so (via frontmatter `status` and/or terminal stage footer). The plan file is updated once at completion and then frozen.
3. **`.agents/work-history.jsonl` remains an optional, gitignored execution log.** It provides centralized transition history, timing, and evidence for project-management reporting. Projects may omit it entirely. It is not used to determine whether a task is closed.
4. **No automatic sync from plans to queue.** New plans are not added to the queue unless the user explicitly adds them with `aet-work add`.
5. **`aet-work review` scans plans without mutating the queue.** It reports approved, queued, in-progress, and closed plans so the user can decide what to add to the sprint.
6. **`aet-ship` owns closure.** After verifying that a task's commit is on `origin/main`, `aet-ship` updates the plan file to terminal status, appends the closure to the execution log, and removes the task from the queue.
7. **Forward-only state within the sprint.** While a task is in the queue, transitions remain deterministic and append-only, as in ADR-011. The difference is that the queue is discarded after closure rather than archived as a permanent record.

## Consequences

- **Easier:** The working tree no longer contains runtime state; `aet-work run` stops tripping over its own queue writes.
- **Easier:** No more "commit only these two files" noise.
- **Easier:** The queue reflects intentional curation. Approved plans can coexist without being forced into the active sprint.
- **Easier:** Closure has one owner: `aet-ship`. There is no separate `record-merge` step for the user to remember.
- **Harder:** Queue state is local to the machine/session. Switching machines means rebuilding the sprint with `aet-work review` + `aet-work add`. Mitigated by the fact that plan files carry all durable state.
- **Harder:** `aet-ship` becomes load-bearing for closure. If it is not run after a merge, the plan stays open and the queue entry lingers. This is acceptable because `aet-ship` is already the natural place where merge verification happens.
- **Harder:** Reporting that relies solely on the execution log must tolerate the log being absent or gitignored. Cross-project analytics may need to scan plan files instead.

## Alternatives Considered

1. **Keep the queue tracked and fix the hygiene check.** Rejected: it preserves commit noise and does not solve the auto-sync or closure-ownership problems.
2. **Derive queue state entirely from plan files + git on every read.** Rejected: it cannot track in-progress stage without side effects, cannot coordinate parallel agents, and makes every command expensive.
3. **Store the queue in a separate repository or database.** Rejected: it adds infrastructure and conflicts with the toolkit's local-first, agent-agnostic design.
4. **Move execution history into plan files.** Rejected after discussion: while plan files do record terminal status, scattering full transition history across many plan files makes reporting harder and couples audit trail with intent documents. A centralized, optional, gitignored log keeps both concerns clean.

## Relation to ADR-011

ADR-011's core principle — state is recorded forward by code and trusted on read — remains valid within the sprint. What changes is the scope of the record:

- ADR-011 treated `.agents/work-queue.json` and `.agents/work-history.jsonl` as durable, tracked artifacts.
- This ADR narrows the queue to an ephemeral sprint board and moves terminal truth into plan files.

The single-writer chokepoint (`aet-state transition`), the forward-only lifecycle, and the live/settled partition are preserved; only the storage and lifetime of the artifacts change.
