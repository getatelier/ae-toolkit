---
subject: orchestrator-process-isolation
---

# Unify aet-work `run` with OS-Process Isolation

## Status

Accepted

## Context

The `aet-work` skill historically exposed two AFK loop commands:

- `run` — a cooperative loop that instructed the agent to clear its context between tasks and re-prime before the next one.
- `run-scripted` — a bash orchestrator that spawned a fresh OS process per task, guaranteeing isolation.

The cooperative `run` never worked in practice. No mainstream agent runtime (Claude Code, Kimi Code, Cursor, Windsurf, Aider) can clear its session and continue executing skill instructions mid-loop. The "CLEAR CONTEXT" instruction was ignored, context degraded, and task quality dropped after 3–4 iterations. The `run-scripted` command, added in May 2026, solved this with guaranteed process isolation and became the de-facto way to run the queue.

Maintaining two commands — one broken and one working — created confusion. Users had to choose between a command that looked simpler and a command that actually worked.

## Decision

Remove `run-scripted` entirely. Replace the old cooperative `run` with the proven OS-process isolation mechanism formerly known as `run-scripted`. No backward-compatible alias.

Changes:

- `aet-work run` generates a bash orchestrator and spawns it as a background OS process.
- `run-scripted` is removed from `aet-work/SKILL.md` and all live reference documentation.
- Historical PRDs and plans mentioning `run-scripted` are left untouched (they document past decisions).

## Consequences

- **Simpler mental model** — one obvious command to run the queue.
- **No confusion** — users no longer have to evaluate which mode to use.
- **Breaking change** — anyone who learned `run-scripted` will find it missing. The error is self-explanatory (`run-scripted` is not a documented command).
- **Historical docs preserved** — old PRDs and briefs still mention `run-scripted` for archaeological purposes.
- **Spawn-only semantics** — `aet run` returns immediately after spawning the detached orchestrator. The "waits for completion" wording in earlier versions of this ADR became false when `run` was daemonized (`nc-06`) and was later locked in by the Run Invocation Determinism PRD: `run-one` blocks and waits, while batch `run` returns at once and is observed via `aet run --follow <run-id>`.

## Alternatives Considered

1. **Keep `run-scripted` as an alias for `run`** — Rejected. An alias papers over the change without simplifying the skill. It also creates a maintenance burden (two names for one thing, forever).
2. **Fix cooperative `run`** — Rejected. This would require runtime vendors to support mid-session context resets triggered by skill instructions. No vendor has signaled intent to support this, and the skill cannot force it.
