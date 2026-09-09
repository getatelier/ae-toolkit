---
subject: session-log-extraction
---

# Session-Log Extraction Is a Per-Adapter Extension Point

## Status

Accepted (2026-07-26). Peer of ADR-031 (runtime observation vs enforcement); extends the
adapter model in `src/aet/cli_adapter.py`. Motivated by
`reports/2026-07-25-aet-performance-observability-review.md`; delivered by the
`telemetry-adapter-parity` PRD (`tap-03`, `tap-04`).

## Context

AET runs stage sessions through a pluggable agent CLI. `cli_adapter.ADAPTERS` already models the
differences that matter at *invocation* time — argv shape, headless flag, usage mode — and
`usage.parse_usage` already dispatches *parsing* on `agent_cli`, returning kimi's wire-file
totals or Claude's JSON envelope totals from one call site.

Session-log extraction never got the same treatment. `src/aet/wirelog.py` parses exactly one
schema: kimi's `~/.kimi-code/sessions/**/agents/*/wire.jsonl`, keyed on
`context.append_loop_event` records with `tool.call`/`tool.result` paired by `toolCallId` and
epoch-millisecond `time`. Worse, the caller hardcodes the same assumption —
`orchestrator.py:901-903` resolves a session directory only `if adapter.name == "kimi"`, and
`_emit_wire_test_runs` returns immediately when that is `None`. The result is not a degraded
signal on other CLIs; it is **zero observed `test_run` records by construction**. All three
Claude Code stage sessions in the archive confirm it.

The shapes genuinely differ and cannot be papered over with one parser: Claude's transcripts live
at `~/.claude/projects/<cwd-slug>/<sessionId>.jsonl`, carry `message.content[]` blocks of
`tool_use`/`tool_result` paired on `tool_use_id`, timestamp in ISO-8601, and signal failure with
a boolean `is_error` rather than an exit-code string. Some differences are advantages: every
Claude record carries `cwd` and `gitBranch`, so project mapping needs no `state.json` sidecar
lookup at all.

The failure mode this creates is the dangerous kind. Telemetry does not report that it saw
nothing; it reports nothing, and every downstream aggregate silently reads a Claude session as a
session with no tests.

## Decision

**Session-log extraction is a per-adapter capability, reached through one dispatched interface,
and an agent CLI is only fully supported once it supplies a reader.**

1. **One dispatch seam, mirroring `usage.parse_usage`.** Callers ask for test invocations by
   `agent_cli` and a session reference; they never name a schema, a path template, or a record
   type. The kimi reader moves behind the seam with byte-identical output for the same input.

2. **The session reference is adapter-resolved, not kimi-shaped.** The orchestrator stops
   computing a kimi session *directory* and instead asks the adapter to resolve whatever
   reference its reader needs. `session_dir` as a cross-adapter concept is retired.

3. **Readers may exploit their own schema's advantages.** The interface constrains the *output*
   (test invocations with command, start, end, exit status), not the route to it. Claude's reader
   uses `cwd` directly rather than reconstructing kimi's path-mapping detour.

4. **A missing reader is an explicit gap, not silence.** An adapter without a reader resolves to
   no session reference and emits no observed records — but that is a stated, testable property
   of the adapter, not an incidental consequence of a hardcoded name check. Adding a CLI to
   `ADAPTERS` without a reader is an incomplete integration.

5. **Extraction stays read-side and observational** (ADR-031). Readers parse logs the agent CLI
   already wrote. Nothing here changes what agents run, and no control path consumes the output.

## Consequences

- Test-run telemetry has the same fidelity on every supported CLI; switching agent CLI stops
  silently switching off half the archive.
- The cost of a third CLI is one reader plus one resolver, both testable against a captured
  fixture with no orchestrator changes.
- Two schema parsers now exist where there was one. That is the real cost, and it is unavoidable:
  the schemas are genuinely different, and the previous "one parser" only worked by not
  supporting the other CLI.
- Fixtures become the contract. Each reader is pinned to a captured session log, so an upstream
  CLI schema change surfaces as a failing replay rather than as a quiet drop to zero records.
- The seam is deliberately narrow — test invocations only. Broader harvesting (per-tool
  aggregates, turn and step counts) would reuse it, but is out of scope here and parked in
  `docs/ideas/cfg-01-session-efficiency.md`.

## Alternatives Considered

- **Keep one parser and normalise both schemas into it.** Rejected: the record shapes, pairing
  keys, time bases, and failure signals all differ; the "shared" parser would be a dispatch table
  wearing a trench coat, with both schemas' assumptions tangled in one function.
- **Generalise the matcher and leave the kimi gate in place.** Rejected: it fixes the smaller
  blind spot while hardening the larger one. Better detection on a CLI that resolves no session
  reference still yields zero records.
- **Have each adapter emit a normalised session log of its own during the run.** Rejected: it
  makes AET responsible for writing a second copy of data the CLI already persists, and it fails
  exactly when it matters most — a crashed session, where the CLI's own log survives and AET's
  would not.
- **Defer the Claude reader and land only the seam.** Rejected per the repo's clean-cut habit: an
  extension point with one implementation is speculative design, and the second reader is what
  proves the interface is actually general.
