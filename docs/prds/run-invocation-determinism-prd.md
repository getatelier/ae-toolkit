# PRD: Run Invocation Determinism

## Overview

`aet run` and `aet run-one` expose execution mode, four timeout/tuning knobs, and a
log-streaming follower as agent-facing choices. Every one of those choices is made fresh
by whichever AI coding agent happens to be driving the session, and it varies between
providers and between sessions of the same provider. The observable cost is a repeating
loop: a run is started with a stall timeout too short for the QA stage, the watchdog kills
it, the session is left dirty, and the operator spends several exchanges recovering — before
any productive work happens. Separately, the one correct way to observe a run
(`aet run --follow`) replays the entire log into the agent's context, so a run that produces
tens of thousands of lines costs tens of thousands of lines of context even when driven
correctly.

This PRD removes the choices. Execution becomes single-mode (always detached), observation
returns a fixed-size report instead of a log, supervision defaults move into the per-provider
`CLIAdapter` record, and the plan argument accepts a task id like the rest of the CLI. The
agent is left with one literal command and no parameters to select.

## Goals

- Reduce the agent-facing surface of `aet run` / `aet run-one` to a plan id, with zero
  tuning flags and zero execution-mode choices.
- Make the token cost of observing a run bounded and roughly constant, independent of how
  much output the run produced.
- Encode supervision timeouts per agent provider in code, so the value that works for a
  full pytest suite is not rediscovered per session.
- Eliminate the non-terminating wait path in the run follower.

## Non-Goals

- **An `aet run logs` escalation command.** Deferred until the bounded report proves
  insufficient in practice; designing the escape hatch before observing what is missing
  would guess at the wrong shape. Parked in `content/backlog/`.
- **Parallel-run aggregation.** Per-child status tables for spawned agents are additive to
  the same code path and can follow.
- **Auto-resume of interrupted runs.** This mitigates the consequence of hangs; this PRD
  removes causes of hangs instead.
- **Ledger telemetry of resolved supervision parameters.** Worth having to prove the
  variance is gone, but it is measurement, not the fix.
- **Integration with the config-file overhaul** (`docs/prds/aet-config-file-overhaul-prd.md`).
  Supervision defaults live on `CLIAdapter` as code and deliberately do not enter a config
  file, avoiding overlap with that PRD.
- **A backward-compatibility window.** Per project convention, removed flags are removed,
  not deprecated.

## Requirements

- **R-1**: `aet run` and `aet run-one` always execute the orchestrator as a detached
  process in its own session. The `--foreground` flag is removed, and no code path runs the
  orchestrator as the invoking session's own process.
- **R-2**: `aet run-one <id>` waits for the detached run to reach a terminal state and exits
  with the run's exit code, without streaming run output to stdout.
- **R-2b**: `aet run` (batch queue) returns immediately after spawning, printing the run id
  and log path, so AFK execution is never held open by the invoking session.
- **R-2c**: `aet run --follow <run-id>` waits for an already-spawned run to reach a terminal
  state and exits with its exit code, without streaming run output. This is the observation
  path for batch runs; it is the same waiter R-2 uses, differing only in that the run
  already exists.
- **R-3**: On completion, the command emits a fixed-shape report: one line per stage with
  status, duration, and exit code, plus an overall result. Report length is bounded and does
  not scale with the volume of run output.
- **R-4**: On failure, the report additionally includes a bounded excerpt of the failing
  stage, capped at a fixed line count.
- **R-5**: The wait path terminates in all cases, including when the pid file is absent or
  unparseable and no returncode file exists.
- **R-6**: `_run_with_live_tee` keeps both its stdout echo and its bounded tail buffer
  unchanged. The echo is what populates the detached run's `output.log`, and the tail buffer
  is what claude's usage parsing reads; usage must continue to resolve non-null for both the
  `json-envelope` (claude) and `wire-file` (kimi) adapters. Token reduction is achieved by
  changing what the *follower* emits (R-3), never by silencing the run.
- **R-7**: `CLIAdapter` carries per-provider supervision defaults for the stall timeout and
  the wall timeout, and the orchestrator resolves them from the active adapter rather than
  from a hardcoded constant or a caller-supplied flag.
- **R-8**: The per-adapter stall timeout default is long enough that a full pytest suite
  emitting output is never killed by it, and the wall-clock backstop default is set well
  above the stall interval. This supersedes ADR-031 decision item 2, which fixed the stall
  default at 300s; a new ADR records the supersession and preserves ADR-031's principle
  (enforce on evidence of silence, not on a stopwatch).
- **R-8b**: An ADR is added superseding ADR-031 decision item 2 only. ADR-031 remains
  accepted for items 1 and 3, and ADR-031 is annotated to point at it.
- **R-9**: `--isolation` and `--stall-timeout` are removed from the `run` and `run-one`
  command surface. `--max-jobs` is retained on `aet run` only (batch concurrency cap,
  default `4`, maximum `8`) and is not accepted by `aet run-one`. `--base`, `--on-failure`,
  `--task-timeout`, and `--cli-bin` are retained as semantic per-run inputs: `--base` names
  the epic integration branch under `single-pr` mode; `--on-failure` selects failure routing
  policy (ADR-030); `--task-timeout`
  is the wall-clock backstop ADR-031 retains; `--cli-bin` selects which agent CLI runs the
  work, and therefore — via R-7 — which supervision defaults apply.
- **R-10**: `aet run` and `aet run-one` accept a bare task id resolved to
  `docs/plans/<id>.md`, with the same passthrough-and-error semantics as `aet ship`.
- **R-11**: A single shared plan-argument resolver is used by `run`, `run-one`, `ship`,
  `sprint`, and `backlog`; the duplicate implementations are removed. It adopts `ship`'s
  semantics — a `.md` value passes through unchecked, anything else resolves to
  `docs/plans/<id>.md`, and an unresolvable id raises naming both interpretations. `sprint`
  and `backlog` adapt at their call sites to preserve their current `None`-returning
  contract.
- **R-11b**: The behavioral differences between the three current resolvers are preserved or
  deliberately changed, not silently altered: `sprint`/`backlog` today accept a
  non-existent `.md` path by falling through to id resolution (yielding
  `docs/plans/<name>.md.md`), and take a `plans_dir` parameter rather than hardcoding it.
  Each divergence is either retained at the call site or its change is recorded.
- **R-12**: The `aet run` start output names the on-disk log path (so a human can tail it
  with standard tools) and points to `aet run --follow <run-id>` as the way to wait for the
  bounded report. It must not describe `--follow` as streaming or tailing output.
- **R-13**: `.agents/commands/aet-work.md` is updated to match: `--foreground` removed from
  its flag list and anti-patterns section, and its `aet run` / `aet run-one` sections
  rewritten for the R-2/R-2b/R-2c behavior. It is a live consumer of the removed flag
  (lines 38, 44, 49).
- **R-14**: ADR-004's consequence text, which states that `run` "spawns it as a background OS
  process, and waits for completion", is corrected — it was already made false by nc-06's
  daemonization, independent of this PRD.
- **R-15**: CONTEXT.md carries glossary entries for `run id`, `detached run`, `follower`,
  `stall timeout`, `wall backstop`, and `bounded report` — added during scope validation.
  They are verified against shipped behavior and corrected if drifted.

## User Stories

- As an operator, I want `aet run <id>` to be the entire invocation so that no agent has a
  timeout or execution-mode decision to get wrong (satisfies: R-1, R-9, R-10)
- As an operator, I want a run's outcome summarized in a few lines so that observing a long
  run does not consume the session's context budget (satisfies: R-2, R-3, R-12)
- As an operator, I want a failing run to tell me what failed without my reading the log so
  that diagnosis does not require a second expensive step (satisfies: R-4)
- As an operator, I want the QA stage to survive a full test suite so that I stop losing runs
  to a watchdog tuned for a shorter stage (satisfies: R-7, R-8)
- As an operator, I want a run that dies badly to report a failure promptly so that the
  session never waits on a process that will never finish (satisfies: R-5)
- As a maintainer, I want one plan-argument resolver so that a fifth caller does not fork the
  convention again (satisfies: R-11)
- As a maintainer, I want token capture to keep working for both agent CLIs so that removing
  live echo does not silently break usage records for one provider (satisfies: R-6)

## Acceptance Criteria

- [ ] `--foreground` is absent from `run` and `run-one`, and `_exec_orchestrator` has no
      remaining caller (satisfies: R-1)
- [ ] `aet run-one <id>` returns only after the run reaches a terminal state, exits with the
      run's exit code, and prints no run output lines (satisfies: R-2)
- [ ] `aet run` returns before the run completes, printing a run id and log path
      (satisfies: R-2b)
- [ ] `aet run --follow <run-id>` on a live run returns only at terminal state with the run's
      exit code and prints no run output lines (satisfies: R-2c)
- [ ] The completion report has a fixed line count for a successful run regardless of log
      size, verified against runs with large and small logs (satisfies: R-3)
- [ ] A failing run's report includes a failing-stage excerpt capped at the configured line
      limit (satisfies: R-4)
- [ ] With the pid file deleted and no returncode file present, the wait path exits non-zero
      rather than looping (satisfies: R-5)
- [ ] The run `output.log` is non-empty and complete for a detached run, and usage parsing yields
      non-null usage for the `json-envelope` and `wire-file` adapters, asserted by a test per
      adapter (satisfies: R-6)
- [ ] `CLIAdapter` exposes stall and wall timeout fields, and the orchestrator watchdog reads
      the resolved adapter's values (satisfies: R-7)
- [ ] The default stall timeout exceeds the observed silent interval of a full suite run,
      and the wall backstop default exceeds the stall interval (satisfies: R-8)
- [ ] An ADR exists that supersedes ADR-031 item 2 and no other item, and ADR-031 links to it
      (satisfies: R-8b)
- [ ] `--isolation` and `--stall-timeout` are rejected as unknown options by `run` and
      `run-one`; `--max-jobs` is accepted by `run` and rejected by `run-one`; `--base`,
      `--on-failure`, `--task-timeout`, and `--cli-bin` are still accepted and still take
      effect (satisfies: R-9)
- [ ] `aet run-one <id>` and `aet run-one docs/plans/<id>.md` resolve identically, and an
      unresolvable id errors naming both interpretations (satisfies: R-10)
- [ ] `ship`, `sprint`, and `backlog` import the shared resolver, and their local copies are
      deleted (satisfies: R-11)
- [ ] `sprint add <id>` and `backlog add <id>` behave identically to today for a valid id, a
      missing id, and a non-existent `.md` path, asserted by tests (satisfies: R-11b)
- [ ] `.agents/commands/aet-work.md` no longer documents `--foreground`, and its `aet run` /
      `aet run-one` sections match the R-2/R-2b/R-2c behavior (satisfies: R-13)
- [ ] ADR-004's statement that `run` "waits for completion" is corrected (satisfies: R-14)
- [ ] CONTEXT.md defines `run id`, `detached run`, `follower`, `stall timeout`, `wall
      backstop`, and `bounded report` (satisfies: R-15)
- [ ] Run-start output prints the log file path and describes `--follow` as waiting for a
      report, not as tailing output (satisfies: R-12)

## Technical Notes

**Detachment and blocking are independent axes.** The orchestrator already spawns detached
with `start_new_session=True` (`src/aet/cli/main.py`), writing the run log, `pid`,
and `returncode` into `.agents/runs/<run-id>/`. R-1 removes the *other* mode
(`--foreground` in `src/aet/cli/main.py`), in which the orchestrator runs as
the session's own process and `_run_with_live_tee` mirrors every line to stdout
(`src/aet/cli/orchestrator.py`). R-2 then makes the default command wait on the already-
detached process. Nothing about where the process runs changes; only the caller's behavior
after spawning does.

**The follower already waits correctly; it observes too loudly.** `_follow_run`
(`src/aet/cli/main.py`) already terminates on both pid death and the returncode file — the
supervision logic is sound. Its cost is that it replays the log from byte zero
and echoes every subsequent line. R-3 replaces the
output, not the waiting. R-5 covers the one genuine gap: when `pid` is `None` and no
returncode file exists, the loop has no exit condition.

**The tee must not be "optimized" — it is the log writer.** `_run_with_live_tee`
(`src/aet/cli/orchestrator.py`) echoes each line to stdout and accumulates a bounded tail.
In detached mode the orchestrator's stdout is redirected to `output.log`
by `src/aet/cli/main.py`, so that echo is what produces the log file. Once `--foreground` is gone
(R-1), the echo has no path to an agent's context at all, and silencing it would empty the
log while breaking claude's usage parsing — claude's usage arrives on stdout as a JSON
envelope read from the tail, whereas kimi's is read post-exit from `~/.kimi-code` session
wire files (`src/aet/cli_adapter.py`). That asymmetry would present as "claude token
capture broken" and be easy to misattribute to
`tap-07-claude-token-capture-verification`. R-6 is therefore a *non-change* requirement with
a regression test per adapter: the token win comes entirely from the follower (R-3), not
from suppressing run output.

**Supervision defaults belong on the adapter.** `CLIAdapter` (`src/aet/cli_adapter.py`) is a
frozen dataclass with two entries. Adding timeout fields is passive data: `build_cmd` is
untouched, so neither CLI's invocation string changes, and the watchdog
(`src/aet/cli/orchestrator.py`) reads the values instead of a caller-supplied flag defaulting to
300 seconds. That 300-second default is the direct cause of the QA
stage being killed during a full suite.

**This PRD reverses one prior decision and recalibrates another.** `--foreground` was not an
accident: `docs/plans/nc-06-run-daemonization.md` task 4 added it deliberately as a debugging
affordance when `run` was daemonized, and `.agents/commands/aet-work.md` documents
it. R-1 reverses that, on the grounds that the debugging value is now served by the on-disk
log (R-12) at no risk of flooding an agent's context. Separately, the 300-second stall
default is ADR-031 decision item 2, chosen deliberately — so R-8 is a recalibration of a
documented decision, not a bug fix, and R-8b records it. ADR-031's principle survives intact:
kill on evidence of silence, never on a stopwatch.

**The determinism boundary: intent may vary, parameters may not.** This PRD removes agent
*parameter* choices, not operator *intent* choices. `run` and `run-one` deliberately keep
different waiting behavior (R-2 / R-2b) because the difference is carried by which command
the operator invoked — one plan versus an AFK queue — and two agents facing the same
situation would not disagree about which they were asked to do. A flag like
`--stall-timeout`, by contrast, has one correct value the agent cannot derive, so it becomes
adapter data (R-7). The test for any future addition: if two correct agents given identical
repo state could produce different observable results, it belongs in code; if the difference
expresses what the operator wanted, it belongs on the surface.

**`--base` is a semantic input, not a knob.** The flag-removal boundary is *supervision and
tuning* versus *what work is being done*. `--base` falls on the semantic side: under
`single-pr` integration mode it names the per-epic integration branch, and the `aet-work`
skill documents it explicitly as "a per-run input, not a config value"
(`skills/aet-work/SKILL.md`). Removing it would break `single-pr` epic
integration outright. It also cannot move onto `CLIAdapter` like the timeouts, since it
varies per run rather than per provider. Any later cleanup that sweeps up "remaining run
flags" must preserve it.

**The plan-id resolver already exists three times.** Formerly duplicated across commands,
`resolve_plan_arg` in `src/aet/plan_parser.py` has the exact semantics wanted, alongside
near-duplicates in `src/aet/cli/sprint.py` and `src/aet/cli/backlog.py`.
R-11 extracts one implementation rather than adding a fourth.

**Human observation needs no new flag.** With the log path printed at start (R-12), a human
follows a run with `tail -f`. This keeps the agent-facing surface at zero streaming
commands without removing human observability.

## Open Questions

- ~~**Should `aet run` (whole-queue batch) block like `aet run-one`?**~~ **Resolved:** no.
  `run-one` blocks (R-2); batch `run` returns immediately (R-2b) and is observed via
  `--follow` (R-2c). This is not a reintroduced mode choice: the distinction is carried by
  *which command the operator invoked*, reflecting intent (one plan vs. AFK queue), not by a
  flag an agent selects. See the determinism boundary in Technical Notes.
- **What stall-timeout value per adapter?** R-8 requires it to exceed a full suite's silent
  interval. The prior operational workaround used 1800s for this repo. Whether that is the
  default for both adapters, or differs between them, should be set from observed data
  rather than assumed.
- ~~**Where does night-shift AFK execution get its fire-and-forget path?**~~ **Resolved:**
  `aet work` is a skill, not a CLI command — there is no `src/aet/cli/work.py`, and
  `run`/`run-one` in `main.py` are the only spawners, so the night-shift agent invokes the
  same public command. Batch `aet run` never blocks (R-2b): it returns immediately after
  spawning, and the session observes the queue later via `--follow` (R-2c). AFK mode is
  unchanged.

## Divergence Summary

*Recorded: 2026-07-27 — Branch: rid-02-shared-plan-arg-resolver*

### Changed from plan

- **R-11b `sprint`/`backlog` `.md` path resolution**: The shared resolver's ship semantics are
  applied to `sprint` and `backlog`. A non-existent `.md` argument is returned unchanged instead
  of falling through to a `.md.md` lookup. This matches the scope-validation decision to adopt
  ship's semantics and is covered by `tests/queue/test_sprint_backlog_parity.py`.
- **R-9 `--max-jobs` on `aet run`**: Originally removed from both `run` and `run-one`,
  `--max-jobs` was restored as a caller-tunable option on `aet run` only (default `4`,
  maximum `8`). `aet run-one` continues to reject it. The dispatcher tests in
  `tests/cli/test_aet_dispatcher.py` and `tests/test_aet_run_dispatch.py` cover both the
  accepted `run --max-jobs` path and the rejected `run-one --max-jobs` path.

---

*Stage: synced*
*Next step: run `aet-ship`*
