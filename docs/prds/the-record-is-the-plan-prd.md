# PRD: The Record Is the Plan — Retire Post-Intake Plan-File Reads

## Overview

R-19 (`docs/prds/open-work-board-prd.md`) made the task record carry the plan's spec
"rather than a path to a file", and the glossary settled it: "after R-19 no plan
file need exist on the machine that runs it". The producer side was migrated —
`render_task_plan` writes the worktree plan from the record, `derive_queue`
accepts specs. Several **consumers were not**, and they still resolve
`plan_file` as a filesystem path.

Because a missing file is indistinguishable from "nothing to do" in every one of
those consumers, all of them fail open and silently. The measured damage:

| Consumer | Symptom | Evidence |
| --- | --- | --- |
| `aet ship` ×5 entry points | Refuses to run: `⛔ Plan not found … Pass the full plan path` | `docs/bugs/20260819-…` (open); `src/aet/cli/ship.py` |
| R-5 plan archive | `archived_to: null` on every post-R-19 `land` event | 56 land events; every success is pre-R-19 or a test fixture |
| `aet metrics` declared size | `None` for **368 of 368** settled records | `src/aet/metrics.py` → `except OSError: return None` |

This PRD does not add a fallback. A fallback would preserve the two
representations that caused the divergence. It completes the R-19 migration by
making the record the only post-intake source, and deletes the file-reading
paths.

The lifecycle has one source of truth per phase and one explicit handoff:

1. **Author** — `aet-plan` writes `docs/plans/<id>.md`. The file is the artifact.
2. **Intake** — `aet sprint add` ingests it into the record's `spec`. **Handoff.**
3. **Execute, ship, close, measure** — the record is the source. Nothing reads
   the file.

## Goals

- Every post-intake consumer reads the spec from the task record; none resolves
  `plan_file` as a path.
- `aet ship <task-id>` works for a task whose plan file does not exist, and is
  idempotent against a settled task.
- Declared size is recoverable for settled records — currently 0 of 368.
- `docs/plans/archive/` no longer exists, and no code or doc refers to it.
- Exactly one accepted argument form for the ship family.

## Non-Goals

- Changing the authoring phase. `aet-plan` keeps writing `docs/plans/<id>.md`,
  and `aet sprint add` keeps reading it. The handoff point is not moving.
- Changing how worktree plans are rendered (`render_task_plan` is already correct).
- Test-state isolation. Tests write `t1`/`demo`/`blocker` records with pytest
  tmp paths into the real `.agents/ledger.jsonl`; that is a separate defect and
  belongs in `aet-bug-report`.
- Reconstructing specs for settled records whose plan exists in no reachable
  revision. R-6 below reports them; it does not invent them.

## Requirements

- **R-1**: Every post-intake consumer of `plan_file`-as-a-path is enumerated in
  writing, with its replacement spec field named. The audit is the deliverable;
  the three known consumers are its floor, not its scope.
- **R-2**: The ship family resolves a **task id** to a task record — live queue
  first, then sealed history — and reads `spec.frontmatter`, `spec.tasks`,
  `spec.title`, and `spec.body`. `plan_parser.resolve_plan_arg` is removed from
  all five entry points.
- **R-3**: `aet ship` accepts a task id only. The `.md` path form is removed;
  board membership via `aet sprint add` is the single entry point.
- **R-4**: A ship command naming a settled task reports the recorded merge
  commit and exits 0, matching `aet state record-merge`'s existing idempotent
  behaviour. This is a state precondition on one record, not a second
  resolution path.
- **R-5**: `aet metrics` reads declared size from `spec.frontmatter.size` on the
  settled record. `_resolve_plan_path` and its archive/repo fallback are
  removed.
- **R-6**: Settled records are backfilled with their spec **before** anything is
  deleted, per ADR-058. `spec_backfill.backfill_specs` already accepts a generic
  record list; it is extended to `work-history.jsonl`. Records whose plan is
  recoverable from no revision are reported by id, never silently skipped
  (ADR-059).
- **R-7**: The R-5 plan archive is retired: `queue.archive_plan_file`, the
  `~/.aet/<slug>/plans/archive/` location, the `archived_to` land-event field,
  and `docs/plans/archive/` (264 files) are removed. Removal happens only after
  R-6 reports full coverage.
- **R-8**: Skills are audited for the phase model. Every `docs/plans` reference
  is classified authoring (correct) or post-intake (stale) and corrected —
  19 files across 12 skills, including `skills/aet-ship/SKILL.md`.
- **R-9**: A consumer that cannot resolve a spec fails closed with the task id
  named. No consumer treats an absent spec as an empty or default value.
- **R-10**: `CONTEXT.md`'s glossary states the post-intake model. The **Task**,
  **Plan File**, **Work Queue** and **Settled-ness Authority** entries are
  corrected to match the code, discharging the obligation
  `docs/prds/open-work-board-prd.md` recorded and did not fulfil.

## User Stories

- As an operator, I want `aet ship merge <task-id>` to work for any task on the
  board, so that following the ephemeral-plan design does not break the tool
  meant to ship it (satisfies: R-2, R-3)
- As an operator re-running a command after a merge, I want to be told the task
  already merged and at which commit, rather than seeing an error I cannot act
  on (satisfies: R-4)
- As an operator reading `aet metrics`, I want declared-vs-delivered size to
  reflect all settled work, so ADR-046 calibration is not computed from zero
  declared sizes (satisfies: R-5, R-6)
- As a maintainer, I want one place that answers "where does a task's spec come
  from", so the next consumer added does not re-derive the wrong answer
  (satisfies: R-1, R-9)

## Acceptance Criteria

- [ ] `aet ship gate <task-id>` succeeds for a task whose record carries a spec
      and whose `docs/plans/<id>.md` does not exist (satisfies: R-2)
- [ ] `aet ship merge <settled-id>` prints the recorded merge commit and exits 0
      (satisfies: R-4)
- [ ] `grep -rn 'resolve_plan_arg' src/` returns no hits outside its removal
      commit (satisfies: R-2, R-3)
- [ ] `aet ship <path>.md` is rejected with a message naming `aet sprint add`
      as the entry point (satisfies: R-3)
- [ ] `aet metrics --json` reports a non-null declared size for settled records
      carrying a spec; the count rises from 0 (satisfies: R-5)
- [ ] `aet state backfill-specs --include-settled --apply` reports coverage for
      `work-history.jsonl` and names every unrecoverable record (satisfies: R-6)
- [ ] `docs/plans/archive/` is absent and `grep -rn 'plans/archive'` returns no
      hits in `src/`, `skills/`, or `docs/` (satisfies: R-7)
- [ ] The audit document lists every post-intake `plan_file` consumer with its
      replacement field (satisfies: R-1)
- [ ] No skill instructs an agent to read or pass a plan path after intake
      (satisfies: R-8)
- [ ] `CONTEXT.md` no longer defines a Task as a plan file or the Plan File as
      the source of truth for intent, and the Settled-ness Authority entry names
      code that exists (satisfies: R-10)

## Technical Notes

**The correct pattern already exists in the codebase.** `src/aet/cli/aet_state.py`
(`cmd_record_merge`) loads the task by id from the queue, falls back to the
sealed record in `work-history.jsonl`, and handles the settled case
idempotently. Its comment cites R-4 and R-19 by name. R-2 and R-4 extract that
lookup into one shared helper and point ship at it — this is not a new
abstraction, it is deduplicating an existing correct one.

**Every ship consumer wants a spec field, not a file.** Traced:
`_work_class_from_plan` → `spec.frontmatter.work_class`; `_unchecked_tasks` and
`_plan_task_count` → `spec.tasks`; `_extract_prd_link` → `spec.body`;
`parse_frontmatter(...).get("id")` → `spec.frontmatter.id`; `title_from_plan` →
`spec.title`. The sealed record carries exactly `body`, `frontmatter`, `tasks`,
`title`. Nothing in ship passes the plan to a subprocess, so no render is needed.

**Three pieces of accidental complexity delete themselves**, which is the signal
this removes a layer rather than adding one:

- Formerly `_task_id_from_plan` in ship operations round-trips id → path → filename stem →
  id, existing only because the id is discarded at the front door.
- `_scope_audit` excludes the plan file from the changed-paths diff
  (`src/aet/cli/ship.py`) — dead post-R-19, the plan is not in the diff.
- `_build_pr_body` and `_generate_changelog_entry` emit `Plan: [name](path)`
  links to a file R-19 says need not exist. Every PR body carries a dead link.

**R-5 is half-landed, not merely broken.** `docs/prds/open-work-board-prd.md` requires
"a one-time copy of the 264 legacy files so historical metrics survive without a
second read path". That migration never ran: `~/.aet/` contains no `plans/`
directory. Its acceptance criterion is still unchecked. This is the
exact hazard ADR-058 names — populate before removing — so R-6 strictly precedes
R-7. The 264 files in `docs/plans/archive/` are today the only surviving source
of declared size for 360 pre-R-19 records; only 8 of 368 settled records carry
`spec.frontmatter.size`.

**Why the archive is retired rather than repaired.** `src/aet/metrics.py` reads
exactly one thing from a settled plan: `parse_frontmatter(plan_path)`. The
record's `spec.frontmatter` carries those fields structurally. A rendered
archive would be a second serialization of data the record already holds — the
redundancy this PRD exists to remove.

**Scope is wider than the three known consumers.** Scope validation found
**19 modules** under `src/` referencing `docs/plans`, including `orchestrator.py`,
`next.py`, `status.py`, `desk.py`, `sync.py` and `reconcile.py`. Most are
expected to be authoring-phase and therefore correct, but that cannot be claimed
without R-1's audit. This is why the three known consumers are the audit's floor
and not its scope.

**Settled-ness was verified, not assumed.** `CONTEXT.md` describes
a historical `_is_settled_from_authority` reader in `init_queue.py` reading three inputs,
one of them a plan-file footer that R-19 makes impossible. Neither the function,
the module, nor the `aet init-queue` command exists. What actually answers "is it
done?" is the sealed history log: `aet queue sync` reports "skipped (already
settled)" from `work-history.jsonl`, and its `--plans-dir` option is documented
"Deprecated and ignored: sync no longer scans the plans directory." The authority
is already a task record, which is what R-4 and R-7 rest on. `CONTEXT.md` is the
only thing still describing the old model — hence R-10.

**`is_settled_plan` carries a dead branch.** `src/aet/plan_parser.py` (`is_settled_plan`) still reads
`status` frontmatter, which ADR-055 removed from the contract and `plans lint`
now rejects. Its callers are all phase-1 lint tools and are out of scope here,
but R-1's audit should record it.

**Failure mode.** These consumers fail open today: `archive_plan_file` returns
`None` for a missing source, `_declared_size` catches `OSError` and returns
`None`. Both read as "no data" rather than "broken". R-9 makes the replacement
fail closed, consistent with ADR-033 §3.

## Post-Intake Consumer Register (R-1 Audit)

The audit covered `src/aet/`, `src/aet/panel/`, `reports/`, `scripts/`, `skills/`,
and `docs/plans/archive/`. The three consumers known at planning time are the
floor of this register, not its ceiling.

<!-- aet-lint: off -->
### Stale post-intake consumers

| File | Line(s) | Consumer | Replacement field | Notes |
| --- | --- | --- | --- | --- |
| `src/aet/cli/ship.py` | 103, 329, 506, 541, 581, 675, 799, 833, 886, 1113, 1122 | `ship` family | `spec.frontmatter.*`, `spec.title`, `spec.body`, `spec.tasks` | Five entry points; `resolve_plan_arg` and `_task_id_from_plan` |
| `src/aet/queue.py` | 591–614 | `archive_plan_file` | retired with R-7 | R-5 plan archive; fails open with `None` |
| `src/aet/metrics.py` | 28–52, 328–345 | `_declared_size_for_task` | `spec.frontmatter.size` | Returns `None` on `OSError`; 0 of 368 settled records recovered |
| `src/aet/track_record.py` | 154–174, 193–203 | `_resolve_plan_path`, `_required_verdicts_pass` | `spec.frontmatter` | Required verdict kinds read from plan file |
| `src/aet/cli/status.py` | 31–45 | `_declared_size` | `spec.frontmatter.size` | Already prefers spec; file fallback is stale |
| `src/aet/cli/desk.py` | 117–124, 463–468 | `_plan_path`, `_run_risk_view` | `spec.frontmatter` | Risk view reads plan for routing gates |
| `src/aet/cli/aet_state.py` | 524–530, 565–580 | closure archive, `_land_digest` | `spec.body` (R-ids), spec serialization (hash) | `archived_to` write and plan-hash/R-id read |
| `src/aet/cli/orchestrator.py` | 1489–1500, 1951–1954 | `process_task`, integration evidence | `spec.frontmatter` | Fallback parse of rendered worktree plan |
| `src/aet/plan_parser.py` | 423–429 | `task_routing_data` fallback | `spec.frontmatter` | Shared helper used by post-intake consumers |
| `src/aet/worktree.py` | 456–462 | `render_task_plan` fallback | `spec` | Already renders from spec; copy fallback is stale |
| `src/aet/cli/next.py` | 37–39 | `derive_queue` fallback | `spec` presence | Spec should be required; file-existence fallback is stale |
<!-- aet-lint: on -->

### Authoring-phase consumers (correct)

These read `docs/plans/<id>.md` before intake and remain correct after R-19:

- `src/aet/plan_parser.py` (`title_from_plan`, `build_ticket_map`,
  `stage_from_plan`, `is_settled_plan`,
  `references_other_plans`, `most_recent_plan`,
  `new_task_from_plan`, `resolve_plan_arg`)
- `src/aet/plans_lint.py` (`lint_floor`, `lint_corpus`)
- `src/aet/plan_validate.py` (corpus validation)
- `src/aet/cli/context.py` (`_plan_files` etc. operator context inspection)
- `src/aet/cli/sprint.py` (`resolve_plan`, `_add`, `_intake`)
- `src/aet/cli/backlog.py` (`resolve_plan`, `_add`)
- `src/aet/cli/plan.py` (`cmd_validate`)
- `src/aet/cli/orchestrator.py` (`run_single` run-one intake handoff)

### `docs/plans/archive/` consumers

The archive is still referenced outside the package and must be retired under
R-7:

- `docs/CONVENTIONS.md`
- `docs/releases/v1.8.0.md`
- `docs/diagrams/plan-task-lifecycle.*`
- `docs/adr/061-the-record-is-the-plan-after-intake.md`
- `docs/prds/structural-review-tier-2-prd.md`
- `docs/prds/open-work-board-prd.md`
- `docs/prds/the-record-is-the-plan-prd.md` (this PRD)
- `scripts/validate-skills.sh`
- `scripts/archive/migrate-plan-archive.py`
- `src/aet/plans_lint.py` docstring
- `src/aet/telemetry.py` (`plans_archive_dir`)

### Sibling-scope statement

The sibling implementation scope is **not complete**. In addition to the three
known consumers, the audit found post-intake reads in `desk`, `status`,
`track_record`, `aet-state` land digest, and fallback paths in `orchestrator`,
`plan_parser`, `worktree`, and `next`. The sibling plans must grow to cover at
least:

- `desk` risk view
- `status` declared-size fallback
- `track_record` required-verdict routing
- `aet-state` closure land digest
- removal of fallback paths in `orchestrator/process_task`,
  `plan_parser/task_routing_data`, `worktree/render_task_plan`, and
  `next/derive_queue`

This register satisfies R-1 and informs the sibling plans' scope.

## Decisions Taken at Scope Validation

- **The decision is recorded as ADR-061** (`the-record-is-the-plan-after-intake`),
  amending ADR-055 and relating to ADR-058 and ADR-059. ADR-055's scope is
  settled-ness, not read-path authority, so an amendment alone was insufficient.
- **`archived_to` stays in historical `land` events.** Only new writes stop.
  Rewriting the ledger to erase a fact that was true when written contradicts
  ADR-059 and the store's append-only design.
- **The glossary is corrected in this PRD** (R-10) rather than deferred, because
  shipping code that contradicts `CONTEXT.md` is how this drift began.

## Open Questions

- Does `aet ship`'s removal of the `.md` form break any documented workflow that
  ships a plan never added to the board? R-8's skill audit is the place this
  would surface; if one exists, R-3 needs revisiting before implementation.
- Does any consumer outside `src/aet/` (panel, reports, external tooling) read
  `docs/plans/archive/`? R-1's audit must cover the repository, not just the
  package.

---

*Stage: synced*
*Next step: run `aet-ship`*
