# Migrating to `aet state`

## When to Read This

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy queue file path in migration guide -->
You are upgrading an existing project that already has `.agents/work-queue.json` to use the centralized `aet-state` helper — now the `aet state` subcommand — for state transitions and transition validation.
<!-- aet-lint: on -->

## What Changes

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy queue mechanics in migration guide -->
Before `aet-state`, the work queue stored `status` directly in JSON and skills mutated it by hand. After `aet-state`, the queue records `state` forward through validated transitions, and `aet state audit` reconciles stored state against git ground truth on demand.
<!-- aet-lint: on -->

## One-Time Repair

Run this on any existing queue to detect stale or invented states without mutating the queue:

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy queue file path in migration repair command -->
```bash
aet state audit .agents/work-queue.json
```
<!-- aet-lint: on -->

This prints stored and expected statuses for every task. If a task is stored as `awaiting_merge` or `merged` but git says otherwise, inspect manually and use `aet state transition` to repair.

To force a full repair:

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy queue file path in migration repair commands -->
```bash
# 1. Audit stored state against git ground truth
aet state audit .agents/work-queue.json

# 2. Sync the open-work board (rebuilds blocker DAG, drops terminal records)
aet queue sync

# 3. Re-add any approved plans that should be on the board with `aet sprint add`

# 4. Check for remaining discrepancies
aet status
```
<!-- aet-lint: on -->

## Common Stale States

| Stored state     | Likely expected status | Cause                                  |
| ---------------- | ---------------------- | -------------------------------------- |
| `merged`         | `in-progress`          | Branch not yet on the resolved trunk branch |
| `awaiting_merge` | `in-progress`          | Pipeline finished but PR not merged    |
| `merge_verified` | `merged`               | Legacy alias; normalized automatically |
| `in_progress`    | `planned`              | Worktree removed, branch deleted       |

## Ongoing Maintenance

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy queue file path in migration guide -->
- Run `aet state audit` when you suspect stored state has drifted from git reality
- Never edit `.agents/work-queue.json` by hand; use `aet state transition`
- If a task was abandoned with a `failure_reason`, clear the reason before transitioning it back to active
<!-- aet-lint: on -->
