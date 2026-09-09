---
name: aet-ship
description: Pre-merge validation, PR creation, merge, and post-merge closure for AET tasks. Use when a task reaches awaiting_merge, when opening or merging a PR, or when `aet ship close` reports an ambiguous merge-verification result.
---

# aet-ship

Pre-merge gate, PR creation, merge, and post-merge closure for AET tasks.

## When to Use

- A task has reached `awaiting_merge` and you need to open or merge its PR
- You want to run the pre-merge gate (`aet ship gate`) before opening a PR
- You need to merge a task branch directly into its target branch
- You need to verify a squash merge before closing (`aet ship verify`)
- `aet ship close` reports an ambiguous merge-verification result and you need a decision procedure

## Commands

- `aet ship <plan_file|task_id>` — run the gate, then open a PR.
- `aet ship gate <plan_file|task_id>` — run the pre-merge gate only.
- `aet ship open <plan_file|task_id>` — run the gate and open a PR.
- `aet ship merge <plan_file|task_id> [--branch <target>]` — run the gate, detect conflicts against the target branch, merge directly into it, and record closure. `--branch` defaults to the resolved trunk branch.
- `aet ship split <plan_file|task_id> --message <msg> --paths <path>...` — split a monolithic PR range into logical commits. Repeat `--message`/`--paths` pairs in order. Fails closed if the resulting tree does not match the original HEAD.
- `aet ship verify <task_id|plan> [--squash-fallback]` — verify a branch has merged without mutating queue or ledger state. Prints `<merge-sha> <strategy> (<match-kind>)`.
- `aet ship close <task_id>` — record post-merge closure (task looked up in the live queue, then sealed history).
- `aet ship close <...> --delete-branch` — after successful closure, delete the remote and local feature branch atomically.

A bare task id given to `aet ship`, `aet ship gate`, `aet ship open`, or `aet ship merge` resolves to the task record (live queue first, then sealed history); the plan file is never consulted after intake.

`aet ship merge` checks for merge conflicts against `origin/<target>` before merging and records the resulting merge commit in the work queue.

## Pre-Merge Gate

`aet ship gate` (and pre-merge commands including `aet ship open` and `aet ship merge`) runs against the task's resolved feature branch and dedicated workspace, independent of the ambient checkout:

1. **Workspace and branch resolution**: Resolves the feature branch from the task record, locating its existing worktree or allocating a dedicated temporary worktree.
2. Rebase verification of the resolved feature branch against trunk.
3. Clean working tree check in the resolved workspace.
4. Test suite execution (`AET_SHIP_TEST_CMD`, defaulting to `make validate`) inside the resolved workspace, explicitly reporting the validated branch.
5. Optional coverage check (`AET_SHIP_COVERAGE_CMD`).
6. **Evidence resolution**: Resolves required evidence from the workflow definition via `gate.required_evidence`, then checks each required kind's verdict via `gate.check_task_evidence` — the same derivation the in-run stage gates use (ADR-070). A verdict that is missing, unreadable, or not `pass` pauses the gate, and the refusal names the kind, the producing stage, and the reason. Verify evidence for a `critical` task is the `verify` verdict written by `aet-verify`; no working-tree file is read.
7. Scope audit and commit count checks against the resolved feature branch and declared files in the plan spec.

## Integration Modes

### `pr-per-task` (default)

Each task ships in its own PR to the resolved trunk branch. Typical flow:

```bash
aet ship open FEAT-001
# After the PR merges:
aet ship close FEAT-001
```

### `single-pr` (epic mode)

Tasks integrate into a shared Integration Branch (declared via `aet epic set` or
`--base`) and the epic ships as one PR to trunk. Typical flow:

```bash
# Declare the active epic branch, title, and optional PR body:
aet epic set feat/epic-name --title "Feature: epic description"

# Run tasks against the active epic:
aet run

# Open the epic pull request targeting trunk:
aet ship open-epic

# Or when the epic branch is ready to merge directly to trunk:
aet ship merge feat/epic-name --branch main

# Close each task that was part of the epic, pointing at the epic branch as
# the integration target and the trunk merge commit if needed:
aet ship close FEAT-001 --target-branch feat/epic-name
```

`--target-branch` tells `aet ship close` which branch the task merged into.
Use the configured integration branch (the epic branch) for per-task closure;
use `main` when closing the epic itself after it merged to trunk.

## Merge Verification

`aet-ship` resolves the trunk branch from config →
`refs/remotes/origin/HEAD` → `main`. It never hardcodes `origin/main` as the
verification target. Run `aet setup verify` to see the resolved trunk for the
current checkout.

For squash merges, the original branch commits are not ancestors of the trunk
branch. `aet ship close` accepts `--merge-commit <sha>` to record the squashed
commit that actually landed on trunk.

## Closure

`aet ship close` is a single code transaction. It writes the terminal queue
state transition and records the `land` event in the content-addressed ledger
(including the plan content hash, PRD requirement ids, and merge ref). The
queue-ref update is atomic under a single `git update-ref --stdin`
transaction; the mandatory push of `refs/aet/*` must succeed before closure
reports success.

At terminal closure (`aet ship close` and `aet ship merge`), resilient plan
archival checks for a local plan file:

- If `docs/plans/active/<id>.md` (or legacy `docs/plans/<id>.md`) is present on
  disk, it is moved to `docs/plans/archive/<id>.md` and staged into git if
  `docs/plans/archive/` is tracked. Repositories can track `docs/plans/archive/`
  to retain historical settled plans or ignore it for 100% ephemeral plan files.
- If absent (e.g. in distributed execution where the spec lives only in the task
  record per ADR-061), an informational notice is logged and closure proceeds
  cleanly without error.

Do not ask an agent to update the plan footer, queue state, or ledger. Those
writes are owned by `aet ship close` and `aet gate submit`. In particular, never
hand-edit `.agents/ledger.jsonl`: it is content-addressed, so changing a line
leaves its id disagreeing with its body, and the next load refuses the entire
file until it is restored.

## Merge-Verification Exit Codes

`aet ship verify` reports merge status through named exit codes. Prefer it over
manual `git merge-base` / `gh` choreography.

| Exit code | Condition | Action |
|----------:|-----------|--------|
| `0` | Merge resolved | Use the printed SHA/strategy/kind; proceed to `aet ship close` if needed. |
| `10` | `EXIT_VERIFY_NO_MATCH` | No ancestry, no GitHub `mergeCommit`, and no diff match. The branch may be unmerged or outside the fallback window. |
| `11` | `EXIT_VERIFY_AMBIGUOUS` | Empty branch diff or more than one drift-match candidate. Resolve manually before closing. |

In any non-zero case, **do not delete the feature branch** until a human confirms
the merge status. Use `aet ship close --merge-commit <sha>` only when you have
independently verified the squash commit SHA on the resolved trunk branch.
