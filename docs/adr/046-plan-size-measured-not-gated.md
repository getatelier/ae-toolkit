---
subject: plan-size-measurement
---

# Plan Size is Measured After Implementation, Not Gated Before It

## Status

Accepted. Supersedes the enforcement premise of
`docs/prds/task-size-guardrails-revision-prd.md` (adopted 2026-07-21). Extends
ADR-015 (telemetry informs guardrails, local-first). Does not touch ADR-006
(plan atomicity and the `docs/plans` vs `docs/roadmaps` boundary), which governs
what a plan *is* rather than how large it may be.

## Context

AET has enforced a size ceiling at plan intake since the guardrail model was
introduced. The enforced quantity has changed twice; the shape of the mechanism
never has. Both attempts picked something countable in the plan document and
treated it as a stand-in for the size of the diff that plan would produce:

1. **File count** — how many files the plan listed under Files to Modify.
   Dropped by the 2026-07-21 revision.
2. **Task-list line count** — rejected above 300 lines, enforced in
   `src/aet/plan_parser.py::validate_size()`. The revision PRD's stated rationale
   was that "a task list that long is almost certainly a > 300-line diff."

That rationale was never measured. It has now been measured, on 2026-07-23,
across 264 plans and 1,048 commits (729 attributed to a plan by id, 147 plans
with a measurable code diff, counting added+deleted lines outside `docs/`,
`.agents/`, `content/`, and `reports/`):

**The proxy does not predict what it claims to.** Correlation between task-list
length and delivered code diff is **r = 0.30**, and past roughly six task-list
lines the relationship is flat:

| Task-list lines | n  | Median code diff |
| --------------- | -- | ---------------- |
| 1–5             | 8  | 76               |
| 6–10            | 60 | 413              |
| 11–20           | 31 | 361              |
| 21+             | 25 | 352              |

A 25-line task list delivers *less* code than a 7-line one.

**The gate is inert.** Task-list lengths across all 264 plans: median 10, mean
13.2, p90 25, max **54** — 18% of the cap. Zero plans have ever exceeded it. At
the observed ratio of ~38 diff lines per task-list line, the 300-line cap
corresponds to an ~11,550-line diff. `validate_size()` has never rejected a plan
and structurally cannot.

**Loosening the numbers alone does not change behaviour.** The 2026-07-21
revision raised limits and dropped the file-count check. Post-revision plans
(n=21) shifted only marginally — median task-list length 10 → 16, max *down*
54 → 35 — and the label mix was unchanged (L: 4% before, 5% after).

Meanwhile the labels themselves drifted ~2x from delivery: 71% of `M` plans
exceeded their own stated 200-line ceiling, at a median of 405.

The common cause of all three failures is the same. **The size of a diff is not
a property of the plan document.** It is a property of the code the plan has not
touched yet — its existing shape, its coupling, how much of the change is
mechanical, and what the implementer discovers on contact. No count taken from
the plan text carries that information, so every proxy for it is a
re-parameterisation of the same missing signal. Choosing a third countable thing
would inherit the defect intact.

## Decision

**Plan size is measured after implementation, not gated before it.**

1. Intake stops enforcing a size proxy. `validate_size()` no longer rejects a
   plan on task-list length, and **no replacement proxy is introduced.**
2. The S/M/L bands remain, as *advisory predictions* calibrated against measured
   delivery rather than aspiration. A band is a falsifiable claim about what a
   label tends to deliver, not a limit intake enforces.
3. Both edges of the model are advisory and symmetric. The ceiling becomes a
   2-of-N signal rule; the floor (a plan too small to justify its own branch, PR,
   and review) prompts a merge with a sibling. Each asks the planner to justify
   in writing; neither blocks.
4. The real number is computed at **task closure**, where it exists and is exact:
   the first-parent range of the task's merge commit, recorded on the task's
   history entry alongside the size label the plan declared.
5. Future threshold changes are derived from the recorded distribution. An
   argument to move a band must cite it.

`ATOMIC OVERSIZED` is unaffected. It is a planner-raised assertion that a task
could not be decomposed, not an automated measurement, and it keeps its existing
`aet-implement` refusal and unattended-mode hard stop.

## Consequences

**Positive**

- The one enforced check that has never fired stops implying that size is under
  control when it is not.
- Size becomes evidence rather than argument. The next threshold discussion is
  settled against a recorded distribution instead of re-derived from intuition,
  which is how the last two attempts produced unmeasured rationales.
- Declared-versus-delivered divergence becomes visible per task, which is a
  better estimation signal than any plan-time count could be.
- Removing the one-directional framing ("split early, split often") alongside
  the gate addresses the actual driver. The measured evidence is that the
  numbers were not what constrained planners — the framing was.

**Negative**

- Intake no longer refuses anything on size. A genuinely unbounded plan can now
  enter the queue. This is accepted: the check being removed demonstrably never
  caught one, so nothing real is being given up, and the coherence requirements
  in ADR-006 remain.
- Planner discretion increases at plan time. That is a deliberate trade: the
  determinism moves to closure, where the quantity is knowable, rather than
  being simulated at intake where it is not.
- Measurement depends on `merge_commit` being present on the task record. It is
  present on 267 of 289 existing records (92%); the remaining 8% are
  unmeasurable and are reported as such rather than silently omitted.

**Neutral**

- The bands are fixed constants, not re-derived automatically from the recorded
  distribution. Automatic re-derivation was rejected as a drift loop in which
  thresholds chase whatever was last shipped, ratifying scope creep as the new
  normal. Re-calibration stays a human decision informed by the report.

## Alternatives Considered

- **Replace the task-list proxy with a third countable quantity** (task count,
  files-to-modify, estimated hours). Rejected: this ADR exists because two such
  proxies have already failed for a shared structural reason. A third would fail
  the same way.
- **Keep the 300-line check as a warning rather than a rejection.** Rejected:
  warning on a signal with r = 0.30 produces noise, and a warning nobody can act
  on trains planners to ignore the whole guardrail block.
- **Tighten the bands and enforce them harder.** Rejected: contradicted by the
  measurement. 71% of `M` plans already exceed the current ceiling. The ceiling
  is not under-enforced; it is wrong.
- **Block closure when the delivered diff wildly exceeds the declared label.**
  Rejected: that is the same gate moved later. Closure-time measurement collects
  evidence; it does not judge. If enforcement is ever warranted, it should be
  argued from the data this decision starts collecting.
- **Make thresholds per-project configurable.** Deferred, not rejected. It adds
  a configuration surface before there is data to justify per-project divergence.

## References

- `docs/prds/plan-sizing-recalibration-prd.md` — the measurements above and the
  full requirement set
- `docs/prds/task-size-guardrails-revision-prd.md` — superseded; its R-3 asserts
  the proxy rationale falsified here
- ADR-006 — plan atomicity and the plan/roadmap boundary, unchanged by this
- ADR-015 — telemetry informs guardrails, local-first
