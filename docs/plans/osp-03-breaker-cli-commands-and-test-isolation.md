---
blocked_by:
  - osp-01-preflight-and-startup-handshake
  - osp-02-circuit-breaker-and-last-run-status
docs_sync: required
id: osp-03-breaker-cli-commands-and-test-isolation
pipeline: standard
security_review: skipped
size: M
work_class: normal
---

# Plan: Circuit Breaker CLI Commands and Test Isolation

## Context

PRD: docs/prds/orchestrator-status-and-preflight-integrity-prd.md (R-5, R-6)
Decision: ADR-075 (Synchronous Preflight Validation and Status Truthfulness), decisions 4 & 5.

Currently, operators and agents have no dedicated CLI commands to inspect or clear the systemic circuit breaker stored in `refs/aet/breaker`. Resetting a tripped breaker requires running raw git ref commands (`git update-ref -d refs/aet/breaker`).

Additionally, tests exercising `BreakerStore` or orchestrator batches previously risked polluting the live repository's git refs if test fixtures inadvertently targeted the workspace directory rather than isolated temporary repositories.

This plan introduces first-class `aet breaker show` and `aet breaker reset` commands and audits all tests to guarantee absolute test isolation.

## Intake Triage

- [x] Not a defect — adds first-class breaker management CLI and enforces test fixture isolation.
- [x] Sliced as an independent, testable management capability.

## Task List

1. Create `src/aet/cli/breaker.py` implementing:
   - `aet breaker show`: displays tracked failure signatures, per-task counts, and whether systemic threshold is tripped — S (traces: R-5)
   - `aet breaker reset`: clears `refs/aet/breaker` with confirmation and output feedback — S (traces: R-5)
2. Register `aet breaker` command group in `src/aet/cli/main.py` and regenerate CLI docs via `aet docs generate` — S (traces: R-5)
3. Audit and update all tests in `tests/orchestrator/test_circuit_breaker.py` and related test files to ensure all `BreakerStore` instances strictly use isolated `tmp_path` git repositories and never touch the live repo root — M (traces: R-6)
4. Add CLI tests in `tests/cli/test_breaker.py` verifying `aet breaker show` and `aet breaker reset` behavior — S (traces: R-5)
5. Merge branch to main and verify integration — S

### Floor Check

- [ ] Expected diff is below the calibrated floor threshold
- [x] The change is limited to one subsystem (`src/aet/cli/breaker.py` and test suites)
- [ ] `Files to Modify` substantially overlaps a sibling it is ordered against
- [ ] This is docs-only and its sole consumer is a single sibling

## Files to Modify

- `src/aet/cli/breaker.py`
- `src/aet/cli/main.py`
- `tests/cli/test_breaker.py`
- `tests/orchestrator/test_circuit_breaker.py`
- `docs/CLI.md`

## Rejected Alternatives

- **Embedding breaker reset into `aet state reset`.** Rejected: `aet state reset` is a low-level state reconciliation tool; a dedicated `aet breaker` command group makes circuit breaker management discoverable and clean.
