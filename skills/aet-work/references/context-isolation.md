# Context Isolation in the AFK Loop

## The Problem

An AFK loop running multiple tasks in one session accumulates context:

- Task 1: 20k tokens consumed
- Task 2: +20k tokens = 40k total
- Task 3: +20k tokens = 60k total
- Task 4: agent starts missing obvious things, repeating itself, ignoring constraints

This is not hypothetical. The "smart zone" for LLMs is ~100k tokens. After that, quality degrades progressively.

## Why Cooperative Isolation Failed

Earlier versions of aet-work attempted a cooperative approach: the skill instructed the agent to clear its own context between tasks (via `/clear`, session restart, or equivalent). This failed on every tested runtime for the same reason — **no agent can reset its own context and continue executing skill instructions mid-session.** The instruction is ignored, context leaks, and quality degrades.

The only reliable solution is to move isolation out of the skill and into the OS process layer.

## OS-Process Isolation — `aet run`

`aet run` invokes the unified Python orchestrator that spawns a fresh OS process for every task:

```
Parent agent session (clean)
  → detects runtime
  → invokes `bin/orchestrator`
    → Orchestrator spawns Agent CLI process #1 (clean context, fresh process)
      → Task 1 completes, commits, exits
    → Orchestrator spawns Agent CLI process #2 (clean context, fresh process)
      → Task 2 completes, commits, exits
  → Orchestrator returns
  → Parent session remains clean
```

**Why this works:**

- **Physical process boundary** — the old context is unreachable; no compliance needed.
- **Universal** — works on every runtime that exposes a CLI (Claude Code, Kimi, Cursor, etc.).
- **Branch isolation enforced** — each task runs in its own git worktree on its own branch.
- **Queue state is the memory** — task and ledger state persists across process boundaries.

**Trade-offs:**

- Requires the agent CLI to support non-interactive/print mode
- Each task incurs CLI startup overhead (2–10s depending on runtime)
- The parent session must remain open to wait for the orchestrator to finish
- Interactive approval gates inside skills must be bypassed when running headless. The orchestrator sets `AET_EXECUTION_MODE=unattended`; skills that gate on human judgment (e.g., `aet-implement`) detect this and skip the gate, logging the bypass for auditability.

## Runtime Self-Detection

`aet run` does not scan `PATH` or maintain a hard-coded priority list. The agent executing the skill **self-reports** its own CLI command and flags. This means:

- Kimi Code running `aet run` generates a script that calls `kimi`
- Claude Code running `aet run` generates a script that calls `claude`
- A new agent CLI works immediately without any changes to the skill

The skill asks the currently running agent: "What CLI command and flags should the orchestrator use to spawn a fresh process of you?" The agent answers based on its own identity.

### Known Runtime Capabilities

| Runtime             | Non-interactive CLI | `aet run` support |
| ------------------- | ------------------- | ----------------- |
| Claude Code         | `claude --print`    | ✅ Supported      |
| Kimi Code CLI       | `kimi --print`      | ✅ Supported      |
| Cursor              | Limited             | ⚠️ Check CLI docs |
| GitHub Copilot Chat | Not available       | ❌ Not supported  |
| Aider               | `aider --message`   | ✅ Supported      |

> This table reflects known capabilities as of the skill's last update. Runtimes evolve; verify with your specific version.

## Without Context Isolation

| Task # | Cumulative Context | Agent Quality           |
| ------ | ------------------ | ----------------------- |
| 1      | 20k                | ✅ Sharp                |
| 2      | 40k                | ✅ Good                 |
| 3      | 60k                | ⚠️ Slight decline       |
| 4      | 80k                | ⚠️ Missing details      |
| 5      | 100k               | ❌ Repetitive, confused |
| 6+     | 120k+              | ❌ Unreliable           |

## With Context Isolation

| Task # | Context Per Task | Agent Quality |
| ------ | ---------------- | ------------- |
| 1      | 15k              | ✅ Sharp      |
| 2      | 15k              | ✅ Sharp      |
| 3      | 15k              | ✅ Sharp      |
| ...    | 15k              | ✅ Sharp      |
| 20     | 15k              | ✅ Sharp      |

## Stage-Group Session Reuse (`standard` isolation)

For `standard` isolation, the orchestrator groups consecutive pipeline stages that share the same `session_group` and runs them in a single agent session instead of spawning one session per stage.

```
Parent agent session (clean)
  → invokes `aet run-one docs/plans/FEAT-001.md`
    → Orchestrator spawns Agent CLI process #1 (clean context)
      → Stage group 1: aet-tdd → aet-implement, then aet-qa
      → Commits between stages
    → Orchestrator spawns Agent CLI process #2 (clean context)
      → Stage group 2: aet-review
    → Orchestrator spawns Agent CLI process #3 (clean context)
      → Stage group 3: aet-cso, then aet-sync-docs
```

**Why this helps:**

- Reduces repeated file reads, test suite runs, and environment rediscovery within a group.
- Keeps the same physical process boundary between groups, so context is still reset between unrelated work.
- `minimal` and `full` isolation are unchanged.

**Verification and fallback:**

After a group session exits, the orchestrator verifies that the stage recorded on the task record reached the expected final stage. If the group session did not advance far enough, the orchestrator falls back to the original per-stage execution for that group, resuming from the recorded stage.

## Parallel Execution Is Safe

Parallel execution of independent tasks is safe because isolation is enforced at two independent layers:

1. **Git worktree isolation** — each task runs in a separate git worktree on its own branch. Files, git state, and branch history are physically separate. Two tasks cannot collide on the same working tree because each has its own `.git/worktrees/<id>` directory.

2. **OS process isolation** — each task runs in its own agent CLI process. There is no shared memory, no shared context, and no way for one agent to read another's state. The only shared resource is the backend state, and access to that is serialized.

Because these layers are independent, doubling the number of concurrent tasks does not weaken isolation. Task #1 and Task #10 are as isolated from each other as Task #1 and Task #2 were in sequential mode.

## Drain-on-Failure Behavior

When a task fails under parallel execution, the orchestrator does not kill the other running tasks. Instead it:

1. Records the failed task's status
2. Stops spawning new tasks
3. Waits for all currently running tasks to finish
4. Exits with a non-zero status

This preserves work already in progress. If Task #3 fails while Tasks #4 and #5 are running, Tasks #4 and #5 complete normally and their results are saved. Only new spawns are halted. The user can inspect the failed branch, fix the issue, and re-run `aet run` to resume.

## Queue-Update Invariant

Under parallel execution, only the main orchestrator loop reads and writes task state. Child processes (the agent CLI invocations) do not touch task backend records. This eliminates race conditions:

- The orchestrator spawns a child
- The child runs to completion and exits
- The orchestrator polls for completion and only then does it update the queue

Queue mutations are serialized by the backend storage and lock manager. The orchestrator wraps every load→mutate→save cycle in this lock, and `aet state` acquires the same lock around every transition. No database is required, but file locking is required even within a single process because child CLI sessions and the orchestrator itself can write concurrently.

## Plan Snapshot Semantics

When `aet run` or `aet run-one` materializes a task worktree, the orchestrator renders the task record's `spec` into a plan file in that worktree before any pipeline stage runs. The rendered copy is **by content, not by git state**: the agent reads the spec the operator just edited, not a stale committed copy.

The overlay is a **snapshot** taken at worktree creation and refresh. Editing a plan in the main checkout after the task has started does **not** propagate into the running worktree. Closure later operates on the post-merge checkout, so there is no write race between the two copies.

This behavior is intentional. Plan edits are local-only until terminal closure; the queue record and ledger state travel with the repo via `refs/aet/*`. See [`queue-commands.md`](queue-commands.md) for intake semantics and ADR-054 / ADR-055 for the durability contract.

## Further Reading

- `bin/orchestrator` — the unified Python orchestrator invoked by `aet run`
- `lib/aet_queue.py` — queue read/write operations with wrapper-format preservation
- `lib/cli_adapter.py` — CLI detection and command building for Kimi and Claude
- `references/parallel-execution.md` — deep dive on concurrency caps and resume behavior
