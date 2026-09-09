# PRD: A Single Admission Path onto the Board

## Overview

Admission — building a new task from a plan file and putting it on the board —
happens at two doors: `aet sprint add` and `aet sprint intake`. Neither calls a
shared operation. Each inlines its own sequence of checks, and the sequences
drifted until the only policy both doors shared was the one three accepted ADRs
forbid, while the policy those ADRs want ran on one door only.

The measured state on 2026-08-27, before this PRD:

| Policy | `sprint add` | `sprint intake` | `backlog add` |
| --- | --- | --- | --- |
| Already queued / already settled | yes | yes | n/a |
| Footer stage is `plan-approved` | yes | yes | `{plan-draft, plan-approved}` |
| Frontmatter contract, rtrace, acks | yes | **no** | no |

The footer row is the ADR-019 violation. The validation row is the hole it hid:
a plan reachable from an `aet:sprint` issue entered the queue with nothing
checked, while the identical plan was refused at the other door. That hole is
closed (commit `9aa5c7b4`), but it was closed by extracting one half of the
decision. The other half — queued, settled, stage, blocked-handling — is still
written twice.

Scope validation turned up a fact that sharpens this. `update_plan_footer()` no
longer exists anywhere in `src/`, and no code writes a plan `_Stage:` footer —
the only remaining writers are three templates and a skill instruction. So the
footer is not a code-maintained breadcrumb that some gates wrongly read. It is a
value produced only by templates and consumed only by gates. Once the three
emitters stop and the gates stop reading, it does not become a breadcrumb; it
ceases to exist for new plans, and existing plan files keep theirs harmlessly.

This PRD makes admission a single operation. The reason to do it is not tidiness:
it is that "no gating decision reads the plan footer" is currently unauditable.
Answering it today means grepping six call sites and classifying each as gate or
breadcrumb, and the classification is not obvious from the call. With one
admission operation the question is answered by reading one function, and the
next ADR that changes admission policy has one edit site instead of three.

## Goals

1. There is exactly one place that decides whether a plan may join the board,
   and the full set of admission outcomes can be read there.
2. No gating decision reads the plan `_Stage:_` footer, as ADR-019 decision 4
   has required since it was accepted, and the glossary describes what the code
   actually does.
3. Adding a third door in future cannot reintroduce a policy divergence, because
   a door has no policy to implement.

## Non-Goals

- **Re-deciding whether the footer may gate admission.** Three accepted, live
  ADRs settle it: ADR-019 decision 4 ("The plan footer `*Stage:*` is demoted to
  a human breadcrumb everywhere; no gating decision reads it"), ADR-055
  decision 1 (`status` leaves the plan contract), and ADR-061 (the record is the
  plan after intake, with `aet sprint add` as the single named handoff). This
  PRD decides *where the single answer lives*, not what it is. No new ADR is
  authored for the disposition.
- **Changing what the validation suite checks.** `plan_validate` keeps its
  current checks. Only where it is invoked from changes.
- **Removing display or fallback readers of the footer.** `src/aet/gate.py`
  categorizes plans for display, `src/aet/cli/context.py` reports stage and is
  mostly the separate PRD lifecycle, and `verifier.read_plan_stage` is consumed
  in `src/aet/cli/orchestrator.py` only after `task.get("stage")` has been
  tried. That last one is the third input `CONTEXT.md` names; it degrades to
  a breadcrumb once the gating doors close, and its own docstring already says
  it is advisory. ADR-019 permits breadcrumb reads. All are out of scope.
- **The stale `.agents/work-queue.json` reference audit.** Fifteen files across
  six skills, already filed in `content/backlog/`. It shares a *method*
  with this PRD's footer sweep — per-file judgment across `skills/`, because
  some occurrences are correct where migration docs name the old path
  deliberately — but not a subject. Merging them produces one task verifiable
  only against two unrelated criteria. It stays where it is filed.
- **A general plugin or registry for doors.** Two doors exist. The operation is
  a function both call, not an extension point.
- **PRD and brief footers.** A different lifecycle, still read by `aet context`.
  The sweep in R-8 is scoped to the three files that emit the *plan* footer.

## Requirements

- **R-1**: A single admission operation decides whether a plan may join the
  board. `aet sprint add` and `aet sprint intake` obtain their decision from it
  and implement no admission policy themselves.
- **R-2**: The operation returns an enumerable outcome — admitted with the built
  task, skipped because the task is already live or already settled, or refused
  with reasons — so the complete set of admission outcomes is readable in one
  place.
- **R-3**: Each door renders the outcome in its own shape: `add` exits with a
  message and a status code, `intake` records a row in its batch summary.
  Presentation stays with the door; the decision does not.
- **R-4**: No admission decision reads the plan `_Stage:_` footer. The approval
  signal is the operator's invocation for `add`, and the `aet:sprint` label on
  the issue for `intake` — both deliberate human acts on a specific plan.
- **R-5**: The `plan_validate` suite runs identically at both doors as a
  property of the shared operation, not of each caller, so a door cannot be
  added that skips it.
- **R-6**: `aet backlog add` no longer gates on the footer, so "no gating
  decision reads the plan footer" holds without exception and can be verified by
  reading the admission operation alone.
- **R-7**: The display and fallback footer readers named in Non-Goals are
  unchanged, and a test pins that `aet context` still reports plan stage.
- **R-8**: The three files that emit the plan footer stop emitting it:
  `.agents/templates/plan-template.md`, `skills/aet-plan/SKILL.md`, and
  `skills/aet-setup/examples/plan-template.md.example`. PRD and brief footers
  are untouched.
- **R-9**: `skills/aet-plan/SKILL.md` completion item 2 no longer instructs
  writing the footer, and the `CONTEXT.md` plan-lifecycle entry records that the
  footer is a breadcrumb only rather than "not yet a breadcrumb only".
- **R-10**: A plan carrying no `_Stage:_` footer is admitted at both doors, and
  a regression test asserts it at each.
- **R-11**: The admission operation preserves each door's distinct provenance:
  `aet sprint add` and `aet sprint intake` continue to write ledger `cut` events
  with `source` values of `sprint-add` and `sprint-intake` respectively. Event
  ids derive from `source:task:kind:ref` (ADR-055 decision 2), so collapsing the
  two sources would change event identity.
- **R-12**: The `CONTEXT.md` glossary is corrected where it describes this area
  inaccurately, in four places found during scope validation:
  **Board** ("Plans enter the board only through `aet sprint add`" — `aet sprint
  intake` is a second door), **Plan File** and **Stage** (both say the footer is
  updated or maintained by code; no such writer exists), and **Plan Backlog**
  ("Approved plans in `docs/plans/`" — no longer accurate once R-6 lands).

## User Stories

- As a maintainer auditing ADR-019 conformance, I want to read one function to
  learn what authorizes a plan onto the board, so that the answer does not
  depend on classifying six call sites as gates or breadcrumbs
  (satisfies: R-1, R-2, R-6).
- As an operator, I want the same plan to be accepted or refused identically
  whichever door I use, so that a refusal tells me about my plan rather than
  about which command I typed (satisfies: R-1, R-5).
- As an agent following `aet-plan`, I want to produce a plan that queues without
  a footer, so that the skill's instructions and the CLI's enforcement agree
  (satisfies: R-4, R-9, R-10).
- As a maintainer changing admission policy in future, I want one edit site, so
  that a policy change cannot land on one door and miss another
  (satisfies: R-1, R-3).
- As a maintainer, I want the footer sweep to leave the PRD lifecycle intact, so
  that finishing this sweep does not break `aet context`'s stage reporting
  (satisfies: R-7, R-8).

## Acceptance Criteria

- [ ] `new_task_from_plan` is called from exactly one place, and neither
      `sprint.py` door contains a queued/settled/stage check of its own
      (satisfies: R-1).
- [ ] The admission outcome type enumerates every refusal reason; adding a
      reason requires editing that type (satisfies: R-2).
- [ ] `aet sprint add` on a refused plan still prints the finding list and the
      `⚠️ VALIDATE ACK` line; `aet sprint intake` still prints one refused row
      per candidate with its reason (satisfies: R-3).
- [ ] `grep -rn "stage_from_plan" src/` returns no hit inside an admission or
      backlog gating branch; the remaining hits are the display, reporting and
      fallback readers named in Non-Goals (satisfies: R-4, R-6, R-7).
- [ ] A plan with no `_Stage:_` footer and a clean contract is admitted by
      `aet sprint add`, and by `aet sprint intake` from an `aet:sprint` issue
      (satisfies: R-10).
- [ ] A plan failing rtrace is refused at both doors with the same finding
      (satisfies: R-5).
- [ ] `grep -rn '_Stage:\|\*Stage:' skills/ .agents/templates/` returns only PRD
      and brief footers: `aet-sync-docs/SKILL.md`, `prd-template.md.example`,
      `brief-template.md`, and `aet-validate-scope/SKILL.md`
      (satisfies: R-8).
- [ ] `aet context` still reports `active_plan_stage` and `active_prd_stage` for
      a repo whose PRD carries a footer (satisfies: R-7).
- [ ] `CONTEXT.md`'s plan-lifecycle entry no longer says the footer is "not yet
      a breadcrumb only" (satisfies: R-9).
- [ ] Admitting the same plan through each door produces two ledger events whose
      ids differ, with `source` values `sprint-add` and `sprint-intake`
      (satisfies: R-11).
- [ ] No `CONTEXT.md` entry claims code maintains the plan footer, and the
      **Board** entry names admission rather than one command (satisfies: R-12).

## Open Questions Resolved in This PRD

1. **Where the admission operation lives.** Not `plan_parser.py`, which turns
   text into structures and would have to grow dependencies on `plan_validate`
   and the backends — a layering inversion. Not `sprint.py`, which would make
   `backlog.py` and any future door import from a CLI command module. A module
   at the domain layer beside `plan_parser.py` and `plan_validate.py`, depending
   on both and imported by the CLI doors.
2. **Whether `aet backlog add` is a violation or a legitimate Author-phase
   read.** It is contestable: backlog is pre-intake, and ADR-061 says the file
   is the artifact during authoring. It is included anyway, for a reason
   independent of that argument — its accepted set is
   `{plan-draft, plan-approved}`, which spans the entire authoring lifecycle, so
   any plan written from the template passes. The check is close to vacuous as a
   gate while still costing the audit an exception to reason about. Removing it
   buys an absolute, checkable property; keeping it buys a gate that admits
   everything.
3. **Whether the footer sweep belongs here.** Yes, because leaving
   `skills/aet-plan/SKILL.md` item 2 in place after the gate is gone is worse
   than the original bug: it would instruct agents to satisfy a requirement that
   no longer exists, and the 2026-08-27 retro's note about the requirement being
   temporary would have outlived its subject.

## Scope Validation Findings

Run against `CONTEXT.md`, the ADR set, and the code on 2026-08-27.

1. **No code writes the plan footer.** `update_plan_footer()` is absent from
   `src/`; the only `_Stage:` hits under `src/` are a docstring in
   `plan_parser.py` and two console prints. This is why the sweep in R-8 is
   sufficient — there is no code emitter to also remove.
2. **`CONTEXT.md` names one door where there are two.** The **Board** entry says
   plans enter "only through `aet sprint add`". `aet sprint intake` calls
   `new_task_from_plan` and `backend.save` exactly as `add` does. The glossary
   documented the invariant this PRD is about to make true.
3. **Both doors already write ledger events**, with distinct `source` values —
   no divergence there, but it is a constraint on the consolidation (R-11)
   rather than something to unify.
4. **No ADR conflict.** ADR-019/055/061 mandate the footer disposition and are
   cited, not re-decided. ADR-054's "`aet queue sync` never scans the plans
   directory" is unaffected: this PRD changes admission, not discovery.

## Intake Triage

- [x] Confirmed this is a **feature or enhancement**, not a reproducible defect.
      The triage was run explicitly: the *footer disposition* is a conformance
      defect against ADR-019/055/061 and was routed out of this pipeline, but
      whether the board has one admission path is decided by no accepted ADR,
      which is what makes this planning work.
- [x] Reproducible defects found alongside this item were routed to
      `aet-bug-report` and fixed: `telemetry.report` scanning the wrong archive
      file (`e99766a2`), `teardown_worktree`'s obstruction predicate
      (`611b4b2a`), the unresolvable-rtrace refusal message (`7c2f7761`), and
      `aet sprint intake` running no validation (`9aa5c7b4`).

## Divergence Summary — adm-01-single-admission-operation

*Recorded: 2026-08-27 — Branch: adm-01-single-admission-operation*

### Deferred

- **Task 7 (merge branch to main and verify integration)**: deferred to the `aet-ship` closure stage, consistent with the standard pipeline.

## Divergence Summary — adm-02-backlog-stops-gating-on-the-footer

*Recorded: 2026-08-27 — Branch: adm-02-backlog-stops-gating-on-the-footer*

### Changed from plan

- **Test placement (Task 4):** The regression test for admitting footerless plans to the backlog was added to `tests/projections/test_backlog_add.py` rather than `tests/cli/test_backlog.py` (which does not exist; backlog add projection tests are housed under `tests/projections/`).

### Deferred

- **Task 5 (merge branch to main and verify integration)**: deferred to the `aet-ship` closure stage, consistent with the standard pipeline.

---

*Stage: synced*
*Next step: run `aet-ship`*
