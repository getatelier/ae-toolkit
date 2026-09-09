---
subject: work-class-policy
---

# Work Class Is a Recorded Attribute; Zero-Review Auto-Merge Is Policy-Gated and Off by Default

## Status

Accepted (2026-07-15). Implements G3 (R-7, R-8, R-9) of the Roadmap Phase 4 PRD
(`docs/prds/roadmap-p4-two-human-ends-prd.md`). Builds on ADR-020 (sequencing is
not delegable; determinism over runtime discretion), ADR-011 (one deterministic
state writer), and ADR-013 (plans are the source of truth). The autonomous-merge
**enforcement wall** — a fail-closed merge gate plus a per-harness merge-guard —
is a separate decision recorded in ADR-029 (extends ADR-005) and is what makes
the off-by-default posture below un-bypassable rather than merely defaulted.

## Context

The AE Toolkit's north star is a "dark factory": drive human touches between
plan-approval and review toward zero, and concentrate the human minutes that
remain at the two ends — planning quality (intake) and review (exit). The exit
end is the throughput ceiling. To let *trusted* work eventually skip the human
review gate, the factory needs three things it does not have today:

1. A machine-readable record of **how risky each task is**. `docs/PIPELINE.md`
   already defines three work classes — Trivial / Normal / Critical — but only as
   a **routing** concept used by entry-point skills to pick a pipeline. The class
   is never stored on the task, so nothing downstream (the ledger, a review
   policy) can attribute a merge to a class. `work_class` appears nowhere in the
   toolkit (grep clean).

2. A **track record per class**: how often has work of a given class merged
   cleanly — reached `merged` with every required verdict `pass`, no failed stage,
   no rework? Without this, "trust this class" is a guess, not a measurement.

3. A **mechanism to auto-merge an enabled class** — present but shut — so that
   Phase 7 can enable class #1 as a config change backed by real data, not as new
   machinery built under deadline.

The risk is building an auto-merge path at all: it closes a task without a human
in the loop. The decision below is about how to make that mechanism exist safely
and provably off, and how to key it on a signal that is authored, not inferred.

## Decision

### 1. `work_class` is an authored, recorded plan-time attribute

`work_class` becomes an optional plan-frontmatter key whose value is one of
`trivial | normal | critical` — the lowercase machine form of the existing
`docs/PIPELINE.md` tiers. It **records** the tier as a stored field; it does not
redefine, re-score, or add tiers.

- It is **authored** at plan/triage time, never inferred at runtime. Heuristic
  auto-classification is rejected under the ADR-020 razor: a signal that gates a
  human-review bypass must be a deterministic, inspectable input, not an LLM
  judgment.
- It is **validated at intake** (an invalid value is rejected as part of the
  Phase 4 intake gate) and **carried onto the task record** so the ledger can
  attribute a merge to a class.
- A **missing** value is treated as `unclassified`, which is **never**
  zero-review-eligible. Unknown risk needs eyes — fail-safe.

`CONTEXT.md` and `docs/PIPELINE.md` are updated to record work class as a
machine-readable attribute, not only a routing concept.

### 2. A track-record reader measures per-class clean-merge history

A read-only reader computes, per `work_class`, the **clean-merge** count from the
telemetry archive (`~/.aet/telemetry/...`) and the execution log
(`.agents/work-history.jsonl`). A task counts as a clean merge when it reached
`merged` (terminal) with every required stage verdict `pass`, **no** failed stage
record, and no rework (no re-entry from `failed`, no repeated stage run). The
reader is surfaced as a read-only projection reporting each class's clean-merge
count and whether that class is currently zero-review-enabled. It computes; it
never enables.

### 3. Zero-review auto-merge exists, is policy-gated, and ships OFF

A policy (a config file) names the zero-review-**enabled** classes. It is
**empty by default**, so nothing auto-merges. A task auto-transitions
`awaiting_merge → merged` **only when both** hold:

1. its `work_class` is explicitly listed as enabled, **and**
2. its class track record (§2) meets the configured threshold.

When it fires, it drives the **same** merge + closure path a human merge would
(`aet-state record-merge` remains the sole writer of the `merged` transition —
ADR-011); no second closure writer is introduced. Absent either condition, the
task waits for a human decision. The shipped default (empty policy) satisfies
"the mechanism exists and is off."

### 4. Enablement is deferred to Phase 7, on data

Phase 4 builds the mechanism and ships it disabled. **Enabling zero-review class #1
is Phase 7's exit gate**, decided on Phase 7's track-record data. This is the
"dark factory gets dark from the exit door inward" sequencing: the exit door is
built now, opened later, by explicit human decision backed by measurement.

## Consequences

- **Easier:** A merge can be attributed to a work class, so the factory can
  measure first-pass-clean-merge rate per class — the evidence Phase 7 needs to
  justify opening the exit door.
- **Easier:** Enabling a proven class later is a config change against a real
  track record, not a code change under deadline.
- **Easier:** The risk signal is authored and inspectable, so review ranking and
  eligibility are deterministic and auditable end to end (no runtime judgment
  added anywhere).
- **Harder:** Planners acquire one more authored field. Mitigated by fail-safe
  defaulting: omitting it is always safe (`unclassified`, never eligible).
- **Neutral / bounded risk:** An auto-merge code path now exists. It is inert by
  construction (empty policy) and, per ADR-029, sits behind a fail-closed gate and
  a per-harness merge-guard, so "off by default" is enforced, not merely
  documented. Its correctness (provably off; fires only when enabled **and**
  qualified) is the highest-stakes item under test in the phase.

## Alternatives Considered

1. **Infer `work_class` heuristically at runtime** — Rejected. It gates a
   human-review bypass; inferring it violates the ADR-020 razor (a
   gate-skipping input belongs in authored data, not runtime discretion) and
   makes eligibility non-deterministic.
2. **Key eligibility on the workflow name or a per-task ad-hoc flag** instead of a
   work-class attribute — Rejected. The workflow names a stage *sequence*, not a
   risk tier (CONTEXT.md explicitly separates the two); a per-task flag has no
   track record to aggregate against. Work class is the unit that already carries
   a risk semantics and can accumulate history.
3. **Ship zero-review on by default (or auto-enable a class once its track record
   crosses a threshold)** — Rejected. Auto-enablement is the exit-door decision
   itself; making it implicit removes the human from the one gate this whole
   design exists to protect. Enablement stays an explicit human act on data
   (Phase 7).
4. **Threshold as a runtime judgment** instead of a mechanical count on recorded
   track record — Rejected. Same razor as (1): eligibility must be a mechanical
   function of stored facts.
5. **Two separate ADRs (attribute; policy)** — Rejected. The attribute exists to
   key the policy; splitting them records half a decision. One combined record.
6. **Redefine or re-score the three work-class tiers** — Rejected and out of
   scope. Phase 4 records the existing tier as a field; the Trivial/Normal/Critical
   definitions in `docs/PIPELINE.md` stand.
