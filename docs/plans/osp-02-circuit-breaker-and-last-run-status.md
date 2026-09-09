---
blocked_by:
docs_sync: required
id: osp-02-circuit-breaker-and-last-run-status
pipeline: standard
security_review: skipped
size: M
work_class: normal
---

# Plan: Circuit Breaker and Last-Run Status Reporting

## Context

PRD: docs/prds/orchestrator-status-and-preflight-integrity-prd.md (R-3, R-4)
Decision: ADR-075 (Synchronous Preflight Validation and Status Truthfulness), decision 3.

`aet status` displays summaries of queue tasks and registered worktrees, but completely ignores `refs/aet/breaker`. When a systemic circuit breaker is tripped, `aet status` continues to report `ready: N` and `No failed tasks`, creating the false appearance that execution is healthy when batch runs cannot proceed.

Furthermore, when no active detached run is running, `aet status` simply prints `No active detached runs`, giving no visibility into whether the previous run succeeded or terminated abnormally.

This plan updates `aet status` to inspect `refs/aet/breaker` and recent telemetry, surfacing prominent breaker warning banners and previous run failure diagnostics.

## Intake Triage

- [x] Not a defect — enhances status visibility to truthfully report circuit breaker state and last-run termination causes.
- [x] Sliced as an independent, testable monitoring capability.

## Task List

1. Update `src/aet/cli/status.py` to load `breaker.BreakerStore` and check `systemic_tripped()` — S (traces: R-3)
2. Render a prominent warning banner in human-readable and JSON projection output when the systemic circuit breaker is tripped, specifying the signature, affected task count, and remedy — S (traces: R-3)
3. Update `src/aet/cli/status.py` to inspect the latest run record in telemetry via `telemetry.RunLogger` when no active detached runs exist, surfacing if the previous run terminated with failure (`outcome: failure`), its exit code, and error summary — M (traces: R-4)
4. Add comprehensive unit tests in `tests/cli/test_status.py` covering:
   - `aet status` rendering breaker warning banner when `refs/aet/breaker` is tripped.
   - `aet status --json` outputting breaker trip status in JSON projection.
   - `aet status` displaying previous run failure information when telemetry records an error.
   — M (traces: R-3, R-4)
5. Merge branch to main and verify integration — S

### Floor Check

- [ ] Expected diff is below the calibrated floor threshold
- [x] The change is limited to one subsystem (`src/aet/cli/status.py` and tests)
- [ ] `Files to Modify` substantially overlaps a sibling it is ordered against
- [ ] This is docs-only and its sole consumer is a single sibling

## Files to Modify

- `src/aet/cli/status.py`
- `tests/cli/test_status.py`
- `docs/CLI.md`

## Rejected Alternatives

- **Failing `aet status` with non-zero exit code when breaker is tripped.** Rejected: `aet status` is an informational diagnostic command (ADR-033: projections fail open). It should return 0 while rendering clear visual warnings.
