---
subject: test-run-provenance
---

# `test_run` Records Carry Provenance: Observed Runs and Claimed Runs Are Not Interchangeable

## Status

Accepted (2026-07-26). Extends ADR-031 (runtime observation vs enforcement) — this is the same
null-honesty principle applied to the record type ADR-031 did not cover. Sibling to ADR-050
(per-adapter extraction). Motivated by
`reports/2026-07-25-aet-performance-observability-review.md`; delivered by the
`telemetry-adapter-parity` PRD (`tap-05`).

## Context

The telemetry archive holds one record type named `test_run`, written by **two emitters that
measure different things**:

- `_emit_wire_test_runs` (`orchestrator.py:603`) — **observed**. Reads the session log and writes
  the command the agent actually ran, with real start and end timestamps and the real exit code.
  It never knows how many tests were in the run.
- `_emit_test_run_from_verdict` (`orchestrator.py:711`) — **claimed**. Reads the QA agent's
  verdict and writes `start_time=None, end_time=None, exit_code=0` *literally*. It carries
  `tests_total` / `tests_passed` / `tests_failed`, which no session log exposes, and it fires only
  when the verdict passed — so `result: success` is true by construction, not by measurement.

Nothing on the record says which is which. Measured over the three AET projects: 313 observed and
112 claimed records, deduplicated to 410 distinct rows. The split is exact — every observed
record has timestamps and no test counts, every claimed record has counts and no timestamps — so
provenance is *recoverable by field signature* today, but only by someone who already knows the
two emitters exist. Every consumer that does not know reads a blended corpus: the observed pass
rate is 80%, the mixed corpus reads 85%, and mean durations are computed over a population 27% of
which has null duration and a hardcoded zero exit code.

74 groups hold a claimed record with **no observed twin** — the panel displays a test run AET
never saw. That is not a bug in the emitter; with a kimi-only reader (ADR-050) it is the expected
result of running under Claude Code, or of a test invocation the detector missed. But it is
indistinguishable, on the record, from a measurement.

ADR-031 established that AET reports what it measured and refuses to estimate the rest — kimi
`cost_estimate` stays null rather than being guessed, and ADR-035 carried that null-honesty into
the factory metrics. The verdict emitter writes a green, zero-exit, self-reported row into the
same table as measured rows, which is the same violation in a different column.

## Decision

**A `test_run` record states where it came from, and observed and claimed records are never
aggregated together.**

1. **`source` is part of the record.** `"wire"` for observed runs, `"verdict"` for claimed ones.
   Emitters set it explicitly; it is not inferred at read time from which fields happen to be
   populated.

2. **Timing, throughput, and pass-rate aggregates read observed records only.** Duration means,
   test-time totals, and success rates — in the panel, `aet desk`, and `track_record` — are
   computed over `source == "wire"`. A claimed record's `exit_code: 0` is a restatement of the
   verdict, and counting it as a passing test run double-counts the verdict as evidence for
   itself.

3. **Claimed records are kept, not deleted.** They uniquely carry test *counts*, which no session
   log exposes. The defect was the absence of a label, not the presence of the record.

4. **Provenance is displayed wherever the records are.** A surface that shows claimed records
   labels them and states that they are excluded from its aggregates. Excluding them silently
   would trade one unexplained number for another.

5. **Pre-change records are provenance-unknown, and are not backfilled.** Records written before
   this decision carry no `source`. They are read as unknown and excluded from observed-only
   aggregates. Field-signature inference would be right today and would quietly become wrong the
   moment either emitter's field set changes.

6. **A claim without an observation is a signal, not an error.** Once both readers exist
   (ADR-050) and detection is fixed, a `verdict` record with no `wire` twin means AET did not see
   a run the QA agent says happened. That is worth surfacing; it is not grounds for suppressing
   either record.

## Consequences

- Reported test durations and pass rates become measurements. The headline pass rate drops from
  the blended 85% toward the observed 80% — a correction, not a regression, and one that must be
  described as such wherever it is published.
- Every current consumer of `test_run` aggregates needs a filter added. Missing one leaves a
  blended number in place, which is why the aggregate surfaces are enumerated in the PRD rather
  than left to discovery.
- Historical records stay permanently unlabeled. Any longitudinal comparison spanning this change
  must say so; there is no clean pre/post series without one.
- `test_run` is now a record type with two legitimate populations. A future consumer must choose a
  provenance rather than inheriting a default, which is the intended friction.
- A schema field is added rather than a second record type introduced. The two populations share
  identity (`run_id`, `task_id`, `stage`, `scope`, `test_command`) and are matched on it to detect
  orphans; splitting them into separate types would make that join awkward for no gain.

## Alternatives Considered

- **Stop emitting verdict-derived records.** Rejected: they carry test counts nothing else does,
  and deleting the record hides the orphan signal along with the noise.
- **Infer provenance at read time from field signatures** (has duration ⇒ observed; has
  `tests_total` ⇒ claimed). Rejected as the forward contract: it is correct on today's data by
  coincidence of the emitters' current field sets, and it silently misclassifies the first time
  either emitter changes. It remains the only option for legacy records, which is exactly why
  those are labeled unknown rather than reconstructed.
- **Make the verdict emitter write `exit_code: null` instead of `0`.** Rejected as insufficient
  alone — it fixes the most obviously false field while leaving the record indistinguishable in
  kind. Provenance subsumes it; with `source` present, the record is honest about being a report.
- **Introduce a separate `test_claim` record type.** Rejected: the two populations are joined on a
  shared identity to find orphans, and a second type makes the routine query the awkward one.
