# PRD: Fable Review Hardening — State Safety, Evidence, and Dead-Weight Removal

## Overview

The 2026-07-09 Fable 5 review (`content/fable-review/01…05`) found that AET's markdown layer delivers its "deterministic process" thesis better than its Python layer: the queue has no locking and a non-atomic writer in `aet-state`, timed-out agent processes are orphaned, the documented `aet-work` interface doesn't exist as a binary, the telemetry guide promises records nothing emits, stage gates trust footer regex instead of evidence, and ~30% of the Python layer is dead or vestigial. This PRD implements the agreed upgrade selection from `content/fable-review/05-2026-07-09-upgrade-recommendations.md`: all of Phase 1 (items 1–5), the telemetry-emission half of item 6, item 7 (structured gate evidence), and item 9 (GitRefsBackend prototype).

The urgency is not theoretical: `.agents/learnings.jsonl` records a mid-batch crash **this morning** (2026-07-09T08:22Z) whose symptoms include queue drift — the exact lost-update class the review predicts.

## Intake Triage

Classified as **enhancement program**, not a reproducible-defect report: the concurrency and orphan issues are review-identified hardening of latent races (no isolated repro exists; today's crash learning had a since-fixed proximate cause), and the remaining items are new capability or deletion work. Documented per the aet-plan intake guard.

## Goals

- **G1 — State safety:** zero lost updates under concurrent writers; every queue write is atomic; every state mutation flows through one validated write path.
- **G2 — Process safety:** killing or timing out a task never leaves an orphaned agent process burning tokens.
- **G3 — Honest gates:** `make validate` exercises the Python that holds system state (pytest + ruff), not just markdown.
- **G4 — Interface truth:** the documented `aet-work <subcommand>` interface exists as a real dispatcher; the installer stops polluting PATH with bare names and prunes stale links.
- **G5 — One state vocabulary:** the legacy `status` field is retired; the dead layer (backend `transition`, archive helpers, `sync-footers`, vestigial retries, `estimate_repo_size`) is deleted; fods-06 is superseded.
- **G6 — Telemetry that exists:** every orchestrated run emits stage records; the telemetry guide documents only what is actually emitted.
- **G7 — Machine-checkable gates:** every gated stage produces a schema-validated JSON verdict; the orchestrator fails closed on missing/invalid evidence; footers become human breadcrumbs only.
- **G8 — Git-native state option:** a working, opt-in `GitRefsBackend` behind the existing backend interface, with an A/B findings report.

## Non-Goals

- Stage→skill bindings in `.agents/pipeline.json` (synthesis item 8 — deferred).
- MCP exposure of `aet-state` (item 10).
- Behavioral evals (item 11), review desk / zero-review merge class / planning UI (item 12).
- The bare-vs-AET ablation experiment (the other half of item 6).
- New CLI adapters, base-branch (`main`-only) configurability completion, or a `--on-failure` policy flag — flagged by the review but not selected.
- Making GitRefsBackend the default backend.
- Rewriting settled history: `work-history.jsonl` records keep their historical shape; readers stay tolerant.

## User Stories

- As the solo operator, I can leave a night-shift batch running and know a crash, timeout, or concurrent write cannot corrupt the queue or silently lose a stage record.
- As the solo operator, I can kill a run (or let it time out) and trust that no `claude`/`kimi` process survives to burn tokens or mutate a removed worktree.
- As a contributor, I run `make validate` and it fails if the Python is broken, not just the markdown.
- As a human following the README, `aet-work status` works exactly as documented, and installing AET does not shadow `sync(8)` or claim `add`/`status`/`next`.
- As a maintainer, every line of `lib/` and the binaries is load-bearing: grep for a function finds callers, not corpses.
- As the operator, the morning after a run I can open a per-stage JSON verdict (QA, review, CSO, verify) and see machine-validated evidence, not a footer string.
- As the operator, telemetry contains stage timing/outcome records for every run, so factory metrics become computable.
- As the toolkit author, I can flip one config value to run a project's task state on git refs and compare it against the JSON backend before committing to a migration.

## Story Map (tickets)

| ID     | Title                                                                                                                                                                     | Size | Blocked by     |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- | -------------- |
| frh-01 | Locked, atomic queue writes in the state layer (`queue_lock` helper, `aet-state` atomic + backend-routed writes) + concurrent-writer test                                 | M    | —              |
| frh-02 | Orchestrator queue mutations under lock; one validated failure path; `run_single` None-crash fix; `context-isolation.md` claim corrected                                  | M    | frh-01         |
| frh-03 | Process-group spawning + `killpg` on timeout/termination; orphan test                                                                                                     | S    | frh-02         |
| frh-04 | `make test` (pytest) + ruff wired into `make validate`; per-file ignores for files owned by the state chain                                                               | M    | —              |
| frh-05 | `aet-work` multicall dispatcher; `ship` → `aet-ship` rename; installer links only namespaced names and prunes stale/bare symlinks; docs updated                           | M    | —              |
| frh-06 | Status retirement (lib/read side): normalize-on-read, delete shim + `mark_*` + archive helpers; `status` binary speaks state                                              | M    | frh-01         |
| frh-07 | Status retirement (write side): `aet-state`/`init-queue` vocabulary, delete `sync-footers`/`archive`/unreachable branch; untrack `work-archive.json`; supersede fods-06   | M    | frh-06         |
| frh-08 | Delete dead layer: `TaskBackend.transition` (3 files), verifier retry loop, `estimate_repo_size`                                                                          | M    | frh-03, frh-07 |
| frh-09 | Deterministic stage telemetry per session; delete `loop_record`; telemetry guide corrected (incl. `symlink_dependencies` key fix); `mine-learnings` updated               | M    | frh-08         |
| frh-10 | Gate-evidence schemas + writer contract: `~/.aet/reports/{slug}/{task}/`, `lib/evidence.py`, skill instructions for qa/review/cso/sync-docs                               | M    | —              |
| frh-11 | Orchestrator gates consume evidence (fail closed); group advancement via evidence, not footer; `_divergences_found` off `/tmp`; `test_run_record` derived from QA verdict | M    | frh-09, frh-10 |
| frh-12 | `aet-retro` emits `learning_candidate_record`                                                                                                                             | S    | —              |
| frh-13 | `GitRefsBackend` core: opt-in git-native storage (task records as blobs under `refs/aet/tasks/*`)                                                                         | M    | frh-08         |
| frh-14 | GitRefs wiring (`factory`, `configure-task-backend`), backend-routed sealing, parity suite, A/B findings report in `docs/audits/`                                         | M    | frh-13         |
| frh-15 | Curated flow: `add` parks runnable state (`ready`/`blocked`) and builds edges; `sync` stops auto-adding; pipeline/plan skill texts updated                                | M    | frh-07         |
| frh-16 | Frontier promotes `planned` dependents; batch exits with report instead of silent spin; mid-run pickup test                                                               | S    | frh-11, frh-14 |
| frh-17 | Queue mutation guard: run lease refuses out-of-run writes; revision + content-hash stamps make out-of-band edits fail closed                                              | M    | frh-15, frh-16 |

Dependency rationale: one serialized chain (frh-01→02→03→…→08→09→11) covers every plan that edits `queue.py`, `orchestrator`, or `aet-state` — the scheduler has no conflict awareness, so `blocked_by` is doing that job; frh-06/07 join the chain where their files overlap it. frh-04, frh-05, frh-10, frh-12 are file-disjoint and can run in parallel with anything. (Story map refined at create-stories time from the approved 13-ticket sketch: the status retirement and dead-layer deletion split differently along file boundaries, and the GitRefs split became core + wiring/parity. frh-15/16 added 2026-07-09 evening per owner request: sprint-flow semantics — curation at `add`, automatic dependent promotion on verified merge, live mid-run pickup. frh-17 added 2026-07-10 per owner request after a mid-run out-of-band queue mutation: run lease + tamper-evident writes.)

## Acceptance Criteria

- [ ] A test spawning ≥4 concurrent writer processes against one queue file completes with zero lost updates, and every intermediate read parses as valid JSON.
- [ ] `aet-state`'s writes go through the tempfile+fsync+`os.replace` path; no plain `open(path, "w")` writer of the queue remains anywhere.
- [ ] No code path writes `task["state"]` outside the validated transition function (grep-verifiable).
- [ ] A test that times out a batch child verifies the grandchild process group is dead (no orphaned agent).
- [ ] `make validate` fails when a pytest test fails; fails when ruff reports an error.
- [ ] `aet-work status|add|next|sync|report|run|run-one` resolve via one dispatcher binary; a fresh install creates no bare-name symlinks in `~/.local/bin`; a re-install removes stale AET links (e.g., `ingest-telemetry`, `sync`, `add`).
- [ ] `state_to_status`/`status_to_state`/`mark_status`/`mark_completed`/`mark_awaiting_merge`/archive helpers have zero definitions and zero call sites; live queue records carry no `status` key; `fods-06` footer reads superseded with a pointer to its successor plan.
- [ ] `TaskBackend.transition`, `cmd_sync_footers`, `estimate_repo_size`, and the verifier retry loop are deleted with their tests updated.
- [ ] After any `aet-work run-one`, telemetry contains one `stage_record` per executed stage with duration and outcome; `docs/telemetry-guide.md` lists exactly the record types that have writers.
- [ ] Each gated stage of a `standard` pipeline run writes `{stage}.json` under `~/.aet/reports/{project-slug}/{task-id}/` (env-overridable), validating against a checked-in schema; a missing or schema-invalid verdict fails the gate with a clear error.
- [ ] The stage footer remains as a human breadcrumb; no gate decision reads it.
- [ ] With `backend: git-refs` configured, the `aet-state` test suite passes against the new backend; state survives access from a worktree; `docs/audits/` contains the A/B findings report.
- [ ] `make validate` passes repo-wide at the end of every ticket.

## Technical Notes

<!-- aet-lint: off -->
- **Verified anchors (2026-07-09):** non-atomic writer replaced by `save_queue` in `src/aet/queue.py`; process isolation handled by `_spawn_process_group` in `src/aet/cli/orchestrator.py`; zero call sites for `stage_record`, `loop_record`, `test_run_record`, `learning_candidate_record`; evidence directory configured in `src/aet/evidence.py`; status normalization in `src/aet/queue.py`; `TaskBackend` in `src/aet/backends/task_backend.py`; installer in `src/aet/cli/main.py`.
<!-- aet-lint: on -->
- **Locking:** `fcntl.flock` on a sidecar lockfile next to the queue (`.agents/work-queue.json.lock`), exposed as `queue_lock` context manager in `src/aet/queue.py`; every load→mutate→save cycle (aet-state commands, orchestrator batch loop, sync/init-queue) runs inside it. Keep stdlib-only.
- **Doc correction rider:** `skills/aet-work/references/context-isolation.md` claims "No lock file, no flock … is required" — false in batch mode (up to 8 children invoke `set-stage` concurrently). frh-01/02 must update this claim.
- **Process groups:** `start_new_session=True` on spawn; timeout path escalates SIGTERM→SIGKILL via `os.killpg` on the process group so the agent CLI grandchild dies with the child orchestrator.
- **Evidence home:** mirror telemetry's pattern — `~/.aet/reports/<project-slug>/<task-id>/<stage>.json` with `AET_REPORTS_DIR` override; project slug via the existing `derive_project_slug`. Verdict schemas are checked-in JSON Schema files; validation is stdlib (no jsonschema dep) — a small required-keys/type checker in `lib/`.
- **Telemetry decision (clarified with owner):** deterministic + derive. Orchestrator emits `stage_record`; `test_run_record` is derived from the QA verdict JSON (frh-10); `learning_candidate_record` is emitted by `aet-retro` (frh-11); `loop_record` is deleted as unknowable without session introspection.
- **fods-06 supersession (clarified with owner):** the queue is empty and the live/settled partition shipped, so the corpus migration fods-06 planned is moot; frh-06 supersedes it and the old plan gets a footer note. Settled history keeps legacy keys (append-only); readers stay tolerant.
- **GitRefsBackend (clarified with owner):** working opt-in backend, storage-only — state legality stays in `aet-state`; refs like `refs/aet/state/<task-id>` hold the task record (blob), history via git notes or an appended blob chain; local-only by default (no auto-push). Selected via the existing backend config (`configure-task-backend`). Blocked on frh-07 so it never implements the dead `transition` method.
- **Ruff:** already installed on the dev machine; runtime code stays stdlib-only — ruff is a dev-only tool invoked by `make validate` (with a graceful "not installed" message documented for other machines).
- **Ticket prefix:** `frh-`. Plans go to `docs/plans/frh-*.md`; queue entry via `aet-work sync` at pipeline Step 3.

## Open Questions

1. **Ruff rule set** — proposal: defaults (E, F) plus `I` (import sorting), no formatter this sprint. Widening later is cheap.
2. **Evidence retention** — proposal: no pruning this sprint; revisit when the review desk consumes evidence.
3. **frh-12 split line** — expected split: `frh-12a` backend core (refs read/write + notes history) and `frh-12b` config wiring + parity test suite. Confirmed at create-stories time against the dual-limit model.

## Divergence Summary

_Recorded: 2026-07-10 — Branch: frh-15-curated-flow-intake_

### Changed from plan (frh-15)

- **Implementation locus (tasks 1–5):** frh-15 scoped an 8-file curated-intake implementation, but the production semantics (`build_blocks` in `src/aet/queue.py`, `add` parking at `ready`/`blocked` and rebuilding edges, `plan_parser` recording the real initial state, `sync` no longer auto-adding, and the explicit `aet-work add` handoff in both skill texts) were already present on `origin/main` via the earlier commit `a85ab7b` ("curated sprint intake") before this branch was cut. The frh-15 branch therefore narrowed to **task 6 — the regression contract** (the five named behavior tests) plus plan-footer bookkeeping. Feature behavior matches the story map; only where the code lives differs (upstream commit, not the frh-15 branch). Task 7 (merge + verify) remains owned by `aet-ship`.

---

_Stage: scope-validated_
_Validated: 2026-07-09_
_Next step: run `aet-work` (single-plan or multi-task queue)_
