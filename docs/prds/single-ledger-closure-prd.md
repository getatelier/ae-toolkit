# PRD: Single-Ledger Closure — Mechanical Closure on a Commutative, Repo-Traveling Ledger

## Overview

Eight stores answer "is it done?" today (plan frontmatter `status`, plan
footer `*Stage:*`, queue `state`/`stage`, `work-history.jsonl`, the git-refs
ledger, git ancestry, verdict files), and five merged plans currently
resurrect as `queued` because two of those stores disagree inside the same
file. The structural review traced this to a single generative cause:
mechanical closure duties live in prose, and prose is a probabilistic
executor — the orchestrator itself asks the stage agent to write the plan
footer in `src/aet/cli/orchestrator.py` while
plan footer updates sat wired only to terminal
closure. The beads evaluation then broke the review's own durability
correction: rev 4 put queue and history in `~/.aet/{slug}/`, which does not
survive configuration 2 (one operator across a laptop and a cloud box).

This PRD ratifies the review's item 1 with its two corrections absorbed
(steal 01, rev 8): **one append-only, content-addressed provenance ledger,
carried as pushed git refs, with closure executed as a single code
transaction.** It builds directly on the merged `local-only-plans` work
(lop-01/02/03), which already made plans local-only and durability deferred
to the PR — this PRD changes where state lives and who writes it, not the
intake/hygiene/seeding posture lop shipped.

Intake triage: feature/enhancement (structural state-model change), not a
reproducible defect — the five-plan drift is the motivating evidence, and
patching those five files is explicitly out of scope (the fork: the fix and
this PRD are mutually exclusive work).

## Goals

- Settled-ness has exactly one authoritative home: the ledger. "Is it done?"
  is answered by ledger + git ancestry, nothing else.
- Every terminal and stage transition is written by code in one transaction;
  no skill or orchestrator prompt instructs an agent to mutate plan status,
  footer, or queue state.
- Queue and ledger state travels with the repository via pushed
  `refs/aet/*`, so one operator across several machines (and several
  operators on one repo) see the same state; config, telemetry, and reports
  stay machine-local in `~/.aet`.
- Concurrent appends from independent writers merge without conflict by
  construction — commutative inserts, no chained hash over a set.
- The store count for "is it done?" collapses from 8 to 3 (traveling
  ledger, git ancestry, write-only telemetry archive), and the mechanism
  that policed the redundant stores is deleted with them.

## Non-Goals

- **No adoption of beads** or any external database/sync layer. The
  transport is the GitHub remote every AET project already has.
- **No leases, claims, heartbeats, or cross-operator arbitration** (steal
  07, rejected on standing policy): configuration 2 is a sequential handoff
  the operator directs, not two machines contending for a frontier.
- **No adapter/session-interface rewrite** (review item 2 — held until the
  ledger it reports into exists).
- **No union-type task record** (negative lesson from beads' 60-field
  `Issue` struct): the ledger schema stays narrow; verdicts, evidence
  paths, gate payloads, and skill bindings are NOT absorbed into it — they
  remain files the ledger references by hash.
- **No change to the lop posture**: plans still go from `aet sprint add` to
  merged PR without intermediate commits; intake, base hygiene, branch
  seeding, and worktree materialization are untouched except where they
  read the dying `status` field.
- **No deletion of the plan footer.** The footer survives as a pure
  human-readable breadcrumb — now maintained by code, for free.
- **No patching of the five drifted plans.** The defect class dies with the
  mechanism; the individual files are irrelevant once frontmatter `status`
  has no readers.
- **No multi-agent live frontier** with sub-minute freshness — that is the
  stated reopen condition for beads, and nothing in the four deployment
  configurations asks for it.

## Requirements

- **R-1**: The ledger is the sole settled-ness authority. Plan frontmatter
  `status` is removed from the plan contract: new plans carry no `status`
  key, `init-queue` (and any other reader) no longer derives settled-ness
  from plan frontmatter, and `aet plans lint` treats a live `status` field
  as an error. This voids ADR-034; ADR-055 records it.
- **R-2**: Ledger events are content-addressed and idempotent. Event ids
  derive deterministically from `source:task:kind:(ref | occurred_at)`;
  duplicate writes are harmless no-ops (INSERT-IGNORE semantics). An event
  recorded without an external ref must carry an explicit caller-supplied
  `occurred_at` — never minted from the wall clock — enforced at the store
  boundary so every caller is covered. A reserved `ingest-backfill` source
  is rejected by the write path so readers can filter reconstructed events.
- **R-3**: Concurrent appends commute. The union of event rows is the
  correct merge regardless of writer or order. The envelope's chained
  content hash — non-commutative by
  construction over a changing task-ref set — is removed from the
  operational path; the `StampMismatch` refusal it powers goes with it.
- **R-4**: State travels with the repo. Queue and ledger live as git refs
  (per-task blobs at `refs/aet/tasks/<id>`, envelope at
  `refs/aet/meta/queue` — both already the default backend's layout) and
  are pushed to/fetched from origin: fetch at run/session start, push after
  mutation. Push is best-effort and offline-tolerant — a failed push never
  blocks local operation and is retried at the next boundary; closure
  (`aet ship`) is the one boundary where a push must succeed or fail
  loudly. Config, telemetry, and reports remain in `~/.aet` and are never
  pushed.
- **R-5**: Closure is one code transaction. `aet ship` close writes, in a
  single code path: footer breadcrumb update, queue stage transition, and
  the terminal ledger events (including the R-8 digest). Every flow that
  reaches a terminal state routes through this path — the invocation-drift
  hole (flows that never ran the code closure) is closed structurally, and
  the orchestrator's prompt-delegated footer duty
  in `src/aet/cli/orchestrator.py` is deleted from the prompt template.
- **R-6**: `aet state set-stage` owns mid-pipeline footer atomicity: the
  footer write and the queue stage write happen in one code path via the
  existing `update_plan_footer()` primitive, replacing the prompt
  instruction. The footer flip is part of `aet gate submit`'s success path,
  so "footer only after verdict" is structural rather than documented.
- **R-7**: `aet gate submit` builds verdict payloads in code
  (`--from-pytest`, `--summary`, `--divergence` per the prose-to-code
  study §3.1.2), and the hand-constructed verdict-JSON fallback
  instructions in the four stage skills (aet-qa, aet-review, aet-cso,
  aet-sync-docs) are deleted in the same change.
- **R-8**: Closure records a permanent digest event: the plan's content
  hash, its PRD requirement ids, and the merge ref. "What was the plan for
  this merge?" stays answerable from ledger + PRD + diff after the plan's
  status fields are gone.
- **R-9**: The redundancy-policing mechanism is deleted with the
  redundancy: plan drift detection, the footer↔status validator, and the
  "footer is only a breadcrumb" defenses built around prose duties
  failing. `aet status` reports ledger↔git- ancestry consistency only.
- **R-10**: Every document that instructs or describes the superseded
  behavior is corrected in the same change (lop R-10 precedent): the
  completion-protocol and footer-write duties across the skills corpus
  (~19 duty instances across 10 skills per the study), `AGENTS.md`,
  `CONTEXT.md` (the eight-store glossary and flagged-ambiguities section
  collapse), and new operator guidance for the multi-machine refs posture
  (state travels via origin; a fresh clone fetches it).

## User Stories

- As an operator working across a laptop and a cloud box, I want queue and
  ledger state to travel with the repo, so that the cloud box sees which
  plans already ran and the laptop sees what happened overnight
  (satisfies: R-3, R-4).
- As an operator merging a task, I want closure to be one code transaction,
  so that a plan can never end up footer-merged but queue-queued again
  (satisfies: R-5, R-8).
- As an operator running staged pipelines, I want the footer written by the
  engine at each stage transition, so that an interrupted or forgetful
  session cannot drift the plan file (satisfies: R-6, R-7).
- As an operator on a fresh clone, I want settled work to stay settled, so
  that `init-queue` never resurrects merged plans (satisfies: R-1, R-4).
- As a reviewer of the toolkit's own ADR trail, I want the eight-store
  glossary gone, so that the next structural question has one place to
  look (satisfies: R-1, R-9, R-10).

## Acceptance Criteria

- [ ] A plan file with `status: queued` in frontmatter and `*Stage: merged*`
  in its footer is NOT re-queued by `init-queue`; settled-ness comes from
  the ledger, and `aet plans lint` flags the frontmatter field (satisfies:
  R-1).
- [ ] Two clones each append events to the ledger offline; after both push,
  fetching produces the union of events with no conflict and no manual
  reconciliation (satisfies: R-2, R-3, R-4).
- [ ] Recording the same event twice (same source, task, kind, ref) is a
  no-op — the second write changes nothing (satisfies: R-2).
- [ ] An event submitted without a ref and without an explicit
  `occurred_at` is rejected at the store boundary, regardless of which CLI
  command originated it (satisfies: R-2).
- [ ] With the network unavailable, a stage transition completes locally
  and the push is deferred; at `aet ship` closure, a failed push fails the
  closure loudly with a named remedy (satisfies: R-4).
- [ ] `aet ship` close on a task whose footer was never touched by any
  agent succeeds and leaves footer, queue, and ledger mutually consistent
  in one transaction; killing the process mid-transaction leaves no partial
  state (satisfies: R-5, R-8).
- [ ] The orchestrator's stage prompt contains no footer/status/queue
  mutation instruction, and a mid-pipeline stage transition updates the
  plan footer with no agent action (satisfies: R-5, R-6).
- [ ] A footer write attempted before its gate's verdict is structurally
  impossible — it only exists on `aet gate submit`'s success path
  (satisfies: R-6).
- [ ] `aet gate submit --from-pytest` (and `--summary`, `--divergence`)
  produces a verdict payload the gate accepts; the four stage skills no
  longer document hand-built verdict JSON (satisfies: R-7).
- [ ] `grep -rn "update the plan footer\|footer.*breadcrumb\|drift"
  src/aet skills/` returns only the code that owns the writes — the prompt
  duty, validator, and drift detector are gone (satisfies: R-5, R-9, R-10).
- [ ] `aet status` on a fresh clone of a repo with pushed `refs/aet/*`
  reports the same queue state as the machine that pushed it (satisfies:
  R-4, R-10).

## Technical Notes

- **Verified facts this design relies on** (2026-08-09 trace):
  `git_refs_backend.py` already stores per-task blobs at
  `refs/aet/tasks/<id>` with the envelope at `refs/aet/meta/queue`, updates
  atomically under git's ref locks, skips unchanged blobs so concurrent
  writers touching different tasks never clobber each other — and its own
  docstring states "Nothing here pushes `refs/aet/*`: the backend is
  local-only by default" and documents the chained `content_hash` (ewl-05).
  The beads evaluation's finding stands: the backend is two changes from
  being the answer (push; replace the non-commutative chain with
  content-addressed events).
- **Closure primitives already exist**: plan footer update primitives
  are tested and wired only to terminal closure; `aet state set-stage` (`src/aet/cli/state.py`) writes the
  queue stage but not the footer. The work is wiring and deleting prose,
  not new mechanism — the study sizes T1's closure duties at M.
- **What the ledger does NOT hold**: verdicts, evidence, gate payloads,
  telemetry. `work-history.jsonl` stays write-only telemetry in `~/.aet`
  (rev 5 stands): written, never loaded or verified by operational
  commands. The beads evaluation's SRP point applies — provenance events
  and the field-mutation audit trail are separate tables.
- **Envelope schema**: add a schema-version field from the first commit
  (cheap insurance; the full schema-version guard with actionable error is
  steal 06, tier 2, out of scope here).
- **ADR trail** (mandatory per AGENTS.md): **ADR-055**, authored during
  scope validation. It voids ADR-034 (no plan-frontmatter signal remains),
  revises ADR-054's durability revision (queue/ledger move from
  operator-local `~/.aet` to pushed git refs — the rev-8 correction), and
  records the commutative-writes requirement and the standing refusal of
  lease/arbitration machinery. ADR-034 and ADR-054 are not edited in place.
- **Deployment configurations** (the ground truth, from the beads
  evaluation): every AET project has a GitHub remote. Config 1 (one
  operator, one machine) needs nothing new; config 2 (one operator,
  several machines) demands state travel with the repo; config 3 (several
  developers, one using AET) demands state stay out of the source tree and
  PR diffs — refs satisfy this; config 4 (several AET users) adds
  concurrent writers, which R-2/R-3 make safe.
- **Shadow-config consumer projects**: `refs/aet/*` live in the client
  repo's origin — visible to anyone with repo access but present in no
  working tree and no PR diff. Queue state is not secret; this matches the
  shadow-config goal of keeping AET machinery out of client source trees.

## Open Questions

- **Event taxonomy**: the exact `kind` set for AET (stage transitions,
  verdict refs, claims, closure digest) — beads' {cut, claim, suspend,
  resume, handoff, commit, land, used} is the starting point, trimmed to
  what AET's pipeline actually emits.
- **`work-queue.json`'s role**: projection of the refs store (rebuilt on
  read) vs. replaced by direct ref reads. Performance argues for a
  projection; the single-source principle argues against a second live
  store. Resolve at scope validation.
- **Cutover**: do existing queue entries and `work-history.jsonl` get a
  one-time `ingest-backfill` into events, or does the ledger start empty
  with live tasks re-cut? Backfill fabricates provenance nobody observed;
  an empty start loses in-flight context mid-sprint.
- **Push cadence granularity**: push on every mutation vs. batch at stage
  boundaries (closure excepted, which must push). Trade-off is offline
  tolerance vs. cross-machine freshness.

## Risks

- **The ledger becomes a ninth store**: if verdicts, evidence paths, or
  gate payloads migrate into it, causes 2 and 6 survive with a database
  underneath — the exact objection that killed beads. Mitigated by the
  Non-Goals (narrow schema, references-by-hash only) and the union-type
  negative lesson applied to the task record.
- **Removing the chained hash loses tamper evidence**: accepted. Rev 5's
  operator testimony stands — the integrity apparatus created the failures
  it guarded against — and under configurations 2/4 the chain is not
  merely unwanted but unworkable (non-commutative by construction).
- **Refs push couples local operation to the network**: mitigated by R-4's
  offline-tolerant posture everywhere except closure, which already
  requires pushing the merge.
- **Multi-machine operators are a new tested surface**: the rehearsal gap
  (review item 8) means refs sync could ship unexercised in the
  configuration that needs it most. The validation strategy must include a
  two-clone fixture test, not just unit tests.
- **Skills drift underneath consumer projects**: the symlinked skills keep
  instructing prose writes until R-10 lands; the PRD's same-change
  requirement is the mitigation, and it is why R-10 is a requirement, not
  a follow-up.

## Resolved at Scope Validation (2026-08-09)

- **Event taxonomy** — resolved: `kind` ∈ {`cut`, `stage`, `verdict`,
  `land`}; `land` carries the R-8 digest payload (plan content hash, PRD
  R-ids, merge ref). `ref_kind` ∈ {`git-sha`, `pr`, `plan-hash`,
  `evidence-path`}. Beads' {suspend, resume, handoff, commit, used} are
  dropped: no leases (no claim lifecycle), and commit/usage telemetry is
  the telemetry archive's job, not the ledger's.
- **`work-queue.json`'s role** — resolved: unchanged. It remains the
  JSON-backend file; the git-refs backend (already the default) is the
  authoritative store, and this PRD makes it the *synced* store. No new
  projection/cache layer is built — the backend interface already
  abstracts the read path.
- **Cutover** — resolved: the ledger starts empty. Each live queued task
  gets one `cut` event minted at migration with `occurred_at` taken from
  the task record (satisfying the caller-owned-timestamp rule).
  `work-history.jsonl` is NOT backfilled — it is write-only telemetry, and
  backfilling fabricates provenance nobody observed. The `ingest-backfill`
  source stays reserved and unused.
- **Push cadence** — resolved: push at each state-mutating command boundary
  (sprint add, set-stage, gate submit, ship), not per micro-mutation;
  closure is the only boundary where push is mandatory. Fetch at the start
  of operational commands that read or write queue state.
- **CONTEXT.md timing** — resolved: CONTEXT.md is deliberately NOT updated
  at scope validation. It must describe code as it is; the term rewrite is
  slc-06's job, sequenced after the behavior lands. The resolved terms live
  in ADR-055 until then.
- **ADR trail** — resolved: ADR-055
  (`docs/adr/055-settled-ness-in-commutative-ledger.md`) authored. It voids
  ADR-034, supersedes ADR-054's revision of ADR-034 decision 3, revisits
  ADR-011's event-sourcing rejection, and records the standing refusal of
  lease machinery.
- **UI Coverage Lens** — not applied: CLI-only change, no user-facing
  interface.

## Divergence Summary — slc-06

*Recorded: 2026-08-10 — Branch: slc-06-doc-sweep-operator-guidance*

The slc-06 implementation slice (R-10) matches the planned behavior. The
doc sweep updated the documents that describe or instruct the superseded
status/footer-write behavior, plus operator guidance for the multi-machine
refs posture.

### Added (unplanned)

- `docs/PIPELINE.md` and `docs/WORKFLOW-github.md`: updated to reflect the
  pushed-`refs/aet/*` state model and the new multi-machine operator posture.
  These files were not listed in the plan's "Files to Modify" but contained
  stale references to the old `status`/`footer` workflow.
- `skills/aet-work/references/{context-isolation,queue-commands,reconcile,
  upgrading-existing-project}.md`: updated as part of the R-10 corpus sweep
  for stale status/footer-write duties and multi-machine guidance. The plan
  named `skills/aet-work/SKILL.md` but not the reference docs.

### Deferred

- Merge to `main` and integration verification: remains for the `aet-ship`
  stage.

No meaningful behavioral divergences were introduced.

## Divergence Summary

*Recorded: 2026-08-10 — Branch: slc-05-set-stage-gate-submit-atomicity*

The slc-05 implementation slice (R-6, R-7) matches the planned behavior.
The following file-list expectations from the plan did not require modification:

### Changed from plan

- `src/aet/queue.py` was not modified. `update_plan_footer()` already existed
  in the queue module and satisfied the atomic footer write without changes.
- `skills/aet-work/references/migration-aet-state.md` was not modified. The
  stale-`failure_reason` reactivation rule was folded into the
  `cmd_set_stage` docstring/comment instead of a separate migration doc edit.
- Tests landed under `tests/gate/test_gate_submit.py` and
  `tests/state/test_aet_state.py` rather than `tests/cli/*`, following the
  project's existing directory conventions for gate and state tests.

No meaningful behavioral divergences were introduced.

<!-- aet-lint: off -->
## Divergence Summary — slc-04

*Recorded: 2026-08-10 — Branch: slc-04-mechanical-closure-transaction*

The slc-04 implementation slice (R-5, R-8) matches the planned behavior.
The closure transaction is implemented in `aet_state._apply_transition` and
`cmd_record_merge`, not in `src/aet/cli/ship.py`.

### Changed from plan

- `src/aet/cli/ship.py` was not modified. `aet ship close` already delegates
  to the record-merge closure path; the single-transaction logic landed in
  `src/aet/cli/state.py`.
- Atomic ref updates required modifying `src/aet/backends/git_refs_backend.py`
  (single `git update-ref --stdin` transaction), which was not listed in the
  plan's file list.
- Tests also landed in `tests/backends/test_git_refs_backend.py` for the
  atomic-save failure path, in addition to the planned
  `tests/cli/test_ship_close.py` and `tests/orchestrator/test_orchestrator.py`.

### Deferred

- Merge to `main` and integration verification: remains for the `aet-ship`
  stage.

No meaningful behavioral divergences were introduced.
<!-- aet-lint: on -->

---

*Stage: synced*
*Next step: run `aet-ship`*
