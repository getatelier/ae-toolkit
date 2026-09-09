# PRD: Telemetry Hygiene & Plan-centric Panel

## Overview

The 2026-07-11 panel investigation (`aet-work/panel/README.md`, aet-panel worktree) surfaced four gaps in the telemetry pipeline: the pytest suite pollutes the real archive with junk projects, project identity is derived from the git origin remote so the owner doesn't recognize their own repos, retention is a hand-run shell snippet that once deleted a live run's directory, and the panel is run-centric when the unit of intent is the plan. This PRD turns the four decided designs from that README into implementable plans.

## Goals

- Zero telemetry records written to the real archive by the test suite.
- Project identity the owner recognizes: `<main-worktree-dir>/<worktree-dir>` (e.g. `aiskills/main`), with existing history migrated.
- Retention as a safe, dry-run-first CLI that can never delete a live run.
- Panel default lens = Plans: per-plan lifecycle consolidated across all runs; Runs demoted to a debugging tab.

## Non-Goals

- Session-log capture / live tail (feasibility study deferred — see panel README "Live session log").
- Stable plan identity across file renames (plan identity = normalized path; a rename splits history — accepted v1 limitation).
- Cross-machine or rename-surviving project identity (the panel is a local, single-machine tool — decided).
- Backfilling June-era archives removed by the 2026-07-11 cleanup (unrecoverable).
- Orchestrator/telemetry-emission changes for the panel work (the plan-centric view is buildable from existing records — verified).
- Submodule checkouts in slug derivation (`--git-common-dir` under `.git/modules` — out of scope).
- Backward compatibility shims: the old origin-derived slug and the manual-retention doc snippet are replaced outright, not kept alongside (project rule: no compat windows).
- Retention/pruning of the gate-evidence reports tree (`~/.aet/reports`) — R-4 covers the telemetry archive only; evidence verdicts are consumed fail-closed per task and have their own lifecycle.

## Requirements

- **R-1**: Running the full pytest suite (`python3 -m pytest tests/`) writes no records into the real user archive — every orchestrator spawn from tests resolves `AET_TELEMETRY_ARCHIVE_DIR` to a pytest temp directory unless a test explicitly overrides it. Verifiable by snapshotting `~/.aet/telemetry` before/after a suite run: identical.
- **R-2**: `derive_project_slug()` returns `<main-worktree-dirname>/<current-worktree-dirname>`, labelling the primary worktree `main` (this repo → `aiskills/main`; its aet-panel worktree → `aiskills/aet-panel`). `AET_PROJECT_ID` / `AET_REPO_SLUG` env overrides still win; a non-git directory still falls back to its bare directory name.
- **R-3**: A migration helper renames existing archive project directories to the new scheme (dry-run by default, `--apply` to execute, idempotent, refuses to clobber an existing run dir). After migrating, `aet-work report` and the panel list `aiskills/main` (and `artifactsh/main`) where `thebrightnest/*` used to appear.
- **R-4**: `aet-work report --prune DAYS` prints deletion candidates without deleting; with `--force` it deletes run directories older than DAYS plus stale empty leftover directories. It never deletes the run directory of the leased active run, nor any directory with a fresh mtime (protects live runs of other projects and the empty-dir-at-run-start case that killed the wfd-03 run). The telemetry guide's "retention is manual" bullet is replaced by the CLI.
- **R-5**: The panel opens on a **Plans** lens: one row per plan (normalized `plan_file` → `docs/plans/<plan>.md`) per project, including runs attributable only through `run_summary.task_ids` (task→plan join). The existing Runs view remains fully functional as a second tab.
- **R-6**: Plan detail shows the six-state workflow spine (`plan-approved → implemented → qa-complete → reviewed → secure → synced`) with per-state completion, a chronological cross-run timeline of stage sessions and test runs (run id, worktree, duration, result — retries appear as repeated rows), aggregated environment issues and learning candidates, and run chips that jump to that run in the Runs lens.

## User Stories

- As a toolkit developer, I run the test suite without `tests`, `demo/project`, `tmp*`, `T/tmp*` junk projects reappearing in my archive (satisfies: R-1).
- As the toolkit owner, I see my repo as `aiskills/main` and per-worktree launches as `aiskills/<worktree>`, so the panel's project list matches how I think about my machine (satisfies: R-2).
- As the toolkit owner, my pre-migration run history stays findable under the new project names (satisfies: R-3).
- As the toolkit owner, I prune old telemetry with one command that is safe by default, instead of a shell snippet that once deleted a live run (satisfies: R-4).
- As the toolkit owner, I open the panel and see plans with their pipeline progress, not a pile of orchestrator invocations (satisfies: R-5).
- As the toolkit owner, I drill into one plan and see its full lifecycle — every stage session, retry, and test run across all runs that touched it (satisfies: R-6).

## Acceptance Criteria

- [ ] A directory listing of `~/.aet/telemetry` taken before and after a full suite run is byte-identical (satisfies: R-1)
- [ ] `derive_project_slug()` from this repo returns `aiskills/main`; from `.worktrees/aet-panel` returns `aiskills/aet-panel`; with `AET_PROJECT_ID=x/y` returns `x/y`; from a non-git temp dir returns the dir name (satisfies: R-2)
- [ ] After running the migration helper with `--apply`, the panel folder filter lists `aiskills` (not `thebrightnest`) and historical runs open normally (satisfies: R-3)
- [ ] `aet-work report --prune 7` deletes nothing and lists candidates with total size; adding `--force` removes them; a run dir named in `.agents/work-queue.lease` and a fresh-mtime run dir both survive a forced prune (satisfies: R-4)
- [ ] Opening the panel shows the Plans lens by default with ≥ 1 plan row for this repo's archive; switching to the Runs tab reproduces today's table and detail unchanged (satisfies: R-5)
- [ ] Selecting the wfd-01 plan (known to span multiple runs on 2026-07-06 → 2026-07-11) shows completed spine states, a timeline with rows from more than one run id, and a run chip that navigates to that run's detail (satisfies: R-6)

## Technical Notes

Verified ground truth (2026-07-11, main tree unless noted):

- `src/aet/telemetry.py` — `archive_dir` honors `AET_TELEMETRY_ARCHIVE_DIR`; `resolve_repo_root` honors `AET_REPO_ROOT` before asking git; `derive_project_slug` is origin-remote-based today; `_sanitize` rewrites repo root/home to `{REPO_ROOT}`/`{HOME}`; `RunLogger` writes `{archive}/{slug}/{date}/{run-id}/{task}.jsonl` + `last-run.json`.
- The orchestrator pins `AET_REPO_ROOT` and `AET_RUN_ID` into every child env, so run identity is the launch root and children share the parent's lease — a run's sessions cannot scatter across per-task worktree slugs (`src/aet/cli/orchestrator.py`).
- Lease: `.agents/work-queue.lease` JSON sidecar; `read_lease` in `src/aet/queue.py`. Gitignored, absent when no run is live.
- Tests: `tests/conftest.py` is only a `sys.path` insert — the isolation fixture is greenfield. Explicit `AET_TELEMETRY_ARCHIVE_DIR` settings exist across `tests/test_orchestrator.py`, `tests/test_aet_retro_telemetry.py`, and `tests/test_telemetry_archive.py` (direct `os.environ` set/pop in setUp/tearDown) and must keep working.
- Panel: single self-contained `panel/index.html` (718 lines, React 18 UMD + Babel standalone + Tailwind Play, no build step); run model in `buildRunsFromGroups`/`buildRun`; folder/project grouping memos. `serve` (89 lines) exposes `GET /api/list` + `GET /api/file?p=` — no server change needed for R-5/R-6.
- Records: `stage`, `test_run`, `environment_issue`, `learning_candidate` all carry `plan_file` (sanitized, typically `{REPO_ROOT}/.worktrees/<task>/docs/plans/<plan>.md` — normalize by slicing from `docs/plans/`); `run_summary` carries `task_ids` only → join through a global task→plan map (verified 1:1 in current data). Worktree column = parsed from the raw `plan_file` prefix (`.worktrees/<name>/` else `main`).
- Workflow spine from `.agents/workflows/software.json`: `plan-approved, implemented, qa-complete, reviewed, secure, synced`; `done_state: done`. Stage records carry these names in `stage`/`stages`.
- **Slug consumers beyond the archive** (validation finding 2026-07-11): gate evidence lives at `{reports}/{project-slug}/{task-id}/` and `src/aet/evidence.py` calls `telemetry.derive_project_slug()` (orchestrator passes it explicitly in `src/aet/cli/orchestrator.py`). The R-2 identity change therefore applies to the reports tree automatically (shared function — consistent, no evidence-code change), and R-3's migration renames project dirs under **both** `~/.aet/telemetry` and `~/.aet/reports` so pre-migration verdicts stay findable.
- **Command-surface interaction**: the queued cli-01..05 arc renames `aet-work report` → `aet report` and deletes the old dispatcher. R-4's mechanism lives in `src/aet/cli/report.py` + `src/aet/telemetry.py` and survives either way; docs written by thp-04 must match the command surface present at implementation time.
- Same-file serialization: thp-03/thp-04 are `blocked_by` thp-02 (all touch `telemetry.py` and/or the guide); thp-06 is `blocked_by` thp-05 (same `index.html`). thp-01 is independent and should merge first to stop ongoing pollution.

### Prerequisite P-0 — land panel v1 on origin/main

Panel v1 (`aet-work/panel/{index.html,serve,README.md}` + the guide's interim retention edits) exists only as **uncommitted files** in `.worktrees/aet-panel` — the branch has zero unique commits. aet-work task worktrees are cut from `origin/main`, so thp-05/thp-06 cannot run until panel v1 is committed, merged to main, and pushed. This is a manual git action (owner's uncommitted work — not an aet-work task, since a fresh task worktree wouldn't contain the files), executed at the PRD gate. thp-05/thp-06 must not be queued before P-0 is done.

## Intake Triage

Feature/enhancement pipeline confirmed for R-2…R-6. R-1 is defect-shaped (tests observably pollute the real archive), but the investigation is already complete — root cause and fix are diagnosed in the panel README (only 4 of ~160 orchestrator spawns set the archive env var) — so it is planned here as a hardening task per owner direction instead of a separate `aet-bug-report` cycle.

## Open Questions

None blocking. P-0 execution timing (land panel v1) is decided at the PRD approval gate.

## Risks

- Pollution continues until thp-01 merges (~160 junk spawns per suite run) — mitigation: thp-01 has no blockers; run it first.
- Migration touches the live `~/.aet` archive — mitigation: dry-run default, idempotent, collision-refusing; executed manually by the owner.
- Plan identity is the normalized path — a plan renumber (see learning 2026-07-11 on renumbering) splits panel history. Accepted for v1.
- Parallel worktree merges on shared files — mitigated by the `blocked_by` chains above.

## Divergence Summary

_Recorded: 2026-07-11 — Branch: thp-01-test-telemetry-isolation (scope: thp-01 / R-1 only; R-2…R-6 remain planned)_

### Changed from plan

- Task 1 (isolation fixture): the autouse fixture also patches `telemetry.DEFAULT_ARCHIVE_DIR`, not just the env var — several orchestrator tests run in-process under `patch.dict(os.environ, ..., clear=True)`, which wipes `AET_TELEMETRY_ARCHIVE_DIR`; without the module-level patch those calls fell back to the real archive. Found during QA.
- Task 2 (guard tests): three tests shipped instead of the planned two — `test_runlogger_stays_isolated_when_env_is_cleared` was added to prove the clear=True escape is closed.

### Added (unplanned)

- None beyond the two changes above (both in-scope hardening of the same R-1 mechanism).

### Deferred

- Task 4 (merge to main): deferred to `aet-ship` per the standard pipeline — no code change.

_Recorded: 2026-07-11 — Branch: thp-04-retention-prune-cli (scope: thp-04 / R-4 only)_

### Changed from plan (thp-04)

- None — `prune_archive()`, the `--prune`/`--force` CLI wiring, the guide rewrite, and the five named tests plus CLI smoke test all landed as the Locked design specified.

### Added (unplanned, thp-04)

- CSO-stage hardening (aet-cso F1/F2): `prune_archive()` now rejects a `root` that resolves outside the telemetry archive (`ValueError`), and symlinked dirs are skipped during run-dir iteration so they can never become `rmtree` targets. Two regression tests added (`test_prune_root_outside_archive_rejected`, `test_prune_skips_symlinked_run_dirs`), plus a root-scope narrowing test. Reason: the plan's own security review note required verified archive-root containment.

### Deferred (thp-04)

- Task 5 (merge to main): deferred to `aet-ship` per the standard pipeline — no code change.

_Recorded: 2026-07-11 — Branch: thp-04-retention-prune-cli (scope: thp-04 / R-4 only — second aet-cso pass)_

### Added (unplanned, thp-04 — cso re-run)

- Second-pass CSO hardening (aet-cso F1/F2, re-run): the whole-archive prune walk (`_iter_run_dirs`) now skips symlinked **project** dirs — previously `is_dir()` followed a symlink planted at `~/.aet/telemetry/<link>` and made dirs in the link target `rmtree` candidates, escaping archive containment (High, the class the plan's security review gates on). `prune_archive()` also raises `ValueError` for negative `days`, which would place the cutoff in the future and mark every run as a candidate (Low). Two regression tests added (`test_prune_skips_symlinked_project_dirs`, `test_prune_negative_days_rejected`).

---

_Stage: scope-validated_ (owner gate + closure check 2026-07-11)
_Next step: run `aet-work` (single-plan or multi-task queue)_
