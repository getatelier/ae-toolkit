---
subject: runtime-observation-vs-enforcement
---

# Runtime Observation vs Enforcement: Budget Is Analytics-Only; Stalls Are Detected by Silence, Not the Clock

## Status

Accepted (2026-07-16). Roadmap Phase 5 (`content/fable-review/09-2026-07-10-roadmap.md`). Records an owner decision (2026-07-15) that **overrides** the roadmap's own Phase 5 line ("budget ceilings per task with kill-and-triage on overrun") — a future reader will otherwise expect a budget wall that deliberately does not exist.

**Decision item 2 is superseded by ADR-053** (2026-07-27): the stall default is no longer a flat 300 s on the command surface but a per-adapter value on `CLIAdapter`, and `--stall-timeout` is removed from `run`/`run-one`. The *principle* of item 2 — kill on evidence of silence, never on a stopwatch — is unchanged and still governs. Items 1 and 3 are unaffected.

## Context

Two Phase 5 mechanisms looked like enforcement in the roadmap but are better as observation.

**Cost.** The roadmap promised budget ceilings that kill-and-triage on overrun. But cost is only knowable **post-hoc**: `aet-work/lib/usage.py` parses it from captured CLI output at session exit, records `None` when unmeasurable (Kimi has no published per-token price), and explicitly refuses to estimate cost from prompt/response size. A real mid-session dollar tripwire is therefore impossible without introducing the estimation the module forbids — and the owner's intent is for cost to *inform*, not *govern*.

**Stalls.** The only liveness control today is a wall-clock timeout (`--task-timeout`, `aet-work/bin/orchestrator:1483`). A stopwatch cannot tell a slow-but-alive session (still emitting progress) from a wedged one; it kills both at the same deadline, punishing legitimately long work.

## Decision

1. **Budget is analytics-only.** Per-task token/cost is rolled up from stage telemetry onto the task's ledger record at close, for the desk and the scoreboard. **No code path reads it to gate, kill, throttle, or triage.** There are no cost ceilings and no budget-triggered termination. Consequently `budget` is **not** a failure class — a task cannot fail *because of* cost when cost terminates nothing. Null is preserved end-to-end (never zeroed).

2. **Stalls are detected by event-silence, not the clock.** A watchdog kills a session that has produced no output for `--stall-timeout` (default 300 s), via frh-03's process-group kill, classified `timeout`. The wall-clock `--task-timeout` is **retained only as a coarse backstop**, its default raised well above the stall interval so silence detection is the primary control. A session that keeps emitting is never killed for being slow.

The unifying principle: **observe honestly, enforce only on evidence — never on a guess (estimated cost) or a stopwatch (wall-clock).**

## Consequences

- Cost stays honest: no invented numbers, null where unmeasurable; and the "dark factory gets dark without a cost governor fighting it" — enforcement is not bolted onto a signal that cannot support it.
- Slow-but-alive work is no longer killed; a wedged-but-silent process is still caught within minutes by the watchdog.
- A pathological process that streams noise forever while doing nothing is caught only by the wall-clock backstop, not the silence watchdog — an accepted gap, which is exactly why the backstop is retained.
- Budget enforcement is now a deliberate *non-capability*. If it is ever wanted, it must be re-opened with a new ADR that also resolves the post-hoc-cost problem — it will not creep in silently.

## Alternatives Considered

- **Budget ceiling with kill-and-triage on overrun (the roadmap's original line)** — rejected: cost is post-hoc and often null, so enforcement would require forbidden estimation; and the owner wants cost to observe, not govern.
- **A live cost proxy (elapsed time or a max-tokens cap) as a mid-session dollar brake** — rejected: introduces exactly the estimated-cost signal `usage.py` refuses; couples execution control to a proxy that is not dollars.
- **Pure wall-clock timeout (keep today's model)** — rejected: cannot distinguish working from hung; kills slow-but-alive sessions.
- **Replace the wall-clock timeout entirely with silence detection** — rejected: a process that holds the pipe open but emits nothing, or streams forever, needs a floor; demote the clock to a backstop, do not delete it.
