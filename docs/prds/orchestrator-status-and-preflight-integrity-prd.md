# PRD: Orchestrator Status and Preflight Integrity

## Overview

When running batch or single-plan execution via the `aet` CLI, preflight failures (such as a tripped systemic circuit breaker or invalid queue) currently occur silently after detaching, while `aet run` reports false-positive startup success. Furthermore, `aet status` conceals tripped circuit breaker states and dead runs, reporting that the queue is "ready" when execution is actually halted. This PRD defines synchronous preflight validation before detachment, full circuit breaker visibility in `aet status`, first-class CLI commands for breaker inspection and reset, and rigorous test isolation.

## Goals

- Eliminate silent failures during `aet run` and `aet run-one` by executing preflight validation synchronously before detaching.
- Provide immediate, truthful feedback in `aet status` regarding circuit breaker state, run health, and preflight blockers.
- Introduce first-class CLI commands (`aet breaker show`, `aet breaker reset`) to inspect and manage circuit breaker state without requiring low-level git ref manipulation.
- Ensure automated test suites never mutate or pollute the host checkout's git refs or circuit breaker storage.

## Non-Goals

- Replacing the detached subprocess execution model with foreground-only execution.
- Redesigning the circuit breaker algorithm itself (the 3-task threshold and signature classification rules remain unchanged).
- Modifying the telemetry JSON schema.

## Requirements

- **R-1**: Synchronous Preflight Validation: `aet run` and `aet run-one` validate all preconditions (systemic breaker state, queue parseability and integrity, agent CLI binary resolution, and worktree base branch) synchronously in the foreground process before spawning a detached daemon. If preflight validation fails, the CLI outputs diagnostics to stderr and exits with code 1 without claiming the run started.
- **R-2**: Startup Handshake in `_spawn_detached`: After spawning the background process, `_spawn_detached` performs a brief handshake (verifying the child process didn't terminate immediately on startup) before reporting success and returning 0.
- **R-3**: Circuit Breaker Visibility in `aet status`: `aet status` inspects `refs/aet/breaker` using `BreakerStore` and displays a prominent warning banner whenever the systemic circuit breaker is tripped, identifying the tripped signature, affected task count, and remedy.
- **R-4**: Last Run Failure Visibility in `aet status`: When no active detached runs are present, `aet status` inspects the most recent run telemetry and surfaces if the last run failed prematurely with its error reason.
- **R-5**: Breaker Management CLI Commands: Provide `aet breaker show` (displaying all tracked failure signatures and task tallies) and `aet breaker reset` (clearing `refs/aet/breaker` safely with user confirmation or explicit flags).
- **R-6**: Test Isolation Guardrails: Unit and integration tests for `BreakerStore` and `orchestrator` must execute strictly against temporary git fixtures (`tmp_path` / `git_repo`) and never write to the host repository's `refs/aet/breaker`.

## User Stories

- As an engineer running `aet run`, I want immediate feedback if a precondition or circuit breaker prevents the run from starting, so that I am never misled into believing tasks are executing when they are halted (satisfies: R-1, R-2).
- As an engineer checking `aet status`, I want to see whether the systemic circuit breaker is active or if the last run crashed, so that I have complete visibility into why tasks remain in the `ready` state (satisfies: R-3, R-4).
- As an operator managing runs, I want to inspect and reset circuit breaker state using standard `aet breaker` CLI commands rather than manual `git update-ref` surgery (satisfies: R-5).
- As a developer running test suites, I want test runs to be fully isolated so that test mock data never contaminates live repository state (satisfies: R-6).

## Acceptance Criteria

- [x] `aet run` fails immediately with exit code 1 and error diagnostics on stderr if `refs/aet/breaker` is tripped or the queue is invalid, before any detached process is announced (satisfies: R-1).
- [x] `aet run-one` fails immediately with exit code 1 if the target plan is missing, fails intake, or the breaker is tripped (satisfies: R-1).
- [x] `_spawn_detached` checks child process vitality before printing the run ID and exiting 0 (satisfies: R-2).
- [x] `aet status` displays a clear warning banner when `refs/aet/breaker` has a tripped signature (satisfies: R-3).
- [x] `aet status` reports the failure status and summary of the previous run when it exited non-zero (satisfies: R-4).
- [x] `aet breaker show` lists active failure signatures, per-task counts, and trip status (satisfies: R-5).
- [x] `aet breaker reset` deletes or resets `refs/aet/breaker` and outputs confirmation (satisfies: R-5).
- [x] All breaker and orchestrator tests run in isolated temp repositories and do not write to the host repo (satisfies: R-6).

## Technical Notes

- `src/aet/cli/main.py` should import `breaker.BreakerStore` and perform preflight checks before calling `_spawn_detached`.
- `src/aet/cli/status.py` should load `BreakerStore` and `telemetry.RunLogger` to incorporate breaker and last-run health checks.
- A new CLI group `src/aet/cli/breaker.py` should be added to the Typer command tree and exposed via `aet breaker`.
- Pre-existing tests in `tests/orchestrator/test_circuit_breaker.py` and other test modules must be audited to verify that no `BreakerStore` is initialized with default repo paths.

## Open Questions

- None. The architecture and failure modes are well-understood.

---

*Stage: synced*
*Next step: run `aet-ship`*
