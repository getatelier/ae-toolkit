---
id: test-telemetry-fidelity
---

# PRD: Test Telemetry Fidelity & Structural Pattern Mining

## Overview

Orchestrated plan implementations routinely run 30–50 minutes per task, and the
toolkit cannot currently say why: the `test_run` telemetry that should record
test activity is synthetic (one record per QA gate, hardcoded `scope:
"full-suite"`, zero duration), and `mine-learnings` cannot detect full-suite or
repeated-test patterns because it keyword-matches narrative markdown reports
that no longer exist (0 reports scanned across 102 runs). Meanwhile the raw
data that answers "are we running global tests repeatedly?" already exists —
every kimi session's wire log (`~/.kimi-code/sessions/.../wire.jsonl`) records
each tool call with timestamps — and is discarded after token extraction. This
PRD instruments real per-invocation test telemetry from those wire logs, makes
verdict-derived records honest, and upgrades `mine-learnings`/`aet retro` to
structural pattern detection so the next round of workflow hardening is driven
by measurement instead of anecdote.

## Goals

- Every test invocation inside an orchestrated session produces a real
  `test_run` record (command, duration, classified scope) without any change
  to how agents run tests — passive extraction from existing wire logs.
- Verdict-derived `test_run` records stop fabricating `scope` and `duration`.
- `mine-learnings` detects full-suite share, repeated test invocations,
  slow stages, and token burn structurally from telemetry records.
- `aet retro` surfaces these patterns so `aet-evolve` can propose skill edits
  grounded in evidence.

## Non-Goals

- No change to agent behavior (what tests agents run, when, or how often) —
  this PRD is measurement only. Behavior changes are future telemetry-driven
  PRDs (as tdsh was).
- No claude-session tool-log parsing (claude reports usage via its stdout
  envelope; its per-tool logs are a separate format — future work if needed).
- No panel/UI visualization of test-run records.
- No external telemetry service; analysis remains local-first.
- No changes to the evidence-verdict contract (the ewl-01 evidence-path work
  is adjacent but separate).

## Requirements

- **R-1**: Each Bash tool call in a kimi session wire log whose command is a
  test invocation (pytest, vitest, make validate/test, or project-recognized
  test runner) yields one `test_run` telemetry record with the real command,
  start/end timestamps from paired `tool.call`/`tool.result` wire events, and
  a computed duration.
- **R-2**: Every `test_run` record carries a `scope` classified from its
  command (`full-suite`, `impact`, or `unknown`) by a single shared heuristic
  — no hardcoded scope values at any emission site.
- **R-3**: Unmeasured fields stay `null` (schema null contract); no zeros or
  estimates are written where no measurement exists.
- **R-4**: `mine-learnings` counts full-suite vs impact runs and repeated test
  invocations per task structurally from `test_run` records, replacing the
  dead narrative-markdown keyword scan for those categories.
- **R-5**: `mine-learnings` flags `slow_stage` (stage session duration over a
  named threshold) and `token_burn` (session token count over a named
  threshold) from `stage` records, with thresholds as tunable constants.
- **R-6**: `aet retro` output includes the new structural pattern counts in
  its Telemetry Summary and `--propose` suggestions reference them.

## User Stories

- As the toolkit owner, I want each agent session's test invocations recorded
  with real scope and duration so that I can see whether a 45-minute implement
  session ran the full suite five times or twice. (satisfies: R-1, R-2, R-3)
- As the toolkit owner, I want verdict-derived records to stop reporting
  `full-suite`/`0s` for everything so that scope statistics are trustworthy.
  (satisfies: R-2, R-3)
- As an aet-evolve user, I want `mine-learnings` to rank full-suite share,
  repeated invocations, slow stages, and token burn from structured records so
  that pattern detection works even with zero narrative reports. (satisfies:
  R-4, R-5)
- As an aet-evolve user, I want `aet retro` to surface those patterns and
  propose skill edits from them so that the next tdsh-style hardening round is
  evidence-driven. (satisfies: R-6)

## Acceptance Criteria

- [ ] A real orchestrated kimi session emits one `test_run` record per test
      invocation with non-zero duration and classified scope. (satisfies: R-1)
- [ ] `classify_test_scope` is defined once and used at both emission sites
      (wire extraction and verdict gate); no `scope="full-suite"` literal
      remains in the orchestrator. (satisfies: R-2)
- [ ] Records with no measurable duration write `duration_seconds: null`, and
      the schema doc documents the null contract for wire-derived and
      verdict-derived records. (satisfies: R-3)
- [ ] `aet mine-learnings` on the real archive reports nonzero structural
      counts for full-suite runs once sessions with wire-derived records
      exist, and reports `slow_stage` / `token_burn` counts from existing
      stage records immediately. (satisfies: R-4, R-5)
- [ ] `aet retro` renders the new pattern counts and
      `mine-learnings --propose` maps them to skill-edit suggestions.
      (satisfies: R-6)
- [ ] `make validate` passes; a new ADR records the decision to treat agent
      wire logs as a telemetry source.

## Technical Notes

- Wire format (verified 2026-07-13 against kimi 0.23.x sessions): each line is
  a JSON object with top-level `type`, `time`, and `event`. Test invocations
  appear as `context.append_loop_event` envelopes whose `event` has
  `type: "tool.call"`, `name: "Bash"`, `args.command`, and `uuid`; the paired
  `tool.result` event carries `parentUuid` / `toolCallId` linking back.
  Duration = `time(result) − time(call)`. `usage.py:_sum_wire_usage` already
  resolves session dirs via `session_index.jsonl` — reuse
  `_resolve_kimi_session_dir`, do not re-implement.
- The wire schema is an internal recovery stream, not a public contract
  (`usage.py` already documents this) — extraction must be defensive: missing
  pairs, malformed lines, and absent `time` yield `null` fields, never
  crashes, never estimates.
- Scope heuristic (shared): command names specific test files/dirs →
  `impact`; bare suite runners (`pytest tests/`, `make validate`,
  `make test`, `vitest run` without paths) → `full-suite`; unrecognized
  test-ish commands → `unknown`. Kept deliberately simple — this repo's own
  commands (`python3 -m pytest tests/ -q`, `make validate`) must classify as
  `full-suite`, and `pytest tests/test_panel_serve.py` as `impact`.
- Verdict-derived records (`_emit_test_run_from_verdict` in
  `src/aet/cli/orchestrator.py`) have a single timestamp (verdict
  `generated_at`): duration is unmeasurable there and must become `null`,
  which requires `test_run_record` to accept null start/end.
- `mine-learnings` currently scans `*.md` under telemetry run dirs; verdicts
  live as JSON under `~/.aet/reports/{slug}/{task}/{kind}.json`. The narrative
  scan has produced zero signal since reports moved to JSON — retire it for
  the covered categories rather than re-pointing it (structural detection is
  strictly better and the keyword lists are already stale: "488-test").
- Slow/token thresholds proposed: `slow_stage` > 1800s, `token_burn` >
  5,000,000 tokens (this repo's implement sessions average ~50 min / 7–15M
  tokens, so both will fire — tune after one week of data).

## Open Questions

- Should `tool.call` extraction cover MCP-wrapped bash (e.g. server-prefixed
  tool names) or only `name == "Bash"`? (Default: Bash only in v1; note others
  as `unknown`-eligible later.)
- Is `impact` vs `full-suite` enough, or do we want `lint`/`format` as
  separate scopes for `make validate`-style commands? (Default: keep the three
  scopes; validate-style commands count as full-suite.)

## Relation to Other Documents

- `docs/adr/015-telemetry-driven-skill-improvements.md` — established
  telemetry mining as a first-class input; this PRD fixes the instrumentation
  that mining depends on.
- `docs/prds/telemetry-driven-skill-hardening-prd.md` (tdsh) — the previous
  mining-driven hardening round; its impact-scoped-test rule is exactly what
  this PRD makes verifiable.
- `docs/plans/tele-07-retro-reader-layout-fix.md` — fixed reader/writer layout
  drift; this PRD assumes that reader contract.
- `docs/adr/023-one-canonical-verdict-path.md` — verdict path canon; adjacent,
  untouched here.

---

_Intake triage: feature/enhancement (new measurement capability). Contains one
defect repair — the hardcoded `scope`/`0s` in verdict-derived records — folded
into ttf-02 rather than a separate bug plan, mirroring the tdsh precedent._

_Stage: synced_
_Next step: run `aet-ship`_
