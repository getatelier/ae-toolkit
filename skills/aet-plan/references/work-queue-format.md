# Work Queue Format

## Storage and Location

Task records are stored in git refs under `refs/aet/tasks/<task-id>`.

## Design Principle

Task records store **persistent facts** and the canonical `state` for each task. Reads (`aet status`, `aet next`, the orchestrator) project the stored `state` directly; they do not recompute pickability from git on every read. A separate `aet state audit` command reconciles stored state against git ground truth on demand.

## Schema

```json
{
  "source_prd": "docs/prds/feature-prd.md",
  "queue_updated_at": "2026-06-17T19:00:00Z",
  "tasks": [
    {
      "id": "T1",
      "title": "User can register",
      "plan_file": "docs/plans/T1-register-plan.md",
      "blocked_by": [],
      "blocks": ["T2"],
      "pending_blockers": 0,
      "size": "S",
      "state": "ready",
      "stage": null,
      "branch": null,
      "worktree": null,
      "merge_commit": null,
      "merged_at": null,
      "history": [
        {
          "from": null,
          "to": "planned",
          "at": "2026-06-17T19:00:00Z",
          "by": "sync",
          "evidence": null
        }
      ]
    }
  ]
}
```

## Fields

| Field                      | Type     | Description                                                            |
| -------------------------- | -------- | ---------------------------------------------------------------------- |
| `source_prd`               | string   | Path to the PRD that generated this queue (metadata only)              |
| `queue_updated_at`         | string   | ISO-8601 timestamp of the last queue update                            |
| `tasks`                    | array    | List of all tasks in the queue                                         |
| `tasks[].id`               | string   | Unique task identifier (e.g., T1, T2, auth-01)                         |
| `tasks[].title`            | string   | Human-readable task title                                              |
| `tasks[].plan_file`        | string   | Path to the plan.md for this task                                      |
| `tasks[].blocked_by`       | string[] | IDs of tasks that must complete before this task                       |
| `tasks[].blocks`           | string[] | IDs of tasks that depend on this task                                  |
| `tasks[].pending_blockers` | integer  | Count of blockers not yet terminal; maintained forward by the writer   |
| `tasks[].size`             | string   | S/M/L complexity label from the plan frontmatter                       |
| `tasks[].state`            | enum     | Canonical stored state (see Task States)                               |
| `tasks[].stage`            | string   | Pipeline stage sub-state when `state == in_progress`; otherwise `null` |
| `tasks[].branch`           | string   | Local git branch for this task, if any                                 |
| `tasks[].worktree`         | string   | Path to git worktree for this task, if any                             |
| `tasks[].merge_commit`     | string   | Merge commit SHA once the branch is on `origin/main`                   |
| `tasks[].merged_at`        | string   | ISO-8601 timestamp when the task was marked `merged`                   |
| `tasks[].history`          | array    | Append-only transition log: `{from, to, at, by, evidence}`             |

## Task States

Valid values for `tasks[].state`:

- `planned` — The plan file exists. No local branch has been created yet.
- `ready` — Pickable: all blockers are terminal.
- `blocked` — At least one blocker is not terminal.
- `in_progress` — A branch/worktree has been created and the task is being implemented.
- `awaiting_merge` — Implementation finished; waiting for merge to `origin/main`. **Does not satisfy blockers.**
- `merged` — The branch or `merge_commit` is an ancestor of `origin/main`. **Terminal.**
- `abandoned` — The task was explicitly cancelled with a documented reason. **Terminal.**
- `failed` — Implementation or transition failed; requires human inspection.

## State Transitions

`aet state transition` is the only writer of `state`. Legal transitions:

```text
sync:        ∅ → planned
sync:        planned → blocked            (pending_blockers > 0)
sync:        planned → ready              (pending_blockers == 0)
transition:  blocked → ready              (last blocker reached terminal)
transition:  ready → in_progress          (branch + worktree recorded)
transition:  in_progress.stage advances   (tdd → implement → qa → review → cso → sync-docs)
transition:  in_progress → awaiting_merge (pipeline exited 0; NOT terminal)
transition:  awaiting_merge → merged      (TERMINAL; merge_commit verified once)
transition:  any → abandoned (reason)     (TERMINAL)
transition:  in_progress → failed         (needs inspection; may re-enter)
```

When a task reaches a terminal state, the writer decrements each dependent's `pending_blockers` and promotes any that reach `0` from `blocked` to `ready`.

## Live / Settled Partition

Active task records hold only non-terminal tasks. When a task transitions to a terminal state (`merged` or `abandoned`), it is sealed into history and ledger records. The orchestrator, `status`, and `next` never load settled history for scheduling.

## Auditing Stored State

To reconcile stored state against git ground truth, run:

```bash
aet state audit
```

`audit` reports every task whose stored state disagrees with the state expected from `branch`, `merge_commit`, `blocked_by`, and `plan_file` existence. It never mutates the queue.

## Example

```json
{
  "source_prd": "docs/prds/auth-system-prd.md",
  "tasks": [
    {
      "id": "T1",
      "title": "User can register",
      "plan_file": "docs/plans/T1-register-plan.md",
      "blocked_by": [],
      "blocks": ["T2", "T3"],
      "pending_blockers": 0,
      "size": "M",
      "state": "merged",
      "stage": null,
      "branch": "T1-register",
      "worktree": null,
      "merge_commit": "a1b2c3d",
      "merged_at": "2026-06-17T20:00:00Z",
      "history": [
        {
          "from": null,
          "to": "planned",
          "at": "2026-06-17T19:00:00Z",
          "by": "sync",
          "evidence": null
        },
        {
          "from": "planned",
          "to": "ready",
          "at": "2026-06-17T19:01:00Z",
          "by": "sync",
          "evidence": null
        },
        {
          "from": "ready",
          "to": "in_progress",
          "at": "2026-06-17T19:05:00Z",
          "by": "next",
          "evidence": ".worktrees/T1-register"
        },
        {
          "from": "in_progress",
          "to": "awaiting_merge",
          "at": "2026-06-17T20:30:00Z",
          "by": "orchestrator",
          "evidence": null
        },
        {
          "from": "awaiting_merge",
          "to": "merged",
          "at": "2026-06-17T21:00:00Z",
          "by": "record-merge",
          "evidence": "a1b2c3d"
        }
      ]
    },
    {
      "id": "T2",
      "title": "User can log in",
      "plan_file": "docs/plans/T2-login-plan.md",
      "blocked_by": ["T1"],
      "blocks": ["T3"],
      "pending_blockers": 0,
      "size": "M",
      "state": "ready",
      "stage": null,
      "branch": null,
      "worktree": null,
      "merge_commit": null,
      "merged_at": null,
      "history": [
        {
          "from": null,
          "to": "planned",
          "at": "2026-06-17T19:00:00Z",
          "by": "sync",
          "evidence": null
        },
        {
          "from": "planned",
          "to": "blocked",
          "at": "2026-06-17T19:01:00Z",
          "by": "sync",
          "evidence": null
        },
        {
          "from": "blocked",
          "to": "ready",
          "at": "2026-06-17T21:01:00Z",
          "by": "transition",
          "evidence": "T1"
        }
      ]
    },
    {
      "id": "T3",
      "title": "User can reset password",
      "plan_file": "docs/plans/T3-reset-plan.md",
      "blocked_by": ["T1", "T2"],
      "blocks": [],
      "pending_blockers": 1,
      "size": "S",
      "state": "blocked",
      "stage": null,
      "branch": null,
      "worktree": null,
      "merge_commit": null,
      "merged_at": null,
      "history": [
        {
          "from": null,
          "to": "planned",
          "at": "2026-06-17T19:00:00Z",
          "by": "sync",
          "evidence": null
        },
        {
          "from": "planned",
          "to": "blocked",
          "at": "2026-06-17T19:01:00Z",
          "by": "sync",
          "evidence": null
        }
      ]
    }
  ]
}
```

In this example:

- `T1` is stored as `merged`; it has been sealed to history and is no longer in the live file.
- `T2` is stored as `ready` because `T1` is terminal.
- `T3` is stored as `blocked` because `T2` is not terminal.
