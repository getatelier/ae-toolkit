# PRD: GitHub Issues as the Team Backlog (Forge Projection)

## Overview

Teammates are expected to start using AET, and the owner works from more than one environment (local machine and cloud). The backlog needs to live somewhere both can see, and the owner's goal is to manage it in GitHub Issues while PRDs and plans stay versioned as files.

The blocker is not the GitHub machinery — that already exists in `aet-work/lib/backends/github_backend.py` and has **never run**. `_create_issue()` is unreachable (`bin/sync` hardcodes `sync_task(task, is_new=False)`; `bin/add` never calls it; `is_new=True` appears only in tests). `ensure_labels()` is never invoked. And the only way to reach any of it is `task_backend: "github"`, whose `load`/`save` read and write the local JSON queue — so selecting "GitHub" silently costs the git-refs ledger `ewl-04` made the default. The value that would mean "git-refs *and* GitHub", `task_backend: "both"`, is `raise NotImplementedError`. The clincher: `nsr-02` added `quarantined` to `STATES` on 2026-07-16 and `STATE_LABELS` never learned it — a quarantined task would project unlabeled, and no test caught it, because nothing calls the code.

The deeper blocker is that **sprint membership currently lives only in a gitignored local file.** `aet add` curates `.agents/work-queue.json`, which never leaves the machine. So a second environment cannot see what was scheduled, and no amount of mirroring fixes that — you would be projecting a truth that only one machine holds.

This PRD makes membership **versioned**: plan `status` becomes the record of where a plan sits in its lifecycle, every status-writing command commits and pushes it, and the queue is *derived* from committed status rather than curated locally. GitHub Issues then becomes a faithful one-way mirror of something every clone already agrees on. `aet run` behaves identically on a laptop or in the cloud after a `git pull`, with no inbound reads and no forge in the trust path.

### Scope boundary (owner, 2026-07-17)

AET's unit is **one plan, one operator, executed fully**. Someone plans; one person takes a single plan and sees it through. Whether two people might grab the same plan is a *project-management* concern, not the engine's — if management is sloppy things get messy, but minimal care from each engineer is the assumption AET is designed on. This PRD therefore contains no claim-checking, locking, or cross-operator arbitration. The deliverable includes a **documented workflow engineers follow**, not machinery that polices them.

**Nothing writes to GitHub except AET.** Issues are created by `aet add`, never by hand. Humans do not relabel, close, or file issues. The single human decision in the whole loop is promoting a plan into the sprint, and that is an AET command like any other. Where a problem looks like coordination but actually breaks a *single* operator across two environments (R-8, closure not pushing), it is in scope.

**Intake triage:** feature/enhancement, with three defects folded in as prerequisites. The unreachable creation path and the `quarantined` label gap are invisible today — nobody can reach the projection to observe them — and both die when this feature makes the code live. The closure-push gap (R-8) and the ADR-013/`init-queue` contradiction (R-7) are genuine pre-existing defects, fixed here by owner decision on 2026-07-17 because the board is wrong without them.

## The workflow

The contract this PRD exists to deliver. Every step is a command; every status change is committed and pushed; GitHub only ever receives.

Commands are noun-scoped: with two destinations (board, sprint), the destination is the noun and `add` the verb under it. Top-level `aet add` is retired (clean cut, no alias), replaced by `aet sprint add` — following the existing `aet state <sub>` nesting pattern.

```
1. aet-pipeline-plan  →  docs/plans/foo.md  (status: draft)  →  committed
                         not on the board yet

2. aet backlog add docs/plans/foo.md          "put it on the board"
     → commits + pushes the plan's status
     → creates issue #N (keyed by plan id), labeled by status:
         status: draft     → aet:draft
         status: approved  → aet:backlog

3. aet sprint add docs/plans/foo.md   ← the only human decision
     → status: queued, committed + pushed
     → AET computes the DAG and labels #N  aet:ready  or  aet:blocked

4. aet run          (laptop or cloud — identical)
     → git pull → queue derived from committed status → runs what AET marked ready
     → transitions relabel #N  (aet:in-progress → aet:awaiting-merge)

5. ship → merge → record-merge
     → status: merged, committed + pushed
     → closes #N
```

`aet sprint add` records the human's decision ("work on this") — it keeps the exact meaning today's `aet add` has (approved plan → Work Queue, per CONTEXT.md), only renamed into the noun-scoped surface. AET still computes `ready` vs `blocked` from `blocked_by` in plan frontmatter, so no label ever carries a fact the system derives.

## Goals

- **G1**: The backlog and sprint are visible in GitHub Issues, written only by AET, mirroring a state every clone already agrees on.
- **G2**: Sprint membership is versioned, so `aet run` behaves identically from any environment after a pull — no gitignored file holds a truth the team needs.
- **G3**: Projections are an orthogonal config axis, extensible to other forges later, rather than a storage-backend value. No configuration can make a forge authoritative.
- **G4**: A projection outage can never block, corrupt, or fail a ledger write.
- **G5**: The decisions and the workflow are on the record, including the shelving of roadmap Phase 6.

## Non-Goals

Each carries the trigger that would re-open it, so none of these is vapor.

- **Claim-checking, locking, or coordination between operators.** Out of scope by design, not deferred — see the scope boundary. No trigger; this is a management convention.
- **Humans writing to GitHub.** Filing, relabeling, or closing issues by hand is outside the workflow. The projection assumes it is the only writer; R-17's reconcile reports drift rather than defending against it.
- **Inbound reads of any kind.** AET never queries GitHub to decide what to do. Trigger: none foreseen — versioned status removes the reason.
- **Assignees, priorities, or two-way field sync.** The issue reflects the plan; the plan never reflects the issue.
- **Azure DevOps work items.** The axis takes a second projection type later, but no adapter is built. Trigger: a live ADO project running AET (ADO is prospective as of 2026-07-17).
- **Backfilling the 121 legacy plans.** Grandfathered as settled (R-6). Trigger: wanting historical work as closed issues — a separate migration.
- **Shared-ledger transport, orphan sync branch, event-log ledger, server-side branch protection.** Roadmap Phase 6, whose premise was coordination. Shelved to Phase 9 by R-18.
- **PRDs and plans in GitHub.** They stay versioned in `docs/` (ADR-013; doc 10's 2026-07-12 correction).
- **`aet-ship` forge portability** (`gh pr create` / `gh pr view`). Untriggered while every live repo is GitHub. Recorded as a Phase 9 trigger.

## Requirements

### Config and fences

- **R-1**: Projections are configured on an axis orthogonal to `task_backend`, so a git-refs ledger and a GitHub Issues projection are active simultaneously.
- **R-2**: `task_backend: "github"` and `task_backend: "both"` are removed. No configuration value can select a forge as storage.
- **R-3**: `aet-setup` writes projection config and no longer offers a forge as a `task_backend` value.

### Fail semantics

- **R-4**: A projection failure — `gh` absent, unauthenticated, network down, API error, rate limit — never fails or blocks the ledger write or status commit it accompanies. It warns on stderr and the command succeeds.
- **R-5**: Storage writes remain fail-closed. The fail-open rule is scoped to projections only and does not weaken any existing gate.

### The liveness contract — versioned, and it travels

- **R-6**: `status` is a required, validated plan frontmatter field over the canonical lifecycle `draft → approved → queued → in_progress → awaiting_merge → merged|abandoned` (CONTEXT.md), written as `status: draft` at plan creation and advanced to `approved` by `aet-validate-scope` (the approval gate). A plan with no `status` field is treated as settled, grandfathering the legacy corpus. "Live" means: has a `status` field, and it is not terminal.
- **R-7**: Settled-ness is derived from versioned plan data, not from the gitignored `.agents/work-history.jsonl`, resolving the contradiction between ADR-013 decision 3 and `init-queue:257`.
- **R-8**: Every command that writes plan status commits **and pushes** it — `aet add`, `aet sprint`, and `record-merge`. Today `record-merge` commits (`cmd_record_merge` in `src/aet/cli/aet_state.py`) and stops; only `aet-ship`'s prose pushes, so desk-driven closure leaves `status: merged` local-only. A push failure is surfaced and recoverable; it never loses the local commit or half-closes the task.
- **R-9**: Queue membership is derived from committed plan status, not curated in a local-only file. After a `git pull`, `aet run` selects the same work in any clone.

### The commands

- **R-10**: `aet backlog add <plan>` puts a plan on the board: it commits and pushes the status, then creates exactly one issue keyed by plan id, labeled `aet:draft` or `aet:backlog` per the plan's status.
- **R-11**: `aet sprint add <plan>` promotes a plan into the sprint — the only human scheduling act, preserving today's `aet add` semantics (approved → Work Queue). It sets `status: queued`, commits and pushes, and relabels the issue to the DAG-computed `aet:ready` or `aet:blocked`.
- **R-12**: `ready` and `blocked` remain computed from `blocked_by`; neither is ever set by a human or read from a label.
- **R-19**: Commands are noun-scoped. Top-level `aet add` is retired (no alias); `aet sprint` and `aet backlog` become command groups with an `add` subcommand each, following the `aet state <sub>` nesting pattern. Skills-lint and the canonical docs (CONTEXT.md, PIPELINE.md, aet-work/SKILL.md) plus every live skill that invokes `aet add` are updated; historical plans/audits/bugs are left as records.

### The board

- **R-13**: Every live plan that has been added has exactly one issue, identified by plan id rather than title match. Settled and statusless plans get none.
- **R-14**: The `aet:*` labels are provisioned automatically on first projection use, and the label map covers every member of `STATES` plus `draft` and `backlog`, asserted by a test so a newly added state cannot silently drift.
- **R-15**: A task state transition updates its issue to carry exactly the label for its current state, removing the prior one.
- **R-16**: A terminal state (`merged` / `abandoned`) closes the issue.

### Operations

- **R-17**: A reconcile command heals drift — missing issue, wrong or extra label, issue closed by hand while its plan is live — and is dry-run by default.

### Record

- **R-18**: The decisions and the workflow are recorded: the workflow above as engineer-facing documentation; an ADR superseding ADR-014 (projection, not backend); an ADR for fail-open projections against fail-closed storage; the ADR-013 settled-contract resolution; and roadmap Phase 6 shelved into Phase 9 with its triggers.

## User Stories

- As an operator, I want `aet add` to put a plan on the GitHub board and commit it, so the backlog is something my team can see without touching my machine (satisfies: R-9, R-10)
- As an operator, I want `aet sprint` to be the one act that schedules work, so scheduling is a decision I make deliberately rather than a side effect (satisfies: R-11)
- As an operator working from a laptop and a cloud environment, I want `aet run` to select the same work in both after a pull, so the sprint is not trapped in one machine's file (satisfies: R-8, R-9)
- As an operator, I want `aet:draft` and `aet:backlog` to tell me what is still being planned versus what is ready to schedule (satisfies: R-10)
- As an operator, I want `aet:ready` to mark exactly what the orchestrator may pick up, computed from the graph rather than asserted by anyone (satisfies: R-11, R-12)
- As an operator shipping from one environment, I want the merge visible from the other, so finished work stops showing on the board (satisfies: R-8, R-16)
- As an operator, I want a GitHub outage or an expired `gh` token to be a warning rather than a broken session, so the factory never stops for a mirror (satisfies: R-4, R-5)
- As a teammate on a fresh clone, I want the backlog to look the same as it does on the owner's machine, rather than showing 121 issues for work finished months ago (satisfies: R-6, R-7)
- As an engineer adopting AET on a GitHub repo, I want the workflow written down, so I follow it rather than guess at it (satisfies: R-18)
- As the architect, I want it impossible to configure a forge as the source of truth, so the standing fence holds by construction (satisfies: R-2, R-3)

## Acceptance Criteria

- [ ] A config with `task_backend: "git-refs"` and a GitHub projection produces both a git-refs ledger write and an issue label update from a single transition (satisfies: R-1)
- [ ] `task_backend: "github"` and `task_backend: "both"` are rejected as unknown values with a named error pointing at the projection config (satisfies: R-2)
- [ ] `aet-setup` writes projection config; its checklist and docs no longer name a forge as a backend (satisfies: R-3)
- [ ] With `gh` uninstalled or unauthenticated, `aet add` still commits and pushes the status, warns naming the projection, and exits zero (satisfies: R-4)
- [ ] A git-refs write failure still raises and fails the command — fail-open did not leak into storage (satisfies: R-5)
- [ ] A newly created plan carries `status: draft`; a plan missing `status` is rejected at intake with a named error; a status outside the lifecycle is rejected (satisfies: R-6)
- [ ] A statusless legacy plan produces no issue and is reported as settled, not live (satisfies: R-6, R-13)
- [ ] `init-queue` determines settled-ness with `.agents/work-history.jsonl` absent and produces the same result as with it present (satisfies: R-7)
- [ ] After `aet add`, `aet sprint`, and closure, `git status` shows nothing unpushed at each step (satisfies: R-8)
- [ ] A push failure during `aet add` reports the failure, leaves the local commit intact, and re-running succeeds (satisfies: R-8)
- [ ] A second clone that pulls after `aet sprint` runs the same task from `aet run`, with no `aet add` performed there (satisfies: R-9)
- [ ] `aet backlog add` on a `draft` plan creates one issue labeled `aet:draft`; on an `approved` plan, `aet:backlog` (satisfies: R-10)
- [ ] Running `aet backlog add` twice, or from a second clone, finds the issue by plan id and creates no duplicate (satisfies: R-10, R-13)
- [ ] `aet sprint add` on a plan whose blockers are unmet labels it `aet:blocked`, not `aet:ready`, and `aet run` does not select it (satisfies: R-11, R-12)
- [ ] `aet sprint add` on a plan with no pending blockers labels it `aet:ready` and `aet run` selects it (satisfies: R-11, R-12)
- [ ] Top-level `aet add` no longer resolves; `aet sprint add` and `aet backlog add` parse under the dispatcher, and skills-lint passes with every live skill updated (satisfies: R-19)
- [ ] The `aet:*` labels exist after first projection use with no manual step, and a test fails if a member of `STATES` has no label (satisfies: R-14)
- [ ] A `ready → in_progress` transition leaves exactly `aet:in-progress`, prior label removed (satisfies: R-15)
- [ ] A `quarantined` task projects as `aet:quarantined` — the state that silently had no label (satisfies: R-14, R-15)
- [ ] Recording a merge closes the issue (satisfies: R-16)
- [ ] Reconcile on a repo with live plans and no issues reports what it would create and creates nothing; `--apply` creates them and corrects every label (satisfies: R-17)
- [ ] Reconcile reports an issue closed by hand while its plan is live rather than silently accepting the drift (satisfies: R-17)
- [ ] The workflow is documented for engineers; all ADRs merged; roadmap doc 09 shows Phase 6 in Phase 9 with triggers recorded (satisfies: R-18)
- [ ] A live rehearsal against a real GitHub repo demonstrates the full workflow — add → sprint → run → close — with an audit doc recording it (satisfies: R-10, R-11, R-15, R-16)

## Technical Notes

### Ground truth, verified 2026-07-17 at `ced2d68`

| Piece | State today |
|---|---|
| `_create_issue()` | Implemented; **unreachable**. `bin/sync:154` hardcodes `is_new=False`; `bin/add` never calls `sync_task`. `is_new=True` exists only in tests. |
| `ensure_labels()` | Implemented; **never called** in production. State labels are never provisioned. |
| `STATE_LABELS` | Missing `quarantined`, which `nsr-02` added to `STATES` on 2026-07-16. Proof the map is unexercised. |
| `_update_issue_labels()` | Wired via `bin/aet-state:312` (`on_transition`). Finds the issue by `github_issue_number`, else falls back to `_find_issue_by_title` — brittle across clones, hence R-13's id-keyed identity. |
| `close_task()` | Wired via `bin/aet-state:323`. Closes by `github_issue_number`, which only `_create_issue` (dead) ever sets. |
| `GitHubBackend.load/save` | Read/write `self.queue_file` — the **local JSON queue**. Nothing is stored in GitHub. `task_backend: "github"` means "JSON storage plus labels". |
| `task_backend: "both"` | `raise NotImplementedError("Composite backend is not yet implemented")`. |
| Closure push | `git push` appears **only** in `aet-ship/SKILL.md` prose — no Python binary pushes. `record-merge` commits in `cmd_record_merge` (`src/aet/cli/aet_state.py`) and stops. |
| `ready` is computed | `cmd_transition` (`src/aet/cli/aet_state.py`) releases dependents on closure: `append_history(dep, dep_state, "ready", "release")`. `pending_blockers` falls back to `len(blocked_by)`. Confirms R-12. |
| Config resolution | Already external-first (`ewl-07`): `AET_WORK_CONFIG` → `~/.aet/{slug}/config.json` → in-tree → defaults. The projection axis rides this unchanged. |

### The corpus census — why R-6 exists

Measured 2026-07-17 across `docs/plans/*.md`:

| Signal | Count |
|---|---|
| Total plan files | 203 |
| `status: merged` | 81 |
| `status: draft` | 1 (`nsr-07`) |
| `status: approved` | 1 (`twe-03` — stale; its code merged, footer says `merged`) |
| **No `status` field at all** | **121** |
| `*Stage: merged*` footer | 15 |

`plan_validate.py` has no concept of `status` — neither required nor validated, written opportunistically by the closure path. So 121 plans (60% of the corpus) are indistinguishable from live work using versioned data. The only thing that knows they are settled is `.agents/work-history.jsonl`, which `.gitignore:14` excludes — local and machine-specific. Without R-6, a second environment or a teammate's clone would project 121 backlog issues for work finished months ago.

R-6's grandfathering is safe precisely because of this history: `status` postdates those plans, so "no status field" reliably marks the legacy era rather than making a claim about liveness. Every plan created from here carries `status: draft` at birth, so the rule is complete going forward.

### Membership becomes versioned — why R-9 is the load-bearing change

ADR-013 made the queue an "ephemeral, gitignored sprint board… rebuilt or curated by the user," with plan files as the durable source of truth. Curation has been local-only, which is why the sprint cannot travel. R-9 takes the ADR at its word: membership is **rebuilt from committed status**, so the queue stays an ephemeral cache and stops being the only place a decision lives. Nothing in ADR-013 changes; the half of it that was never realized simply gets realized.

This is also what makes the projection honest. A mirror of a local-only truth would show a teammate something they could neither verify nor reproduce. A mirror of committed status shows them something they already have.

### The ADR-013 contradiction — why R-7 exists

ADR-013 decision 3: `.agents/work-history.jsonl` "remains an optional, gitignored execution log… **It is not used to determine whether a task is closed.**"

`init-queue:257`:

```python
settled_files = {t.get("plan_file") for t in history if t.get("plan_file")}
settled_ids = {t.get("id") for t in history if t.get("id")}
```

The code does exactly what the ADR forbids. Invisible today because one machine holds both history and plans; a second clone makes it immediate. R-6 supplies the versioned signal that lets R-7 remove the history dependency, making ADR-013 decision 3 true rather than aspirational.

### Why closure must push — R-8

The liveness contract only works if it travels. The night shift hides the gap because `aet-ship`'s *prose* tells the agent to push, so main happens to be in sync. But `aet desk merge` (twe-03) drives `gh pr merge` → `record-merge` directly and stops at the commit. Consequences compound: a second environment treats finished work as live and its issue sits on the board forever, and `run-one` bases worktrees on `origin/main`, so unpushed closure means new work starts from a stale base — a known failure mode. R-8 generalizes the fix to every status-writing command, since `aet add` and `aet sprint` introduce two more.

### The label model

One axis, extending `aet:<state>` with two new values:

| Label | Set by | Meaning |
|---|---|---|
| `aet:draft` | `aet add` | On the board, still being planned |
| `aet:backlog` | `aet add` | On the board, approved, not scheduled |
| `aet:ready` | AET (computed) | **The orchestrator may run this** |
| `aet:blocked` | AET (computed) | Scheduled, blockers pending |
| `aet:planned` | AET | In the sprint, not yet released |
| `aet:in-progress` | AET | Being executed |
| `aet:awaiting-merge` | AET | Done, pending closure |
| `aet:failed` / `aet:quarantined` | AET | Runtime outcomes; `quarantined` currently missing from the map |
| *(issue closed)* | AET | `merged` / `abandoned` |

R-14's parity test binds the map to `STATES`, so the `quarantined` gap cannot recur.

### The fan-out surface is small

Three call sites invoke projection methods, all through the backend interface: `bin/aet-state:312` (`on_transition`), `bin/aet-state:323` (`close_task`), `bin/sync:154` (`sync_task`). `aet-state` is the single state writer, so wiring the dispatcher there covers every transition by construction. `aet add` needs the creation call it never had, and `aet sprint` is new. Eight commands call `create_backend`, so the factory's return shape is the blast radius: `init-queue`, `status`, `next`, `aet-state`, `add`, `desk`, `sync`, `orchestrator`.

### Config shape

```json
{
  "task_backend": "git-refs",
  "projections": [
    { "type": "github", "repo": "owner/name", "label_prefix": "aet" }
  ]
}
```

`projections` is a list so a second type (ADO work items) is additive later with no schema change. An absent or empty list means no projection — the default, and the Mode-1 posture.

### Fail-open is the inversion, and it needs its own ADR

`_run_gh` raises `BackendError` on any non-zero exit. Correct for storage, wrong for a mirror: a dead token must not fail a status commit. The kernel rule is fail-closed everywhere (doc 07 steal 4), so this exception must be explicit and bounded. The dispatcher enforces it — it fans out and swallows-with-warning, so no individual projection can forget the rule and no storage path can inherit it.

### Why this replaces Phase 6

Roadmap Phase 6 (doc 09 lines 125-134) assumed a team sharing one ledger across machines, motivating an orphan transport branch, a conflict model, and server-side branch protection. Grounding on 2026-07-17 retired the premise:

- **Coordination is not AET's job.** One plan, one operator, executed fully — no concurrent same-task writes to reconcile, so no conflict model and no event-log rewrite of `git_refs_backend.py`.
- **Versioned status makes state travel without a ledger transport.** R-9 delivers what the sync branch was for, using git as it already works.
- **Teammates are adopters, not adversaries.** Server-side walls defend against someone routing around the client-side hook; nobody is.
- **No live non-GitHub repo.** ADO is prospective, so the forge adapter, `aet doctor --forge`, and `aet-ship` portability have no trigger.

Phase 6 also moved the roadmap's governing metric (human minutes at the two ends) by zero. Phases 7 and 8 move it. R-18 records the shelving with triggers so it re-opens on evidence rather than memory.

### Dependencies and fences

- Depends on `ewl-04` (git-refs default) and `ewl-07` (external-first config) — both merged.
- The fence holds and strengthens: with R-2, no config can name a forge as storage, so "no second storage backend beyond git-refs" becomes structural rather than cultural.
- No backward compatibility, per the standing rule: `task_backend: "github"` is deleted outright. Zero migration cost — it never stored anything in GitHub, and no config on the owner's machine selects it.

## Open Questions

*Resolved during scope validation (2026-07-17): command shape is `aet backlog add` / `aet sprint add` (noun-scoped, top-level `aet add` retired — owner decision); `draft → approved` is owned by `aet-validate-scope`, the approval gate; `status: sprint` corrected to the canonical `status: queued` (CONTEXT.md).*

- **`aet backlog add` on a draft vs approved plan.** Both are accepted (labels `aet:draft` / `aet:backlog` respectively). Confirm whether `backlog add` on a still-draft plan is desired, or whether the board should only show approved work. Leaning: accept both, since "draft or final" was the owner's phrasing.
- **Issue body content and drift.** `_create_issue` writes a body from the task record. Should it link the plan file, and should reconcile rewrite a drifted body, or only labels? Leaning: link the plan, labels-only reconcile — the body is a convenience, not state.
- **Reconcile on a hand-closed live issue.** Re-open, or report and let the human decide? Leaning: report by default, `--apply` to re-open — mirroring ADR-024's `audit` / `heal --apply` split, which exists because a remedy that cannot run against its triggering condition is useless.
- **`twe-03`'s stale `approved` status.** The only approved live plan, and its code is already merged. A one-line correction; called out so R-6's rollout does not mistake it for real backlog.
- **Label prefix collisions.** `ensure_labels` creates `aet:*` labels in a shared team repo. Refuse if a conflicting non-AET label exists, or adopt it?

## Risks

- **R-9 changes what the queue is for.** Membership moving from local curation to derived-from-status touches `add`, `sync`, `init-queue`, `next`, and `orchestrator`. Done wrong, the sprint either silently empties or picks up work nobody scheduled. The `frh-14` parity-suite pattern is the precedent for de-risking a derivation flip.
- **R-6 is a contract change with intake blast radius.** Making `status` required touches `aet-plan`, the plan template, `plan_validate`, and the twe-05 intake gates. If grandfathering is wrong in either direction, either the queue rejects legacy plans (the `init-queue` failure mode already seen with frh-17/18) or 121 stale issues appear.
- **R-8 puts the network in the commit path.** `aet add` and `aet sprint` now push. A push failure must not lose the commit or half-apply the status — and it makes previously-offline commands network-dependent.
- **The projection has never executed against a live repo.** Every path is unproven — the `quarantined` gap is what that costs. The live rehearsal is a task, not an afterthought; mocked tests cannot establish that `gh` behaves as the code assumes.
- **Bulk remote writes.** Reconcile can mass-mutate a repo's issues. Dry-run by default (R-17) is the mitigation; getting it wrong is noisy and public in a shared repo.
- **Fail-open masking real breakage.** A projection that silently warns forever is a board that quietly rots. Mitigation: reconcile surfaces drift, and the warning names the projection and the cause.

## Divergence Summary

<!-- markdownlint-disable MD024 -->

*Recorded: 2026-07-18 — Branch: gib-02-projection-axis-fail-open-dispatcher*

### Changed from plan

- None. The gib-02 plan intent matches the branch diff within naming/organization tolerance.

### Added (unplanned)

- None. The branch contains only the projection-axis and fail-open-dispatcher work scoped to gib-02.

### Deferred

- **R-6 through R-19** remain unimplemented in this branch. They are scheduled for downstream tasks: gib-05 (board machinery), gib-06 (commands and command reshaping), and any follow-ups required for the live rehearsal, ADRs, and roadmap shelving recorded in R-18.

*Recorded: 2026-07-18 — Branch: gib-03-status-liveness-contract*

### Changed from plan

- **Corpus classifier guard:** The plan cited a 203-plan census (121 statusless, 81 merged, 1 draft, 1 approved). By implementation time the corpus had grown to 212 plans, so `test_corpus_classifier_matches_known_live_set` was updated to assert 120 statusless, 82 terminal, and 10 live plans. The guard's intent — exactly statusless + terminal plans are settled — is unchanged.

### Added (unplanned)

- None.

### Deferred

- None.

<!-- markdownlint-enable MD024 -->

---

*Stage: synced*
*Next step: run `aet-ship`*
