# PRD: The Board Is Open Work — Delete Settled-ness, Stop Committing Task State

## Overview

AET keeps progress-management state in the repository, and the symptoms are measurable: **129 of 1,717 commits (7% of history) record nothing but a card moving across a board**; 53 live plan files are still tracked despite `.gitignore` declaring them transient, so the pollution continues; and five ADRs (011 → 013 → 034 → 054 → 055) have each *relocated* the question "is it done?" without ever removing it, the last one unbuilt.

The reframe: **a plan is a task card — progress-management information, not documentation.** The durable record of intent is the PRD, which is project documentation and stays committed. The durable record of outcome is the commit history. Everything between is transient.

The deeper insight is that settled-ness only needs deriving because `init-queue` and `queue sync` re-enumerate the board from `docs/plans/*.md` — an append-only directory that never forgets. **Stop re-deriving the board from the plans directory and "is it done?" stops being a question**: the board is the set of open work, and finished work is simply not in it. ADR-013 already defines the board that way; nothing implements it that way.

This is not a migration to GitHub. Storage stays local in git-refs, which already pushes and fetches `refs/aet/*` and therefore already travels between machines. GitHub Issues stays a **projection** plus a human-owned intent label — ADR-032's fence that no forge is a source of truth remains intact. And a **shadow posture**makes AET usable in repositories that must carry no trace of it.

## Goals

- No commit whose only content is a task-state change.
- Settled-ness deleted as a question, not relocated to a better store.
- One task store, so backend-specific defects stop being possible.
- A backlog visible on GitHub and a sprint composable by hand, without the forge becoming the source of truth.
- AET usable on a repository that must contain no AET artifact at all.
- One PR per PRD.
- Plan on one machine, run on another, with nothing but the repo and its refs.

## Non-Goals

- **Multi-user.** Deferred, and the board contract carries **no** `claim` operation — an unused hook is cost without benefit, and adding it when multi-user arrives is cheaper than carrying it unused. Nothing coordinates across users.
- **GitHub as a task store.** git-refs already travels; a forge store would buy only multi-user, which is deferred. ADR-032's source-of-truth fence stands. Its decision 2 does need a narrow amendment, though — see R-18.
- **A ledger reader or ledger transport.** `.agents/ledger.jsonl` has five writers and zero readers. It stays a local, unread provenance log. Its *four* false documentation claims are corrected (R-18); wiring it is a separate decision.
- **The 2026-08-11 "settled tasks disappeared" incident.** Its recorded mechanism is impossible and it has no reproduction — `aet-bug-report`. Deleting the settled-ness derivation removes most of its blast radius.
- **Offline operation.** Retracted as a constraint: `aet run` spawns an agent against a remote model API and has never worked offline.
- **Verdict portability across machines.** `~/.aet/reports` is machine-local by ADR-055 decision 4, and verdicts are read only by the pre-push hook and the integration gate — both on the machine that did the work.
- **Untracking the 264 legacy files in** `docs/plans/archive/`**.** A visible 264-file diff and the operator's call. They become inert.
- **Metrics and retro rework**, beyond keeping their archive input working.

## Requirements

### Phase 1 — Stop the bleeding (no dependencies; ships alone)

- **R-1**: Every file the toolkit writes under `.agents/` is registered in exactly one hygiene declaration, and a test fails when a writer is added without registering its file.
- **R-2**: "Do not track this" and "tolerate this dirty" are separate declarations with separate consumers, so a tracked-but-tool-written file such as `.agents/learnings.jsonl` can be tolerated without being gitignored.
- **R-3**: A hygiene halt names the paths that caused it.

### Phase 2 — Plans stop being documents

- **R-4**: No AET command produces a commit whose content is a plan-state change, and the 53 live plan files still tracked in git are untracked so `.gitignore`'s declaration actually holds.
- **R-5**: A settled plan is archived to a machine-local location outside the scanned plans directory (`~/.aet/<slug>/plans/archive/`), and `aet metrics` reads settled-task metadata from **that location only** — no dual-read of the legacy `docs/plans/archive/`. Migration performs a one-time copy of the 264 legacy files so historical metrics survive without a second read path.
- **R-6**: Plan-consuming tooling — `aet plan validate`, `plans lint`, the R-trace coverage lint, and ADR-046 delivered-size measurement — operates on live plans only, and does not degrade as settled work accumulates. `aet gate review` is **kept as the shadow-mode board**, and is therefore re-pointed at the board itself rather than at a directory glob: after R-19 a shadow project has task records but need not have any plan file to scan.
- **R-19**: The task record carries the task's spec — its task list and its gate keys (`security_review`, `docs_sync`, `pipeline`, `size`) — rather than a path to a file. The working plan in a worktree is rendered from the record. A task planned on one machine is therefore executable on another with no artifact outside `refs/aet/*`, and `_copy_deferred_files`' main-checkout overlay is removed rather than guarded.

### Phase 3 — The board is open work

- **R-7**: The board is enumerated as the set of open work. No command re-derives it by scanning the plans directory.
- **R-8**: `init-queue`, `_is_settled_from_authority`, and work-history-as-authority are deleted. `.agents/work-history.jsonl` remains a measurement log only.
- **R-9**: `ready` is computed from `blocked_by` plus what has left the board. `blocked_by` is declared intent and may be hand-edited; readiness may never be asserted.
- **R-10**: A dependent becomes ready when its blocker leaves the board, without consulting a settled-history store.

### Phase 4 — One store

- **R-11**: git-refs is the only task store. The json backend and the `task_backend` selection axis are removed, and the documentation that presents json as the non-git-context option is corrected.
- **R-12**: The provenance ledger is written through one exported derivation. The four current derivations — which resolve differently by launch mode, backend and working directory — collapse to one.

### Phase 5 — GitHub as intent, not as truth

- **R-13**: `aet:sprint` is human-owned intent. AET reads the label, validates each candidate against the dependency graph, and admits it or refuses with the blocking reason named.
- **R-14**: A projection or intent-read failure retries with backoff and then halts. It never fails open — "could not reach GitHub" must never read as "nothing is blocking".

### Phase 6 — Shadow posture

- **R-15**: Shadow posture is a first-class, permanent mode: configuration lives only at user scope, no projection runs, and no AET artifact appears in the working tree. It is **inferred** from the absence of project-scope config, and every run announces the inference and its consequence — that `refs/aet/*` will not be pushed — naming the command that opts out.
- **R-16**: In shadow posture `refs/aet/*` is never pushed, including at closure, and ADR-055's mandatory-closure-push carries an explicit exemption rather than being silently bypassed.

### Phase 7 — One PR per PRD

- **R-17**: The integration branch is derived from the PRD a task belongs to, rather than from a single static config value, so concurrent PRDs each carry their own branch and PR.

### Cross-cutting — configuration honesty

- **R-20**: A configuration value that cannot take effect is an error, not a silent no-op. Resolution rejects unknown and misspelled keys, refuses combinations that contradict each other, names the layer each effective value came from (ADR-048), and states the legal alternatives. A removed key — such as `task_backend` after R-11 — fails with a migration message rather than being ignored. An *inferred* value that changes durability behaviour — shadow posture under R-15 — is announced, never assumed silently.
- **R-23**: `aet configure` offers an explicit, named way to declare a project shared across devices, and the documentation states the default plainly: a project nobody configured is local. Opting in is one command, not a matter of knowing that creating project-scope config happens to change push behaviour.

### Documentation truth

- **R-18**: Documentation and ADRs describe the shipped model. The **five** sites asserting ledger refs transport are corrected — `docs/CONVENTIONS.md`, `docs/WORKFLOW-github.md`, `src/aet/backends/git_refs_backend.py`, `src/aet/cli/sync.py`, and **CONTEXT.md's own glossary** — ADR-054's stale plan-`status` clause is retired, and one ADR records the open-work board contract and the shadow posture, amending ADR-011, ADR-013, ADR-045 and ADR-055.
- **R-21**: ADR-032 decision 2 is amended. It currently states a projection "never writes back into AET state and **is never read by AET commands**", which R-13 contradicts by design. The amendment narrows it: a forge is never read for *state*, and reading human-declared *intent* is a distinct, permitted operation. The source-of-truth fence is unchanged.
- **R-22**: ADR-033 gains a third failure category. It classifies projection *writes* as fail-open and storage as fail-closed; a forge *read that gates admission* is neither, and R-14 makes it fail-closed. The ADR must name the category rather than leaving R-14 looking like a violation of it.

## User Stories

- As a maintainer, I want a commit history containing code and intent, not card movements (satisfies: R-4).
- As a maintainer, I want "is it done?" to stop being a question the system has to answer (satisfies: R-7, R-8).
- As an operator, I want to compose a sprint by adding a label in the GitHub UI, and be told when a choice is illegal rather than silently accepted (satisfies: R-13, R-9).
- As an operator on a client project, I want to run AET without a single AET artifact reaching their repository (satisfies: R-15, R-16).
- As an operator with two machines, I want to plan a PRD and its tasks on one and run the queue on the other, with no artifact hand-carried between them (satisfies: R-19, R-7 — git-refs already pushes and fetches). One machine runs the queue at a time, so no concurrency protection is required.
- As a reviewer, I want one PR per PRD, not one per task (satisfies: R-17).
- As an operator adopting AET in a new project, I want a repo that does not halt on the toolkit's own writes (satisfies: R-1, R-2).
- As an operator configuring AET, I want a typo or a contradictory combination to fail with a named reason, rather than a setting that silently does nothing (satisfies: R-20).

## Acceptance Criteria

- [ ] A test enumerates the toolkit's `.agents/` writers and fails on an unregistered one (satisfies: R-1)

- [ ] Appending a learning leaves the tree clean while the file stays tracked (satisfies: R-2)

- [ ] A dirty-tree halt prints the offending paths (satisfies: R-3)

- [ ] A task run start-to-finish adds no commit matching `mark plan stage`, and `git ls-files docs/plans | grep -v archive` is empty (satisfies: R-4)

- [ ] `aet metrics` reports the same per-class figures before and after the archive relocation (satisfies: R-5)

- [ ] A task planned and added on machine A runs to completion on machine B after a fetch, with no plan file present in A's working tree at any point, and with gate skips and pipeline mode resolved identically on both (satisfies: R-19)

- [ ] Plan tooling runtime and output are unchanged after 50 simulated closures (satisfies: R-6)

- [ ] No code path enumerates the board by globbing the plans directory (satisfies: R-7)

- [ ] `grep -rn "_is_settled_from_authority\|init_queue" src/` returns nothing (satisfies: R-8)

- [ ] Hand-adding a readiness-shaped label does not make a blocked task runnable (satisfies: R-9)

- [ ] A dependent becomes ready after its blocker closes, with the history log absent (satisfies: R-10)

- [ ] `grep -rn "work-queue.json\|task_backend" src/` returns nothing (satisfies: R-11)

- [ ] Every ledger writer resolves the same store from inside a worktree, under `aet run` and `aet run-one` (satisfies: R-12)

- [ ] `aet:sprint` on a task whose blocker is open is refused with the blocker named (satisfies: R-13)

- [ ] A simulated 403 or rate-limit during an intent read halts the run and admits nothing (satisfies: R-14)

- [ ] A full run in shadow posture leaves `git status` clean, no `refs/aet/*` on the remote, and no project-scope config file (satisfies: R-15, R-16)

- [x] Two PRDs in flight produce two integration branches and two PRs, with no per-task branch on `origin` (satisfies: R-17)

- [ ] A misspelled config key fails with the legal keys named; a `task_backend`key left behind after R-11 fails with a migration message; shadow posture combined with a `projections` entry or a project-scope config file fails with the contradiction stated; `aet setup verify` reports the layer each effective value came from (satisfies: R-20)

- [ ] No document claims refs transport for the ledger, plan `status` as a liveness signal, or json as a supported backend (satisfies: R-18)

## Technical Notes

**Measured baseline.** 1,717 commits; 109 match `mark plan stage`, 20 match `Seed plan` — 7%, undercounted because `docs(...): mark <id> qa-complete` variants match neither pattern. `.gitignore` ignores `docs/plans/*.md`, but gitignore never untracks: **53 live plans were already tracked and still mutate and commit**. That is why the decision to make plans transient has had no effect, and it is R-4's missing half. 317 files are tracked under `docs/plans/`, 264 of them in `archive/`.

**The board already travels.** `git_refs_backend` implements `push()` and it is called on every state write and mandatorily at closure; `fetch()` runs automatically with refspec `+refs/aet/*:refs/aet/*` when a remote exists. Its own module docstring claims the backend "is local-only by default", which is false about the module it documents. Cross-machine parity therefore needs no new transport — only R-7's enumeration change and R-8's deletions.

**Phase 7 is mostly built.** ADR-045's `integration_mode: single-pr` already opens one PR at the epic level, keeps per-task branches local and ephemeral (§4), moves merge verification up to the epic (§3), and serializes integration behind a lock with mandatory post-rebase re-validation (§5). It was rehearsed by `t2r-13-single-pr-rehearsal`. This repo has no `.agents/aet-config.json`, so it runs ADR-045's degenerate "Scenario A" — `pr-per-task` on trunk. R-17 is the delta, not the mode. ADR-045 §5's lock is documented as "local, single-operator" and stays adequate precisely because multi-user is a non-goal.

**The spec needs a transport, and it is not the forge.** Today the task record carries `plan_file` as a *path* (`parse_frontmatter` in `src/aet/plan_parser.py`), and the projection's `_task_body` writes a title plus a reference to that path, not the spec (`GitHubBackend` in `src/aet/backends/github_backend.py`). Meanwhile `stage_enabled()` and `gate.required_evidence()` read plan frontmatter *at run time*, so the plan file is load-bearing for pipeline routing and gate skips — not only for the agent's instructions. A plan authored on one machine therefore does not reach another by any route: gitignored in git, a path in refs, a reference in the issue. R-19 puts the spec in the record, which already travels, and rejects the issue body as the home because that would make the forge load-bearing for execution and would leave shadow projects with no equivalent.

**Phase 2 must precede Phase 7.** The plan-overlay clobber (`_copy_deferred_files` overwriting an advanced worktree plan, measured downstream at \~$24 in re-run stages) exists only because the worktree copy diverges from the main copy — which happens only because the footer mutates. Ephemeral plans dissolve it. Under `single-pr` it gets *worse*, since worktrees rebase onto a moving tip and refresh more often.

`learnings.jsonl` **is load-bearing.** It is read on every session start — `collect_learnings` in `src/aet/cli/context.py`, and `context_digest.py` injects the most recent entries as "durable insights". Whether to commit it is the operator's choice; the consequence of not committing is machine-local learnings and per-machine recurrence counting. R-2 keeps the tracked-and-tolerated case working.

**The archive is read.** `metrics.py` threads `archive_dir` into `iter_settled_tasks`, so `aet metrics` and `aet retro` pull settled-task metadata from it. R-5 relocates it rather than deleting it, and leaving settled plans in the scanned directory is rejected: `plans_lint`, `plan validate`, the R-trace lint and `gate review` all glob `docs/plans/*.md` and would degrade as settled work accumulates.

**CONTEXT.md's glossary has the two stores' roles inverted.** It states the provenance ledger "is the sole authority for settled-ness", that under `git-refs`it "lives in `refs/aet/*` and travels with the repository", and that `.agents/work-history.jsonl` is "write-only telemetry" to be avoided as the ledger. All three are false: the ledger has no production reader, is a working-tree file under both backends, and work-history is read by `_is_settled_from_authority`, `track_record` and `metrics` — it *is* the settled-ness input the glossary attributes to the ledger. This matters more than the other four sites because `aet-validate-scope` validates every future plan against this glossary, so a false domain model compounds. R-18 covers it.

**Configuration is silent today, and there is prior art to build on.** `_validate_options` in `src/aet/cli/configure_backend.py` checks the *values* of the two options the `configure` command knows about, but nothing anywhere checks for unknown keys — there is no key schema, so a hand-written `.agents/aet-config.json` with `projection` instead of `projections`, or `integraton_mode`, is silently ignored and the operator believes it is configured. Two concrete contradictions already exist: `configure --task-backend`'s help says the default is git-refs while `src/aet/backends/factory.py` defaults to json; and `aet setup verify` prints built-in defaults as though they were project configuration under a venv install, its provenance reading `default`/`trunk`instead of `config (project)`. The machinery to fix this is present — `resolve_config_with_source` and `resolve_integration_mode_with_provenance`already return provenance — so R-20 is about applying it consistently and failing closed on the cases it cannot resolve, not about building something new. The shadow posture makes this urgent rather than cosmetic: R-15 and R-16 turn configuration into the thing that decides whether refs reach someone else's remote.

**Retracted premises, recorded so they are not re-argued.** Offline capability is not a design constraint. Machine-local verdicts are ADR-055 decision 4's decided design, not a gap. `src/aet/backends/git_refs_backend.py`'s "local-only by default" is false. An earlier draft of the audit claimed verdict events are always deleted with the worktree; that holds for `aet run-one` and not for `aet run`, because only the batch path sets `AET_REPO_ROOT`.

## Agreed Vocabulary (lands with R-18)

Settled at scope validation, recorded here rather than in CONTEXT.md because it describes the post-R-19 model and the glossary must state what the code does:

- **Task** — the board entry, carrying the spec. No longer "one atomic `docs/plans/*.md` file"; after R-19 no plan file need exist on the machine that runs it.
- **Rendered Plan** — the ephemeral working copy produced in a worktree from the Task record. Never committed, never the source of anything.
- **Issue** — the GitHub projection of a Task, plus the carrier of the `aet:sprint`intent label. `_Avoid_: issue` keeps its meaning ("do not call a Task an Issue") while the projection gains a name.
- **Board** — the set of open work. Distinct from **Plan Backlog** (approved, not yet on the board) and from the deprecated "Work Queue / Sprint Board" wording.
- **Shadow Posture** — the permanent local-only mode of R-15/R-16.

CONTEXT.md was corrected at scope validation to describe today's reality — the ledger as unread provenance with no transport, the Execution Log as a read input, and a new **Settled-ness Authority** entry naming the three inputs that actually answer "is it done?". R-18 replaces that with the shipped model.

## Resolved at Scope Validation

- **Shadow per-task spec is machine-local and unbacked** — accepted. Better than the question implied: R-19 puts the spec in the task record under `refs/aet/tasks/*`, which lives in `.git`, so it survives worktree destruction and is lost only with the machine. No eager archive at approval.
- **`aet gate review` is kept** as the shadow-mode board. Not free — it must be re-pointed at the board rather than a plans glob (R-6).
- **Archive: new location only.** No dual-read; a one-time copy at migration preserves historical metrics (R-5).
- **No `claim` operation** until multi-user arrives.
- **Shadow posture is inferred** from the absence of project-scope config, and announced on every run (R-15, R-20).

### Default posture, and how it is made obvious

Inference cannot distinguish *deliberately shadow* from *not yet configured*, and that is acceptable because the two want the same behaviour: **a project nobody configured is local.** Staying local is the correct default and the safe direction — a project can never leak `refs/aet/*` to someone else's remote by omission. Multi-device is the deliberate choice, so it is the one that requires saying so.

What remains is discoverability, not correctness. Two requirements cover it: R-15 makes every run announce the inferred posture and its consequence, so the reason machine B cannot see the board is one message rather than an investigation; and R-23 makes opting in an explicit named command with the default documented, rather than a side effect of creating a config file.

This repository has no `.agents/aet-config.json`, so it is local by this rule — correct today, and one `aet configure` away from the plan-on-A-run-on-B scenario in R-19.

## Divergence Summary

*Recorded: 2026-08-14 — Branch: owb-01-spec-travels-in-task-record*

### Deferred

- **Merge branch to main and verify integration**: planned as the final task in `docs/plans/owb-01-spec-travels-in-task-record.md`, but it is owned by the `aet-ship` stage and will be completed when that stage runs.

### Changed

- **Untracked live-plan count**: the branch removed 66 tracked `docs/plans/*.md` files, not the 53 counted at planning time, because more live plans had accumulated in the interim. The implementation untracked every tracked live plan so `.gitignore` now holds.

## Divergence Summary — owb-15-backfill-task-record-specs

*Recorded: 2026-08-15 — Branch: owb-15-backfill-task-record-specs*

All five planned tasks landed. The divergences are in where the code went and in what the migration had to tolerate.

### Changed from plan

- **Task 1 — where the migration lives**: the plan named `src/aet/backends/git_refs_backend.py` as a file to modify. It was not touched. Recovery reads plan blobs directly with `git show <rev>:<path>` and writes through the existing `backend.save()` / `backend.push()`, so the backend needed no change; the migration is a new module, `src/aet/spec_backfill.py`, with `aet state backfill-specs` as its entry point in `src/aet/cli/aet_state.py`. `src/aet/backends/factory.py` was modified instead — `_queue_repo_root` became public as `queue_repo_root` — so the migration anchors the repository root exactly as the backend does rather than deriving it a second way (the fault recorded in the 2026-08-14 config-anchoring learning).
- **Task 1 — `plan_parser.py` change is a split, not new parsing**: the migration reads git blobs that never touch the filesystem, so `parse_frontmatter`, `_extract_body_and_title` and `extract_plan_spec` each gained a text-level counterpart (`*_from_text`) and the path-based functions became thin wrappers over them. Extraction behaviour is unchanged and existing callers are untouched.

### Added (unplanned)

- **`--rev` with a resolvability check**: the source revision is an option defaulting to `b95538dd~1`, and `rev_is_available` verifies it resolves in this clone. Without the check, a typo or a shallow fetch is indistinguishable from a revision in which every plan happens to be absent, and the migration would blame each record in turn.
- **UTF-8 pinned on blob decoding**: `git show` output is decoded as UTF-8 with `errors="replace"` rather than by the process locale. Plans carry em-dashes and status glyphs; under a C/POSIX locale (bare container, cron) locale decoding raises and takes the whole migration down.
- **Working-tree fallback**: a record whose plan is absent from `--rev` is resolved from the working tree before being skipped, because a plan authored after that revision exists only on disk.
- **Dry-run by default**: the command previews without `--apply`, matching the `aet state reset` convention. The plan assumed a single write path.
- **Run-lease refusal and `--force`**: the write path goes through `queue_lib.lease_guard` and the queue lock, and re-loads under the lock, so the migration cannot mutate the board under a live run. Covered by `tests/state/test_spec_backfill_cli.py`.
- **`docs/CLI.md` regenerated** for the new subcommand, and `tests/cli/test_build_parsers.py` extended so the command roster stays asserted.

### Deferred

- **Merge verification** (`git merge-base --is-ancestor HEAD origin/main`) — owned by the `aet-ship` stage and completed when that stage runs.

## Divergence Summary — owb-08-single-source-ledger-path

*Recorded: 2026-08-17 — Branch: owb-08-single-source-ledger-path*

All four planned tasks landed. The divergences are in test scope and line-number references.

### Changed from plan

- **Task 2 — line-number references**: the plan named writers across `sprint.py`, `aet_state.py`, `gate.py`, and `ship.py`. The actual edits shifted because of intervening import changes; the five writers converted are the same five sites across `sprint.py`, `aet_state.py`, `gate.py`, and `ship.py`.

### Added (unplanned)

- **`tests/gate/test_gate_submit.py` and `tests/state/test_aet_state.py` updated to set `AET_LEDGER_PATH`**: the new resolver no longer computes the ledger from `$AET_REPO_ROOT`, so existing gate and state tests that asserted on the ledger file needed an explicit `AET_LEDGER_PATH` override to keep their fixture isolation.

### Deferred

- **Merge branch to main and verify integration** — owned by the `aet-ship` stage and completed when that stage runs.

## Divergence Summary — owb-04-plan-tooling-and-board-review

*Recorded: 2026-08-19 — Branch: owb-04-plan-tooling-and-board-review*

All four implementation tasks landed; the merge verification remains owned by `aet-ship`.

### Changed from plan

- **Task 3 — where the spec size is resolved**: the plan named `src/aet/plan_size.py` as a file to modify. That module was not touched. Instead, `src/aet/plan_parser.py` gained `task_routing_data` to extract frontmatter from the portable task spec, and the two consumers (`src/aet/cli/orchestrator.py` and `src/aet/queue.py`) now read the declared size from the record. The `plan_size.delivered_size` contract is unchanged.
- **Task 2 — additional files touched**: `src/aet/cli/plan.py` and `src/aet/cli/plans.py` were updated to filter settled plans before invoking the validators/linter, and `src/aet/plan_parser.py` was extended with `is_settled_plan`. These were not listed in the plan but are necessary plumbing for the live-work-only behavior.

### Added (unplanned)

- **`docs/CLI.md` regenerated** to reflect the new `gate review --plans-dir` escape-hatch wording.
- **Tests outside the listed directories**: coverage for delivered-size-from-spec lives in `tests/orchestrator/test_orchestrator.py` and `tests/queue/test_queue.py`, not in `tests/plan/` or `tests/gate/`.

### Deferred

- **Merge branch to main and verify integration** — owned by the `aet-ship` stage and completed when that stage runs.

## Divergence Summary — owb-05-board-is-open-work

*Recorded: 2026-08-19 — Branch: owb-05-board-is-open-work*

All eight implementation tasks landed; merge verification remains owned by `aet-ship`.

### Changed from plan

- **Files to Modify was wrong in both directions**: `src/aet/queue.py` was listed but untouched — no settled-ness filter lived there; the derivation lived in `src/aet/cli/aet_state.py` (`_derive_all_states`), `init_queue.py`, and `plan_parser.py`. Conversely `src/aet/plan_parser.py` (`new_task_from_plan` now takes `live_tasks` instead of `settled_ids`), `src/aet/cli/main.py` (init-queue unregistered), and `src/aet/cli/sprint.py` were modified though not listed.
- **Task 6 — the refusal mechanism is a fallback flip**: readiness refusal landed in `derive_status` (`src/aet/cli/aet_state.py`), where blockers that cannot be resolved now derive `blocked` instead of the previous `planned` fallback, so no external assertion can promote a task.
- **Task 4 — history demoted by removal, not demotion-in-place**: `_derive_all_states` lost its `history` parameter entirely and `blocker_status` treats a blocker absent from the board as `merged`. `.agents/work-history.jsonl` survives only as the metrics/retro measurement log.
- **Tasks 2 and 3 landed as one deletion**: `init-queue` and `_is_settled_from_authority` were removed together by deleting the whole `src/aet/cli/init_queue.py` module (395 lines), rather than as two separable edits.
- **Task 8 — equivalence proof shape**: equivalence is demonstrated by targeted tests (`tests/state/test_board_membership.py`, `tests/queue/test_sync.py`, and the no-deadlock-on-merged-blocker test in `tests/workflow/test_aet_work_add_review.py`), not by a corpus-wide before/after harness comparing the live set task by task.

### Added (unplanned)

- **`next.py derive_queue` accepts portable specs**: a task whose record carries an R-19 `spec` stays pickable even when its plan file is absent — integration with owb-01 that the plan did not call out.

- **Review-flagged documentation sweep**: `docs/CLI.md` regenerated, plus `docs/CONVENTIONS.md`, `docs/PIPELINE.md`, `docs/diagrams/plan-task-lifecycle.md`, `skills/aet-work/SKILL.md` and three of its reference files updated to drop stale init-queue references (commits `10f2caeb`, `9e27e2aa`).
- **Test churn beyond the listed directories**: deleted `tests/plan/test_intake_gate.py`, `tests/orchestrator/test_status_liveness_contract.py`, `tests/state/test_versioned_membership.py` and parts of `tests/state/test_state_reset.py`; added `tests/queue/test_sync.py` and `tests/state/test_board_membership.py` for the equivalence proof (task 8).

### Deferred

- **Merge branch to main and verify integration** — owned by the `aet-ship` stage and completed when that stage runs.

## Divergence Summary — owb-07-git-refs-only-store

*Recorded: 2026-08-20 — Branch: owb-07-git-refs-only-store*

All four implementation tasks landed; merge verification remains owned by `aet-ship`.

### Changed from plan

- **Files to Modify was too narrow**: the plan listed six locations, but retiring the json backend and the `task_backend` axis touched 80 files. Call sites referencing `.agents/work-queue.json`, `JsonBackend`, `UnknownBackendError`, and backend-selection logic were scattered across `src/aet/backends/__init__.py`, `src/aet/backends/git_refs_backend.py`, `src/aet/backends/github_backend.py`, `src/aet/cli/aet_state.py`, `src/aet/cli/backlog.py`, `src/aet/cli/desk.py`, `src/aet/cli/gate.py`, `src/aet/cli/main.py`, `src/aet/cli/next.py`, `src/aet/cli/orchestrator.py`, `src/aet/cli/reconcile.py`, `src/aet/cli/report.py`, `src/aet/cli/ship.py`, `src/aet/cli/sprint.py`, `src/aet/cli/status.py`, `src/aet/cli/sync.py`, and `src/aet/worktree.py`.
- **Default queue file changed**: `factory.create_backend` now defaults `queue_file` to `.agents/aet-queue` instead of `.agents/work-queue.json`, removing the last json-backend-shaped default path.
- **Task 2 abstraction collapse**: `TaskBackend.seal` lost its default JSON-file implementation and now raises `NotImplementedError`; `GitRefsBackend` already provided its own override, so this is a documentation-of-reality change rather than new behavior.

### Added (unplanned)

- **`docs/CLI.md` regenerated** to reflect the removal of `aet configure --task-backend`.
- **Test updates outside `tests/backends/`**: tests in `tests/cli/`, `tests/state/`, `tests/orchestrator/`, `tests/projections/`, `tests/queue/`, `tests/metrics/`, `tests/migration/`, `tests/ship/`, `tests/plan/`, and `tests/worktree/` were updated to use git-refs fixtures or to remove json-backend assumptions.

### Deferred

- **Merge branch to main and verify integration** — owned by the `aet-ship` stage and completed when that stage runs.

## Divergence Summary — owb-13-prd-integration-branch

*Recorded: 2026-08-19 — Branch: owb-13-prd-integration-branch*

All three implementation tasks landed; merge verification remains owned by `aet-ship`.

### Changed from plan

- **Task 1 — where the derivation lives**: the plan named `src/aet/backends/factory.py` as a file to modify. It was not touched. The derivation logic is a new module-level contract in `src/aet/branch_ref.py` (`derive_integration_branch_from_prd`, `_task_prd_path`, `resolve_integration_branch_for_task`), consumed by `src/aet/cli/orchestrator.py`, `src/aet/cli/aet_state.py`, and `src/aet/cli/ship.py`. This keeps branch-name resolution in one place rather than splitting it across backend and CLI code.
- **Additional files touched**: `src/aet/cli/aet_state.py` was updated so that audit, heal, validate, reset, transition, and record-merge all resolve the integration branch per-task; `src/aet/plan_parser.py` gained `prd_path_from_text` and `prd_path_for_plan` to extract the PRD reference from a plan body; and `src/aet/plan_validate.py` now reuses that parser.

### Added (unplanned)

- **Tests outside `tests/orchestrator/`**: coverage for `ship verify` resolving a PRD-derived branch lives in `tests/cli/test_ship_verify.py`, and coverage for `aet state` transition/record-merge lives in `tests/state/test_aet_state.py`.

### Deferred

- **Merge branch to main and verify integration** — owned by the `aet-ship` stage and completed when that stage runs.

---

## Divergence Summary — owb-10-sprint-label-intake

*Recorded: 2026-08-20 — Branch: owb-10-sprint-label-intake*

### Changed from plan

- **Task 5 — where single-enumeration lives**: the plan named `src/aet/projections/dispatcher.py` as a file to modify. That file was not touched. The one-enumeration-per-run guarantee is implemented in `src/aet/backends/github_backend.py` (`find_sprint_candidates` calls `_list_issues_retry` once), and the dispatcher remains uninvolved because the read path is not a projection write.
- **Task 6 — retry location**: the retry/backoff logic also lives in `src/aet/backends/github_backend.py` (`_run_gh_with_retry`) rather than in the dispatcher.

### Added (unplanned)

- **`docs/CLI.md` regenerated** to document the new `aet sprint intake` subcommand.
- **`tests/cli/test_sprint_intake.py` and `tests/cli/test_build_parsers.py` updates**: the plan listed `tests/queue/` generically; command-level coverage lives under `tests/cli/`, with parser roster assertions updated.
- **`tests/queue/test_queue_guard.py` adjustment**: existing lease-guard tests now invoke `sprint.main(["add", ...])` to match the subcommand dispatch shape, keeping the guard tests passing.

### Deferred

- **Merge branch to main and verify integration** — owned by the `aet-ship` stage and completed when that stage runs.

---

## Divergence Summary — owb-11-shadow-posture

*Recorded: 2026-08-20 — Branch: owb-11-shadow-posture*

All five implementation tasks landed; merge verification remains owned by `aet-ship`.

### Changed from plan

- **Files to Modify omitted prior work**: `src/aet/cli/configure_backend.py` was listed but was not touched. The `--scope team|shadow` vocabulary and the `--guided` setup flow were already in place from earlier branches, so posture inference is built on the existing `resolve_config_with_source` rather than on new config machinery.
- **Additional files touched**: `src/aet/backends/base.py` (posture constants), `src/aet/cli/aet_state.py` (closure push exemption handling), `src/aet/cli/backlog.py`, `src/aet/cli/orchestrator.py`, `src/aet/cli/reconcile.py`, and `src/aet/cli/sprint.py` (posture plumbing) were modified though not listed.

### Added (unplanned)

- **Test adjustments for the new default**: existing tests in `tests/state/test_aet_state.py`, `tests/state/test_desk_actions.py`, and `tests/state/test_quarantined_state.py` now create a project-scope config so they continue to exercise the shared-posture history-write and push paths after shadow became the default. `tests/cli/test_sprint_intake.py` was updated to seed the queue through `GitRefsBackend` after the json backend removal left the old JSON-file fixture empty.
- **Learning entry** for the `test_sprint_intake.py` fixture fix in `.agents/learnings.jsonl`.

### Deferred

- **Merge branch to main and verify integration** — owned by the `aet-ship` stage and completed when that stage runs.

## Divergence Summary — owb-12-config-honesty

*Recorded: 2026-08-21 — Branch: owb-12-config-honesty*

All five implementation tasks landed; merge verification remains owned by `aet-ship`.

### Changed from plan

- **Task 4 — default-backend contradiction**: the plan named a disagreement between `configure --task-backend` help and `factory.py` defaults. The `task_backend` axis and json backend were removed in `owb-07-git-refs-only-store`, so the contradiction no longer exists and no code change was required in this branch.

### Added (unplanned)

- **`docs/CLI.md` regenerated** to document the new `aet configure --shared` flag.
- **`tests/backends/test_config_honesty.py`**: new test module covering unknown-key rejection, misspelled-key rejection, and projection-in-shadow contradiction.
- **`tests/projections/test_projection_dispatcher.py` updated** to assert that projections in shadow config are rejected and that non-projection keys still resolve external-first.

### Deferred

- **Merge branch to main and verify integration** — owned by the `aet-ship` stage and completed when that stage runs.

---

## Divergence Summary — owb-14-documentation-truth

*Recorded: 2026-08-21 — Branch: owb-14-documentation-truth*

All four implementation tasks landed; merge verification remains owned by `aet-ship`.

### Changed from plan

- **Task 1 — transport claims**: corrected across the five named files. `src/aet/backends/git_refs_backend.py` was narrowed to "queue state" replication and `src/aet/cli/sync.py` to "queue backend configuration"; the corrections are also enforced by new rules in `.agents/doc-rules.yaml`.
- **Task 3 — ADR number**: the new ADR was assigned number `063` (`docs/adr/063-open-work-board-contract-and-shadow-posture.md`).
- **Task 4 — vocabulary**: the agreed vocabulary landed in `CONTEXT.md` and was propagated to related glossary entries and example dialogue (e.g., "Work Queue" → "Board").

### Added (unplanned)

- `.agents/doc-rules.yaml` gained `must_not_contain`, `must_contain`, and `path_exists` rules to make R-18 documentation truth durable.
- `docs/CLI.md` was regenerated to reflect the narrowed `sync.py` help text.
- `.agents/learnings.jsonl` gained an entry recording the QA full-suite red-ness triage.

### Deferred

- **Merge branch to main and verify integration** — owned by the `aet-ship` stage and completed when that stage runs.

*Stage: synced*

*Next step: run `aet-ship`*
