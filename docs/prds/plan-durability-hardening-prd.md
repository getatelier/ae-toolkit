# PRD: Plan Durability Hardening (Gaps 2–3)

## Overview

Follow-up to `docs/bugs/2026-07-14-aet-add-queues-untracked-plans.md`. That bug —
queued plans that git cannot retrieve from `origin/main` spawn empty worktrees —
has three root gaps. **Gap 1 (no intake durability guard) is already fixed** in
`aet-work/bin/add`. This PRD covers the two remaining, deeper gaps so the failure
is closed at execution and prevented by construction, not just caught at intake.

**Intake triage:** hardening of existing behavior, emerging from a reproduced
defect — the fixes are guard/process changes, planned here rather than hacked in.

## Goals

- Make the AFK (unattended) execution path fail closed when the run's plan may be
  non-durable, instead of warning and continuing.
- Make the planning pipeline commit plans before queueing, so the happy path
  produces durable, addable plans by construction (and satisfies the Gap-1 guard).

## Non-Goals

- **No change to `check_base_hygiene`'s detection logic** (`src/aet/worktree.py`) — it
  already correctly flags a dirty tree and `main` ahead/behind `origin/main`.
- **No push automation** — committing/pushing stays the operator's action; we only
  refuse to proceed when durability is not established.
- Gap 1 (intake guard) is done; not re-litigated here.

## Requirements

- **R-1**: In unattended mode, `aet-work` fails closed (does not warn-and-continue)
  when main hygiene indicates the run's plan may be non-durable — a dirty working
  tree (excluding the already-ignored queue sidecars) or local `main` ahead of
  `origin/main`. Projects with no remote (`origin/main` absent) are unaffected.
- **R-2**: The planning pipeline commits plan files before `aet add` —
  `aet-pipeline-plan` and `aet-plan` gain an explicit commit step before queue
  handoff, so plans are durable (and pass the Gap-1 intake guard) by construction.

## User Stories

- As an operator running AFK, a run does not silently proceed on an unpushed/dirty
  main and produce an empty worktree — it stops and tells me to commit/push
  (satisfies: R-1)
- As a planner, finishing a planning session leaves my plans committed and
  queueable without a manual commit I have to remember (satisfies: R-2)

## Acceptance Criteria

- [ ] With `AET_EXECUTION_MODE=unattended` and `main` ahead of `origin/main`,
      `aet-work` halts with a durability message instead of "⚠️ … Continuing" (R-1)
- [ ] With a genuinely dirty tree (non-sidecar), unattended `aet-work` halts (R-1)
- [ ] A no-remote project (no `origin/main`) is **not** falsely halted (R-1)
- [ ] Running the planning pipeline leaves the new plan files committed before
      `aet add` is invoked; `aet add` accepts them without `--allow-untracked` (R-2)

## Technical Notes

**Key decision (R-1) — remove the unattended soften for durability-critical
conditions.** `enforce_base_hygiene` (`src/aet/cli/orchestrator.py`) currently returns `True`
with a warning whenever `AET_EXECUTION_MODE=unattended`. The soften's original
purpose was that batch runs dirty the tree by mutating the queue file between
tasks — but `check_base_hygiene` **already excludes** the queue file and its
`.lock`/`.lease` sidecars (`src/aet/worktree.py`), so failing closed in unattended
no longer false-positives on normal AFK operation. And no-remote projects don't
trigger the ahead check (`rev-list origin/main..main` errors → counted as 0). So
the soften is now largely obsolete for these conditions.

_Alternative considered:_ a surgical per-plan check (does _this_ plan's file exist
on `origin/main`?) instead of general main-hygiene. Rejected for now — more code,
and the general check already covers the failure with the sidecar exclusion.

**R-2 touchpoints:** `aet-pipeline-plan/SKILL.md` (Step 3) and `aet-plan/SKILL.md`
(create-stories/plan handoff + completion protocol). These are live symlinked
skills, so the change takes effect immediately.

## Open Questions

1. **R-1 breadth:** fail closed in unattended on _any_ real hygiene violation
   (simplest, recommended) vs. only on `main`-ahead (the narrowest
   plan-durability signal)? Recommend the former, since the sidecar exclusion
   already removes the expected AFK dirt.

## Proposed plan breakdown

| Plan       | Scope                                                                    | R   | Size | blocked_by |
| ---------- | ------------------------------------------------------------------------ | --- | ---- | ---------- |
| **pdh-01** | unattended `enforce_main_hygiene` fails closed for durability conditions | R-1 | M    | —          |
| **pdh-02** | commit-plans step in `aet-pipeline-plan` + `aet-plan`                    | R-2 | S    | —          |

Both independent of each other and of the merged Gap-1 fix.

## Divergence Summary

_Recorded: 2026-07-14 — Branch: pdh-01-unattended-hygiene-failclosed_

### pdh-01 — Changed from plan

- None — Tasks 1–3 landed as planned: `enforce_main_hygiene` fails closed with
  an explicit halt log line in both modes, ADR-027 extends ADR-005, and
  `tests/test_orchestrator.py` covers unattended ahead/dirty/clean/no-remote,
  interactive-unchanged, and `run_single` halting in unattended mode.

### pdh-01 — Added (unplanned)

- `aet-work/references/queue-commands.md` — the AFK pre-branch hygiene
  paragraph rewritten to the fail-closed contract. The plan's
  `docs_sync: required` frontmatter required AFK-behavior docs to reflect the
  halt, but the task list / Files to Modify did not name this file.
- `docs/adr/README.md` — index rows for ADR-024 and ADR-025 added alongside
  the planned ADR-027 row; both ADR files existed on `main` but were unindexed.

### pdh-01 — Deferred

- None. (R-2 is delivered by pdh-02, a separate queued plan — not a pdh-01
  deferral.)

---

_Stage: scope-validated_
_Next step: run `aet-work`_
