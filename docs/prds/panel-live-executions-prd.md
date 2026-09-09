# PRD: Panel Live Executions

## Overview

The telemetry panel (`aet-work/panel/`) renders aet-work runs from the
`~/.aet/telemetry` archive, but a run only becomes visible once its first
stage completes and only ever shows as a finished success/failure row. While
a run is in flight — sometimes for an hour — the panel shows nothing, or
worse, mislabels a partial run as "success". Verified live on 2026-07-13:
run `b0cfc5a5` executed for 20+ minutes with an empty run dir and returned
zero entries from `/api/list`.

This PRD covers making in-flight executions first-class in the panel using
only data the archive already has (run dirs, file mtimes, partial JSONL
records). No orchestrator or telemetry-emission changes.

## Goals

- A just-started run (empty run dir, zero records) appears in the panel
  within seconds of the orchestrator creating the dir.
- Any run without `last-run.json` is labeled honestly: `live` when there is
  recent archive activity, `incomplete` when activity has gone stale —
  never a fake "success".
- The panel stays current without manual Refresh while in-flight runs exist.
- All of the above built against the existing archive format; the panel and
  `serve` ship together, so no API compatibility window is needed.

## Non-Goals

- Orchestrator/telemetry-emission changes: stage-start records or a
  `live.json` heartbeat ("tier 3") — separate follow-up. Consequence: the
  currently-executing _stage_ remains invisible; the panel shows completed
  stages only.
- Raw session-log tail (the deferred "Live session log" design in the panel
  README).
- Lease-file / PID cross-check (`.agents/work-queue.lease` lives in each
  project repo, outside the archive; archive-native mtime signals only).
- Live features in folder-picker fallback mode (no API → no dir listing;
  documented limitation, served mode only).
- SSE / WebSocket streaming; polling is sufficient at this scale.
- Prune/retention changes (`prune_archive` in `src/aet/telemetry.py` already protects fresh-mtime
  dirs).

## Requirements

- **R-1**: `GET /api/list` additionally returns `dirs`: every current-layout
  run dir (`{project}/{YYYY-MM-DD}/{run-id}`) with `rel` and `mtime`, where
  `mtime` is the newest recursive mtime (dir + contained files, mirroring
  `telemetry.py:_newest_mtime`) so JSONL appends count as activity. Empty
  run dirs are included. The existing `files` array is unchanged, and the
  path-traversal guard on `/api/file` is untouched.
- **R-2**: The panel renders runs that have no `last-run.json` — including
  zero-record dirs — with an honest status: `live` when the run's archive
  mtime is fresher than `LIVE_FRESHNESS_MINUTES` (30), `incomplete`
  otherwise. A no-summary run is never displayed as `success`/`failure`.
  Live runs sort to the top of the Runs table, then by last activity.
- **R-3**: In-progress state is visible where the user looks: a banner in
  run detail (record count + relative last-activity time, e.g. "In progress
  — 3 stage records, last activity 4m ago"; empty dirs get "Waiting for
  first stage record"), and a live marker on plan rows in the Plans lens
  when any contributing run is live.
- **R-4**: While the tab is visible and at least one no-summary run dir has
  activity younger than 60 minutes, the panel polls `/api/list` every ~5s
  and incrementally re-fetches only new or changed run dirs (dir `mtime`
  advanced). A run whose mtime advances between polls is `live` regardless
  of age. Manual **Refresh archive** remains a full reload.

## User Stories

- As the toolkit owner, I launch `aet run` and see a row for it in the
  panel on the next load or poll cycle — before any stage has completed —
  so I know the panel is watching the right run (satisfies: R-1, R-2, R-4).
- As the toolkit owner, I can tell a genuinely running execution apart from
  a crashed/abandoned one by its `live` vs `incomplete` badge and its
  last-activity time, instead of both looking like finished runs
  (satisfies: R-2, R-3).
- As the toolkit owner, I watch a plan's pipeline progress fill in during a
  live run and see which plan rows have active executions (satisfies: R-3).
- As the toolkit owner, I leave the panel open during a run and never press
  Refresh — new stage records appear on their own within seconds
  (satisfies: R-4).

## Technical Notes

- Data model (verified 2026-07-13): `RunLogger` (`src/aet/telemetry.py`) creates the run dir at
  launch, appends one JSON line per completed record to `{task-id}.jsonl`, and writes
  `last-run.json` only at run completion. Torn trailing lines are
  already skipped by both readers.
- The parser already accepts `summary == null` runs with records
  (`index.html`); what is missing is dir visibility, honest status,
  and freshness signals — this PRD adds exactly those.
- Dir mtime alone under-reports activity (appends bump file mtimes, not the
  dir's), hence the newest-recursive mtime in R-1 — same definition the
  prune safety check already relies on.
- Mid-stage quiet window: stage records write only at stage completion, so
  a healthy run can exceed the 30-minute freshness window mid-stage and
  flip to `incomplete`. Accepted for this PRD: the label says "last
  activity Xm ago", never "crashed"; R-4's poll-diff recovers liveness as
  soon as the next record lands; the tier-3 heartbeat closes the window.
- Implementation timing: a running aet-work orchestrator stashes
  uncommitted main-tree panel files at run start and pops them at finish
  (panel README quirk, observed 2026-07-11). Implement when no run holds
  `.agents/work-queue.lease`.

## Architecture Decisions

- **Additive API**: `dirs` alongside `files` in `/api/list`; folder-picker
  mode keeps working unchanged (it simply has no `dirs`).
- **Newest-recursive mtime as the single activity signal** — one definition,
  shared with prune safety; no lease/PID coupling.
- **Polling, not streaming**: `/api/list` is a cheap localhost directory
  walk (3,090 files at the 2026-07-11 peak, ~140 files today); incremental
  content fetches keep payloads tiny.
- **Two plans, one vertical slice each**: `lvp-01` = live runs visible on
  load (API + status model + rendering); `lvp-02` = panel stays current by
  itself (polling + poll-diff liveness). lvp-02 is useless without lvp-01;
  lvp-01 is valuable alone.

## Open Questions

- None blocking. `LIVE_FRESHNESS_MINUTES = 30` is a guess at the typical
  stage-group duration; it is a named constant, trivial to tune after a
  week of real use.

## Risks

- **Mid-stage false `incomplete`** (see Technical Notes) — mitigated by
  honest wording and R-4 recovery; closed later by tier 3.
- **Surfacing crash debris**: stale no-summary dirs (e.g. the crashed
  `bf58c30f` from 2026-07-11) will appear as `incomplete` rows. Intended —
  it makes crashed runs visible for the first time.
- **Stash-pop conflict** if implemented while an orchestrator run is active
  in this repo — mitigated by the lease check before implementation starts.

## Divergence Summary

_Recorded: 2026-07-13 — Branch: lvp-01-panel-live-run-visibility (plan lvp-01)_

### Changed from plan

- Task 6 (`scripts/test-panel-live-runs.mjs`): QA caught a teardown race —
  the harness now awaits Chrome exit (3s cap) before sweeping its profile
  dir and retries the directory removals; without it `rmdir` hit ENOTEMPTY
  on cache files Chrome was still flushing. Test-only; no panel behavior
  change.

### Added (unplanned)

- `docs/telemetry-guide.md`: the "Reviewing a single run" section gained a
  live-run behavior note during docs sync — anticipated by the plan's
  `docs_sync_reason` but not listed in the plan's task list, which scoped
  docs to the panel README only.

### Deferred

- Task 8 (merge to main) — deferred to the ship stage by design; lvp-02
  (R-4 polling) remains a separate plan.

_Recorded: 2026-07-13 — Branch: lvp-02-panel-auto-refresh (plan lvp-02)_

### Changed from plan (lvp-02)

- Task 1 (poll loop): chained `setTimeout` with an in-flight guard instead
  of a bare `setInterval` — same 5s cadence, but a slow tick on a large
  archive can never overlap with the next one.
- Task 3 (poll-diff liveness): the `bumped` flag is sticky for the page
  session — once a run's mtime advance marks it `live`, it stays `live`
  until reload even if no further records land (flag-for-human from
  aet-review; accepted — a rescued run should read as live). Minor ordering
  note from the same review: the dir snapshot advances before the
  changed-dir file fetch, so a record landing between the two is picked up
  on the next tick, not the current one (self-heals within one cadence).

### Deferred (lvp-02)

- Task 6 (merge to main) — deferred to the ship stage by design.

---

_Stage: synced_ (lvp-01 merged 2026-07-13; lvp-02 implemented, reviewed, and synced 2026-07-13 — pipeline: minimal, CSO deliberately skipped per plan frontmatter)
_Next step: run `aet-ship` for lvp-02_
