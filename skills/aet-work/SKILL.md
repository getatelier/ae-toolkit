---
name: aet-work
description: Work queue management and sequential task execution. Use when you have plan.md files to run in order, want hands-free task execution, or need to check what's ready. Triggers on "run the queue", "pick next task", "what's next", "what's unblocked", "run all tasks", "keep working", "run tasks", "execute plans", "night shift", "AFK mode", "queue status", "init queue", "what can I work on", "run unblocked tasks".
---

# aet-work

Queue management for agentic engineering. The single job of this skill is to manage the ephemeral sprint board and orchestrate task execution — not to plan, implement, or review.

## When to Use

- You have multiple `docs/plans/*.md` files from a PRD breakdown
- You want to run tasks sequentially without manual intervention
- You want to check what's blocked, what's unblocked, what's done
- You want the "night shift" AFK loop

## Context

Run `aet context` and parse its JSON for session context (branch, repo
state, AGENTS.md, learnings, active plan/PRD stage); print the stage
banner it emits. Do not ask the user for this context manually.

## Prerequisites

This skill invokes AET helpers through the `aet` dispatcher (`aet state`, `aet status`, `aet queue sync`, `aet next`, `aet report`, `aet run`). `aet` must be on `PATH`. Run `aet setup link` once after installing skills. If you are developing in this repo, `make install-skills` runs it automatically.

## Mental Model: One Source of Truth Per Phase

The lifecycle has one source of truth per phase and one explicit handoff (ADR-061):

1. **Author** — `aet-plan` writes `docs/plans/{id}.md`. The file is the artifact.
2. **Intake** — `aet sprint add` ingests the file into the task record's `spec`. This is the handoff.
3. **Post-intake** — the task record's `spec` is the source of intent, stage, and terminal closure. The plan file may be rendered into a worktree as an ephemeral working copy; nothing writes back to it (R-4/R-19), so its contents are never authoritative.

The open-work board is an ephemeral sprint board that holds only the active tasks you have explicitly chosen to work on. `.agents/work-history.jsonl` is an optional, gitignored execution log.

This means:

- Approved plans do **not** automatically enter the sprint. Use `aet sprint add` to curate the queue.
- `aet gate review` reads plan files and reports their status without mutating the queue.
- `aet status` reports only the active sprint, not every approved plan.
- Plan drift is informational, not a hard gate.

### File roles

| File                         | Role                                                    | Tracked         |
| ---------------------------- | ------------------------------------------------------- | --------------- |
| `docs/plans/{id}.md`         | Authoring artifact; rendered into worktrees as a working copy | Yes             |
| `refs/aet/tasks/*`           | Ephemeral sprint board: active tasks only               | No (git refs)   |
| `.agents/work-history.jsonl` | Optional execution log for transitions and timing       | No (gitignored) |
| `.agents/ledger.jsonl`       | Content-addressed provenance ledger                     | No (gitignored) |

The ledger is an append-only, content-addressed event store. Do not edit it by hand: each event id is a SHA256 over its canonical fields, so any manual change leaves the id disagreeing with the body. The next load verifies every line and refuses the whole file, so every command that records provenance fails until the ledger is restored — and there is no rebuild path for it.

### Mutation guard

While a batch or `run-one` is live, the orchestrator writes a run lease to `.agents/work-queue.lease` (gitignored). Mutating commands — `add`, `aet queue sync`, and the `aet state` writers — refuse to run while another run holds a live lease, naming the owning run id. A lease whose process has exited is reclaimed as stale automatically.

Use `--force` only to deliberately override a lease you know is stale, or to make an urgent manual edit during a batch. It prints a loud warning and can corrupt a live run, so prefer re-running after the batch finishes.

Queue writes are also tamper-evident: a hand-edited state fails closed on read for mutating commands. Run `aet state audit` to inspect the unverified queue against git ground truth, and `aet state heal --apply` to reconcile and restamp the envelope. Read-only commands like `status` warn and continue.

The ledger (`.agents/ledger.jsonl`) is also system-managed. It is append-only and content-addressed; the only supported way to keep it valid is to avoid hand-editing and let `aet ship close`, `aet state transition`, and `aet gate submit` write events through the `Ledger` class. If the ledger appears wrong, run `aet state audit` first — it reports queue-vs-git drift, which is the question a wrong-looking ledger usually stands in for.

The `git-refs` backend is `schema_version`-stamped (ADR-055) and treats the live refs as ground truth. A previous chained `content_hash` over the task-ref set has been removed because a chain over a set is non-commutative and made independent writers conflict by construction. The tamper-evident `content_hash` protection therefore applies to the JSON backend only; the same `audit` / `heal --apply` recovery applies there.

### Queue lifecycle

1. Plan reaches footer stage `plan-approved`.
2. User runs `aet sprint add docs/plans/FEAT-001.md` → task appears in queue as `ready` (or `blocked` if it has pending blockers).
3. `aet next` or `aet run` transitions it through `in_progress` and its stage sub-states.
4. Task reaches `awaiting_merge`.
5. PR is opened and merged into the resolved trunk branch.
6. `aet-ship` verifies the merge commit is on the resolved trunk branch.
7. `aet-ship` records the terminal ledger event, appends closure to `.agents/work-history.jsonl`, and removes the task from the active sprint board. Plan files are transient working copies — closure no longer touches them (R-4/R-19).

## Task Backends

`aet` routes queue I/O through a pluggable storage backend. The default
`git-refs` backend stores queue state and the ledger in git refs under `refs/aet/*`.

### Configuration

Backends are configured in `.agents/aet-config.json` (team mode) or
`~/.aet/{config-slug}/config.json` (shadow mode). Use `aet configure --guided`
to create the file in the right place:

```bash
aet configure --guided --scope team --integration-mode pr-per-task
```

Run `aet-setup` (or `aet configure`) to write this file.

### The task store

`git-refs` is the only task store. It keeps queue state and the ledger in git
refs under `refs/aet/*`. Reads and writes push to and fetch from origin
best-effort except at closure, where the push is required. No GitHub access is
required beyond the git remote.

There is no backend to select, and no `task_backend` key: it was removed in 1.10
along with the JSON store it chose between. A config still carrying the key is
reported and ignored.

### Multi-machine posture

Queue and ledger state travel with the repo via `refs/aet/*` on origin. A fresh
clone must fetch them explicitly:

```bash
git fetch origin 'refs/aet/*:refs/aet/*'
```

`~/.aet` stays machine-local (config, telemetry, reports). Offline work is safe;
closure is the syncing boundary.

### GitHub Issues projection

GitHub Issues mirroring is configured on the `projections` axis. A forge is a
projection, never a task store. Add a projection entry to the same config file:

```json
{
  "integration_mode": "pr-per-task",
  "projections": [
    { "type": "github", "repo": "owner/repo", "label_prefix": "aet" }
  ]
}
```

AET states map to `aet:*` labels on the mirrored issues. `aet next` picks the
next open issue labeled `aet:ready` when a GitHub projection is enabled.

See [`references/github-backend.md`](references/github-backend.md) for the full
label contract, `gh` CLI requirements, issue body format, and sync behavior.

## Integration Modes

`integration_mode` selects how tasks close:

| Mode          | Behavior                                                                 |
| ------------- | ------------------------------------------------------------------------ |
| `pr-per-task` | Each task ships in its own PR to the resolved trunk branch (default).    |
| `single-pr`   | Tasks integrate into a shared epic/Integration Branch and ship together. |

Configure the mode with `aet configure`:

```bash
aet configure --integration-mode single-pr --scope user
```

The per-epic integration branch is a per-run input, not a config value. Use
`--base` with `aet run` or `aet run-one`:

```bash
aet run --base feat/epic-name
aet run-one --base feat/epic-name FEAT-001
```

`aet setup verify` prints the resolved `trunk_branch`, `integration_branch`, and
`integration_mode` with provenance.

## Commands

### `sprint add`

Promote a single approved plan into the runnable sprint.

```bash
aet sprint add docs/plans/FEAT-001.md
aet sprint add FEAT-001
```

Accepts a plan file path or a task ID. Refuses plans that are not `plan-approved`, terminal plans (`merged`, `abandoned`), and settled tasks. Adds the task to the queue. No commit or push happens at intake; plan durability is deferred to terminal closure. Blockers already settled in `work-history.jsonl` do not count toward `pending_blockers` — a plan whose blockers have all merged enters as `ready`, never deadlocked.

### `backlog add`

Scaffolded for gib-07; full backlog intake is not yet implemented.

### `review`

Scan all `docs/plans/*.md` files and print a human-readable status summary. Board columns derive positionally from the loaded workflow — entry stage → approved, terminal skill-less stage → queued, every other stage → in-progress — so variant workflow vocabularies render a sensible board without a per-workflow mapping table; queue states keep fixed columns. For the packaged `software` workflow:

- **Approved:** `plan-approved` (workflow entry stage)
- **Queued:** `synced` (terminal skill-less stage)
- **In Progress:** `implemented`, `qa-complete`, `reviewed`, `secure`, and any other non-terminal stage
- **Awaiting Merge:** `awaiting_merge`
- **Closed:** `merged`, `abandoned`

```bash
aet gate review
```

This reads the board from the active task backend; it does not modify the queue.

### `status`

Show the current sprint board.

```bash
aet status
```

Reports active task counts, a dependency table (pending `blocked_by` only), next ready tasks, failed tasks, and worktree health. Plan drift is reported as a warning only.

### `next`

Pick the next ready task and transition it to `in_progress`.

```bash
aet next
```

### `run`

AFK loop that runs queued tasks in isolated worktrees. Invokes the orchestrator.

```bash
aet run
```

Configuration and detailed behavior: [`references/queue-commands.md`](references/queue-commands.md).

### `run-one`

Run the full pipeline on a single plan without adding it to the queue.

```bash
aet run-one FEAT-001
```

### `sync`

Append-only reconciliation for plans already in or entering the queue. It does **not** auto-add every approved plan.

```bash
aet queue sync
```

Use `add` for explicit curation; use `aet queue sync` after queue edits or when resolving blocker DAGs.

### `state heal`

Seal terminal tasks and repair stale queue entries. Worktree removal is manual (`git worktree remove`) — see [`references/queue-commands.md`](references/queue-commands.md).

```bash
aet state heal
```

### `audit`

Reconcile stored state against git ground truth without mutating the queue. Human-run diagnostic only.

```bash
aet state audit
```

### `report`

Print execution telemetry summary.

```bash
aet report
```

### Plan-drift detection

List plan files that are not in the active queue or settled history. Informational only — reported automatically by `aet status` and `aet next`.

```bash
aet status
```

### Drift check

Detect tasks marked terminal whose commits are not on the resolved trunk branch — part of `aet state audit`.

```bash
aet state audit
```

### Marking tasks terminal

Manually mark a task as `merged` or `abandoned`. This is the only supported way to set a terminal status manually.

```bash
aet state transition FEAT-001 <current_status> merged
aet state transition FEAT-001 <current_status> abandoned --reason="duplicate"
```

**Rules:**

- Never mark a task `merged` without verifying its merge commit is on the resolved trunk branch.
- Never mark a task `done` manually; use `merged` or `abandoned`.
- `merge_verified` is a legacy status; use `merged` instead.

## Queue Terminal Statuses

| Status      | Meaning                                        | Set by                 |
| ----------- | ---------------------------------------------- | ---------------------- |
| `merged`    | Code is verified on the resolved trunk branch  | `aet-ship`             |
| `abandoned` | Task explicitly cancelled                      | `aet state transition` |
| `failed`    | Pipeline failed; needs human review            | Orchestrator           |

## Key Principles

- **Plans are the source of truth** — queue is a runtime view
- **Explicit curation** — only `add` puts work in the sprint
- **Ephemeral sprint board** — board state and `.agents/work-history.jsonl` are never committed
- **System-managed ledger** — `.agents/ledger.jsonl` is append-only and content-addressed; never edit it by hand
- **Forward-only state** — transitions are recorded by code and trusted on read
- **Queue-unaware pipeline** — individual skills know nothing about the queue
- **Session isolation** — `run` spawns fresh OS processes per stage
- **Agent-agnostic** — uses only git commands and generic session language
