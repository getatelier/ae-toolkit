---
blocked_by:
docs_sync: required
id: osp-01-preflight-and-startup-handshake
pipeline: standard
security_review: skipped
size: M
work_class: critical
---

# Plan: Synchronous Preflight Validation and Startup Handshake

## Context

PRD: docs/prds/orchestrator-status-and-preflight-integrity-prd.md (R-1, R-2)
Decision: ADR-075 (Synchronous Preflight Validation and Status Truthfulness), decisions 1 & 2.

`aet run` and `aet run-one` spawn detached background worker daemons via `_spawn_detached` in `src/aet/cli/main.py`. Currently, all preflight checks (such as systemic circuit breaker state in `refs/aet/breaker`, queue parseability, agent CLI binary resolution, and worktree base branch verification) execute only after detachment inside the background worker process. If a preflight check fails, the background process terminates immediately, but `aet run` has already returned exit code 0 to the caller, claiming the run started.

This plan moves preflight validation to execute synchronously in the foreground before detachment and adds a process vitality handshake to `_spawn_detached`.

## Intake Triage

- [x] Not a defect — adds synchronous preflight validation and startup vitality verification.
- [x] Sliced as an independent, testable horizontal capability for CLI execution.

## Task List

- [x] 1. Define a synchronous preflight validation function in `src/aet/cli/main.py` (or helper module) that verifies:
  - Systemic circuit breaker is not tripped (`breaker.BreakerStore(repo_root).load()`).
  - Work queue is parseable and valid (`backend.load()`).
  - Agent CLI binary resolves on `PATH` or configured binary path.
  - For `run-one`: target plan file exists and resolves to a valid spec.
  — M (traces: R-1)
- [x] 2. Integrate synchronous preflight validation into `aet run` and `aet run-one` in `src/aet/cli/main.py` so that validation failures write clear diagnostics to `stderr` and raise `typer.Exit(1)` before `_spawn_detached` is called — S (traces: R-1)
- [x] 3. Enhance `_spawn_detached` to perform an initial startup handshake checking that the spawned child process remains alive past the launch window before writing the pid file, logging the run start, and returning 0 — S (traces: R-2)
- [x] 4. Add unit and integration tests covering:
  - `aet run` failing fast synchronously when systemic circuit breaker is tripped.
  - `aet run` failing fast synchronously on queue corruption.
  - `aet run-one` failing fast on unresolvable plan or tripped breaker.
  - `_spawn_detached` catching immediate child exit.
  — M (traces: R-1, R-2)
- [ ] 5. Merge branch to main and verify integration — S

### Floor Check

- [ ] Expected diff is below the calibrated floor threshold
- [x] The change is limited to one subsystem (`src/aet/cli/main.py` and tests)
- [ ] `Files to Modify` substantially overlaps a sibling it is ordered against
- [ ] This is docs-only and its sole consumer is a single sibling

## Files to Modify

- `src/aet/cli/main.py`
- `tests/cli/test_run_preflight.py`
- `docs/CLI.md`

## Rejected Alternatives

- **Spawning foreground-only runs by default.** Rejected: batch runs are intended to run unattended in the background; synchronous preflight ensures failures are caught immediately while preserving detached execution for long-running batches.
