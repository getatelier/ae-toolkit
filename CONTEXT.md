# AE Toolkit Work Queue Context

The Agentic Engineering Toolkit uses a work queue and a provenance ledger to coordinate sequential and parallel task execution across planning, implementation, review, and shipping skills.

## Language

**Provenance Ledger**:
The append-only, content-addressed store of task transition and closure events, at `.agents/ledger.jsonl`. Events are idempotent and commutative — concurrent appends from independent writers merge without conflict — and the store verifies every line against its own content address on load, refusing a file whose ids no longer attest their bodies.
It has **five writers and no production reader**: `aet sprint add`, `aet state set-stage`, terminal closure, `aet gate submit`, and `aet ship open` append to it, and nothing in `src/aet` calls `read_events()`. It is a working-tree file under **every** backend — no backend implements ledger storage — and it is gitignored, so it does not travel between machines. It is provenance only, not the settled-ness authority. See **Settled-ness Authority** for what actually answers "is it done?".
_Avoid_: describing the ledger as refs-borne or as the settled-ness authority; deriving settled-ness from plan frontmatter.

**Board** (also called the **Work Queue**):
The set of open work: the ephemeral active list of tasks loaded by the queue backend. Under the `git-refs` backend it is stored in `refs/aet/tasks/<id>` per task, `refs/aet/sealed/<id>` per sealed tombstone, and the `refs/aet/meta/queue` envelope, and pushed to/fetched from origin. Plans enter the board through `aet sprint add` or `aet sprint intake`, not from frontmatter fields (ADR-055, ADR-066). Discovery is record-based; `aet queue sync` never scans the plans directory (ADR-054).
_Avoid_: issue tracker.

**Task**:
The board entry, carrying the spec. A task is represented by one record under `refs/aet/tasks/<id>` while active, plus an optional sealed record under `refs/aet/sealed/<id>` once terminal. After intake, the record's `spec` is the source of the plan; no plan file need exist on the machine that runs it.
_Avoid_: ticket, story, issue.

**Plan File**:
The markdown document in `docs/plans/` authored in the planning phase. It describes how to implement a task and is the artifact of the **Author** phase. After intake, the task record's `spec` is the source of intent; the plan file may be rendered into a worktree as an ephemeral working copy.
_Avoid_: PRD, roadmap, spec.

**Rendered Plan**:
The ephemeral working copy produced in a worktree from the **Task** record. Never committed, never the source of anything.

**Issue**:
The GitHub projection of a **Task**, plus the carrier of the `aet:sprint` intent label. Not the source of truth.
_Avoid_: using "issue" for a Task.

**State**:
The canonical workflow state stored in `tasks[].state` while a task is in the queue: `planned`, `ready`, `blocked`, `in_progress`, `awaiting_merge`, `failed`, or `quarantined`.
_Avoid_: using `state` for terminal truth.

**Inert Task**:
A task on the board that has not yet run: its state is one of `planned`, `ready`, or `blocked`, and it has no `branch`, `worktree`, or `merge_commit` assigned. An inert task's plan spec can be re-ingested from the plan file via `aet sprint add` without deleting refs on origin (ADR-068).
_Avoid_: re-ingesting a task that carries run state.

**Status (plan lifecycle)**:
_Deprecated._ The `status` frontmatter field left the plan contract in ADR-055 and is now rejected by `aet plans lint`. Settled-ness is derived by **Settled-ness Authority**. The `_Stage:_` footer is a breadcrumb only.
_Avoid_: using plan `status` for any runtime scheduling or settled-ness decision.

**Blocker**:
A task that must reach a terminal state before another task can become pickable.

**Dependent**:
A task that is blocked by another task.

**Terminal State**:
A terminal closure event that ends a task's lifecycle and satisfies blockers: `merged` or `abandoned`. Recorded in both the **Provenance Ledger** and the **Execution Log**.
_Avoid_: done.

**Plan Backlog**:
Plans in `docs/plans/` that are not yet on the board and not yet closed.

**Shadow Posture**:
The permanent local-only mode inferred from the absence of project-scope AET configuration. Configuration lives at user scope, no projection runs, and no AET artifact appears in the working tree. Because the operator has not opted into cross-device sharing, `refs/aet/*` are never pushed. Every run announces the inferred posture and its consequence.

**Execution Log**:
`.agents/work-history.jsonl`, the gitignored append-only log of transitions and closures. It feeds project-management reporting (`aet metrics`, `aet retro`, and ADR-028's zero-review track record) **and** it is one of the three inputs to **Settled-ness Authority** — it is not optional in practice, and it is read, not write-only.
_Avoid_: calling it write-only telemetry, or assuming a task's closure survives its loss.

**Settled-ness Authority**:
What actually answers "is it done?": the sealed task record in `work-history.jsonl`, consulted by `aet queue sync` (reporting "skipped (already settled)") and verified by `aet state record-merge` against the resolved trunk branch. The authority is a task record, not the plan file or the **Provenance Ledger**.
_Avoid_: attributing this role to the **Provenance Ledger** (ADR-055 assigns it there; the code does not implement it) or to a plan-file footer.

**Source PRD**:
The product requirements document that generated the plan, referenced from the plan file's Context section.

**Declared Size**:
The `size` value in a plan file's frontmatter — `S`, `M`, or `L`. It is a _prediction_, made at plan time, of how large the change will be. It is not enforced at intake: plan-time diff size is not derivable from the plan document, so no proxy for it is gated. See ADR-046 for the measurement and decision.
_Avoid_: treating a declared size as a measurement, or as a limit intake will enforce.

**Delivered Size**:
The _measured_ diff of a task, computed at closure over the first-parent range of its `merge_commit` and recorded on the Execution Log entry. The headline figure excludes planning artifacts (`docs/`, `.agents/`, `content/`, `reports/`); the total is retained alongside it.
_Avoid_: calling this "size" unqualified — the whole point of recording it is that it is comparable to, and frequently diverges from, the **Declared Size**.

**Divergence Record**:
The mechanical record of unplanned work computed at terminal closure: the merged first-parent range's changed files minus the file list declared in the task's `spec` (under `Files to Modify`), plus any recoverable test-count delta. Stored on the **Execution Log** entry independently of the `docs_sync` routing key. Fails soft with a status and reason rather than blocking closure. Distinct from the narrative **Divergence Summary**, which remains the judgment and obligation of the `aet-sync-docs` stage when it runs.
_Avoid_: expecting the divergence record to be written by `aet-sync-docs`; skipping the mechanical record when `docs_sync: skipped`.

**Band**:
The expected **Delivered Size** range attached to each **Declared Size** label. A band is a falsifiable claim about delivery, re-checkable against the recorded distribution — not an intake limit.

**Pipeline Mode**:
The per-plan orchestration-isolation setting declared in plan frontmatter: `minimal` (all skilled stages in one session), `standard` (default stage groups), or `full` (one session per stage). Advisory default follows **Declared Size**; changes touching auth, data models, API contracts, dependencies, or persisted state override to `standard`/`full` regardless of size (ADR-047).
_Avoid_: confusing it with **Integration Mode**, which is repo configuration, not per-plan frontmatter.

**Integration Mode**:
The repo-level configuration (`integration_mode: pr-per-task | single-pr`) controlling whether each task ships its own PR or tasks accumulate onto one integration branch (ADR-045). Under `single-pr`, "done" has a second meaning — task merged into the integration branch vs. epic merged into trunk.

**Shadow Config**:
The project-local configuration layer that overrides the team config for one repo (ADR-048). The configuration used in anger pairs `single-pr` with a shadow config and a heavy dependency environment — distinct from the dogfooded configuration (trunk + team config + no dependencies).

## Plan Lifecycle (ADR-061, ADR-068)

The source of truth for a task's spec changes at one explicit handoff:

1. **Author** — `aet-plan` writes `docs/plans/<id>.md`. The file is the artifact.
2. **Intake** — `aet sprint add` ingests the file into the task record's `spec`. This intake is repeatable while the task remains an **Inert Task** (ADR-068); once execution begins, the record's `spec` is frozen.
3. **Post-intake** — execution, shipping, closure, and measurement read `spec.frontmatter`, `spec.title`, `spec.body`, and `spec.tasks` from the record. No consumer resolves `plan_file` as a path.

See ADR-061 (`docs/adr/061-the-record-is-the-plan-after-intake.md`) and ADR-068 (`docs/adr/068-intake-is-repeatable-while-a-task-is-inert.md`) for the full decisions and consequences.

## Relationships

- A **Task** has a `spec` ingested at intake. Before intake, the **Plan File** is its authoring artifact; after intake, the record's `spec` is the source of intent.
- A **Task** may have zero or more **Blockers**.
- A **Task** may be a **Blocker** for zero or more **Dependents**.
- A **Dependent** becomes `ready` only when all its **Blockers** have a **Terminal State**; the writer promotes it forward when the last blocker reaches terminal.
- A plan enters the **Board** through `aet sprint add` or `aet sprint intake`; board membership is the admission record, not a frontmatter field.
- A plan is closed when its task reaches the terminal state `merged` or `abandoned`; at that point it no longer appears on the **Board**.
- Closure records the terminal event in the **Provenance Ledger** and **Execution Log**.
- A **Task** has one **Declared Size** (predicted at plan time) and, once closed, one **Delivered Size** (measured at closure). The pair is what makes a **Band** checkable; neither substitutes for the other.

## Example dialogue

> **Dev:** “I added a new plan file. Why doesn’t `aet-work status` show it as `ready`?”
>
> **Expert:** “Approved plans are not added to the sprint automatically. Run `aet sprint add docs/plans/<id>.md` to put it on the board; it will become `ready` if it has no blockers. Use `aet gate review` to see all approved plans that are not yet on the board.”

## Multi-Machine Operator Posture

Queue state travels with the repository via `refs/aet/*` on origin — `refs/aet/tasks/<id>` per task, `refs/aet/sealed/<id>` per sealed tombstone, plus the `refs/aet/meta/queue` envelope. A task leaves the board by assertion (the tombstone), not by absence; `load()` treats a tombstoned task as no longer live and reaps the local task ref as housekeeping (ADR-059). The **Provenance Ledger** and the **Execution Log** do **not** travel: both are gitignored working-tree files with no transport. A fresh clone must fetch the queue explicitly:

```bash
git fetch origin 'refs/aet/*:refs/aet/*'
```

`~/.aet` stays machine-local: it holds config, telemetry, and reports, and is never pushed. Offline work is safe; mutation pushes are best-effort everywhere except closure, where a failed push fails the closure loudly (ADR-055). `git fetch --prune` is unsafe for `refs/aet/*`: a local-only task is indistinguishable from a deleted-upstream task, so pruning destroys work that has not yet pushed (ADR-059).

## Forward-Only State Model (ADR-011, revised by ADR-013)

**State**:
The canonical workflow state stored in `tasks[].state` while a task is active in the queue: `planned`, `ready`, `blocked`, `in_progress`, `awaiting_merge`, `failed`, or `quarantined`.
_Avoid_: using `state` for terminal truth.

**Inert Task**:
A task on the board that has not yet run: its `state` is one of `planned`, `ready`, or `blocked`, and it has no `branch`, `worktree`, or `merge_commit` assigned. An inert task's spec can be re-ingested by running `aet sprint add` on the updated plan file. (ADR-068)
_Avoid_: attempting to re-ingest a task that has begun execution or carries run state.

**Terminal State**:
A terminal ledger event that ends a task's lifecycle and satisfies blockers: `merged` or `abandoned`. `failed` is **not** terminal and does **not** unblock dependents.
_Avoid_: treating `failed` or legacy `done` as terminal.

**Quarantined**:
A non-actionable task state entered when the **Circuit Breaker** judges a failure deterministic (`{in_progress, failed} → quarantined`). Like `failed`, it is **not** terminal and does **not** unblock dependents; unlike `failed`, it is never auto-retried — a human clears it forward (`quarantined → ready`) after a fix, or abandons it. (ADR-030)
_Avoid_: conflating a breaker quarantine with human `abandoned`, or expecting the scheduler to ever re-pick it on its own.

## Night-Shift Runtime (ADR-030, ADR-031)

**Failure Class**:
The single category assigned to a terminating agent session: `environment`, `flaky`, `design`, `timeout`, or `canceled`. A fixed, code-owned menu — the breaker's counting never depends on an LLM inferring it. (ADR-030)

**Failure Signature**:
A deterministic short digest of `(stage, normalized-error)` with volatile spans (paths, PIDs, timestamps, ids, line numbers) stripped, so identical failures collide and distinct ones do not. It is the key the **Circuit Breaker** counts. (ADR-030)

**Circuit Breaker**:
The deterministic rule that stops throwing work at a repeating failure: **per-task** (the same **Failure Signature** 3× ⇒ the task is quarantined) and **systemic** (one signature across N distinct tasks ⇒ the shift stops spawning). Counts are persisted, so a quarantine survives across shifts. (ADR-030)

**Triage**:
A bounded judgment session spawned on a failure under the default `--on-failure=triage`, which confirms the **Failure Class** and routes the outcome — requeue (`flaky`/`environment`) vs quarantine (`design`). Judgment lives in an explicit, sanctioned session; the engine only enforces its verdict, and the breaker bounds it. (ADR-030)
_Avoid_: reading "triage" as a runtime conditional embedded in the engine — the engine holds no hidden branch; it spawns a session and enforces the result, as it does for any stage.

**Per-Task Cost**:
Token and dollar totals rolled up per task from stage telemetry onto the task's closure record at close, stored as `cost: {tokens, usd}`. **Analytics only** — read by the desk and the scoreboard, never by any gate, kill, or triage path. Null is preserved honestly: when no stage record carried a measurable value, the field is omitted rather than zeroed or written as a null-valued object. (ADR-031)
_Avoid_: treating cost as a budget ceiling or any execution-control signal; conflating the closure record with the **Provenance Ledger**.

## Run Supervision (ADR-053, supersedes ADR-031 item 2)

**Run**:
One invocation of the orchestrator over one plan (`aet run-one`) or the active queue (`aet run`). Distinct from a **Task** (the unit of work) and from a _session_ (one agent CLI process spawned for a single stage) — one run spawns many sessions.

**Run Id**:
The identifier minted per run (`run-YYYYMMDD-HHMMSS-<suffix>`), naming its metadata directory `.agents/runs/<run-id>/` (holding `output.log`, `pid`, `returncode`). Also the `{run-id}` path segment in the **Telemetry Archive**.

**Detached Run**:
The only execution mode. The orchestrator always runs in its own OS session with stdout redirected to the run's `output.log`; it is never hosted by the invoking session's process. "Detached" describes _where the process lives_, not whether the caller waits.

**Follower**:
The waiter that blocks until a run reaches a terminal state — either a terminal record or death of the run's pid — and then exits with the run's exit code. It emits a **Bounded Report**, never the run's output. `aet run-one` embeds one; `aet run --follow <run-id>` attaches one to an already-spawned run.
_Avoid_: reading "follow" as tailing or streaming. A follower waits and summarizes; it never relays log lines.

**Bounded Report**:
The fixed-shape completion output of a **Follower**: one line per stage with status, duration, and exit code, plus a capped excerpt of the failing stage on failure. Its length does not scale with the volume of run output — that is the whole point. Full output stays on disk in `output.log`.

**Stall Timeout**:
The liveness interval after which the watchdog kills a session that has shown no sign of life. Liveness is hybrid: process-tree activity (active descendants) or run-log/file writes reset the timer. The resulting failure class is `timeout`, and the same class applies to any session killed by a signal (negative exit code) whether from the stall watchdog, the wall-clock backstop, or another signal. A uniform value on every supported `CLIAdapter` (7200 s), not a command flag and not a config key; it is a backstop for true death, not a proxy for per-CLI output cadence. (ADR-053 superseded in part by the liveness redesign, ADR-060)
_Avoid_: treating it as a duration limit — a session with active descendants or growing log files is never killed, however long it runs; treating it as a per-adapter tuning knob.

**Wall Backstop**:
The coarse wall-clock ceiling (`--task-timeout`), retained as a last-resort ceiling even when hybrid liveness reports activity. Defaults to 7200 s and remains overridable.

**Run Liveness**:
Whether a _recorded run_ is still executing — a different question from **Stall Timeout**'s hybrid session liveness, which asks whether a running agent session is doing work. Run liveness is answered from evidence: a recorded `returncode` settles it, and otherwise the run's recorded `pid` must be held by a process whose own start time is not later than the run's recorded `started`. A PID number alone is not the answer, because PIDs are recycled — on 2026-08-29 `aet status` reported two unrelated desktop processes as active runs. Consumed by the active-run listing, the `--follow` wait, and the reclaimability of the **Run Lease**. (ADR-072)
_Avoid_: calling `os.kill(pid, 0)` a liveness check; conflating it with the stall watchdog's session liveness, which shares the module but not the definition.

**Proxy**:
A signal that correlates with a fact and is cheaper to read than evidence of it — a branch existing, a PID being held, the ambient checkout, a field's type, a count of zero. ADR-072 states that a decision depending on a fact reads evidence of that fact, not a proxy for it, and that a change reading a proxy where evidence is reachable is refusable at review. Where a proxy is unavoidable, the call site says so and names the divergence it accepts.
_Avoid_: reading a proxy's confident answer as an evidenced one; demonstrating conformance with a test that constructs proxy and fact together, which cannot show them diverging.

**History**:
Append-only log of transition entries and closure events written to the optional, gitignored `.agents/work-history.jsonl`. It is used for reporting, not for scheduling or closure determination.

**Pending Blockers**:
Counter maintained forward by the state writer; a task becomes `ready` only when `pending_blockers == 0`.

**Stage**:
Sub-state of `in_progress` recorded in the task record (e.g., `implement`, `qa`, `review`).

**Live Set**:
Active tasks in the queue backend (`refs/aet/tasks/<id>` per task, `refs/aet/sealed/<id>` per sealed tombstone, and the `refs/aet/meta/queue` envelope under `git-refs`); the only set loaded for scheduling. The board is recreated as needed.

**Execution Log**:
Optional, gitignored `.agents/work-history.jsonl` containing transitions and closure evidence. Projects may omit it.

**Audit**:
Explicit human-run reconciliation of stored state against git; replaces implicit derive-on-read.

**Gate Evidence (Verdict)**:
A schema-validated JSON verdict written by a checking skill (qa, review, cso, sync-docs) to `~/.aet/reports/{project-slug}/{task-id}/`, consumed fail-closed by the orchestrator's stage gates (ADR-019) and, in `single-pr` mode, by the serialized integration step before the squash-merge lands (ADR-045). The plan footer `*Stage:*` remains a human breadcrumb; gating decisions read evidence, never the footer.
_Avoid_: treating a footer stage string as proof a stage passed.

**Workflow**:
A named, versioned data file defining one linear stage sequence with its skill and evidence bindings (packaged default `src/aet/workflows/<name>.json`, overridable per repo in `.agents/workflows/`). Selected by the plan frontmatter key `workflow:` (default `software`). Stage vocabulary comes from the workflow; lifecycle **State** stays frozen in code.
_Avoid_: calling lifecycle states "workflow state"; using "work class" for a workflow name (work class = a recorded machine-readable task attribute, one of `trivial`/`normal`/`critical`/`unclassified`, authored in plan frontmatter).

**Stage Routing Key**:
Plan frontmatter (`security_review`, `docs_sync`: `required`/`skipped`, with a reason required when skipped) deciding at plan time whether a gated stage runs. Policy input authored at triage — part of the plan's machine contract, not runtime judgment and not state.
_Avoid_: runtime heuristics deciding whether a gate runs.

## Branch Model (ADR-044, ADR-045, ADR-076)

**Trunk Branch**:
The final merge target, resolved as: config → `git symbolic-ref refs/remotes/origin/HEAD` → `main`. No code path names a branch literally. (ADR-044)

**Integration Branch**:
The branch task worktrees are cut from and integrate into. In `single-pr` mode, resolved through the 8-step ordering: CLI override (`--base`) → environment (`AET_WORK_BASE_BRANCH`) → task record stamp (`task['integration_branch']`) → parent document declared branch (`branch` in PRD frontmatter) → envelope active epic (`read_epic()` / `aet epic set`) → PRD filename stem fallback → config `integration_branch` → **Trunk Branch**. In `pr-per-task` mode, steps 3–6 are skipped, and it equals the Trunk Branch in the default mode. (ADR-045, ADR-076)

**Integration Mode**:
Project configuration, `pr-per-task` (default) or `single-pr`, resolved through the external-first config chain. Selects what the terminal event is for a task and who serializes merges — the forge (`pr-per-task`) or AET's local advisory lock (`single-pr`). (ADR-045)

**Epic**:
The set of plans decomposing one deliverable that share one **Integration Branch** and one PR in `single-pr`. An epic's identity is an explicit declaration (branch, PR title, body file) rather than an inference from a PRD filename; not a persisted entity beyond the envelope key and per-task stamp. (ADR-045, ADR-076)
_Avoid_: epic as a separate queue entity or file in `docs/epics/`.

**Active Epic**:
The single declared epic active in the queue envelope metadata at `refs/aet/meta/queue`, declared via `aet epic set <branch> [--title] [--body-file]`. Tasks are stamped with their resolved integration branch at intake; when an in-flight task's stamp does not match the active epic resolution, execution halts fail-closed with an actionable mismatch error. (ADR-076)
_Avoid_: assuming multi-epic concurrency; ignoring mismatch halts without resetting the task or switching the active epic.

**Integrated (terminal semantics in `single-pr`)**:
In `single-pr`, the terminal state `merged` means squash-merged into the **Integration Branch** locally, and blockers unblock on that event; trunk arrival is verified once per **Epic** when the integration branch's PR merges. In `pr-per-task`, `merged` keeps its trunk meaning.
_Avoid_: "done" — the mode decides which event it names.

**Integration Failure**:
An engine-level outcome in `single-pr`: a rebase conflict or post-rebase validation failure while integrating a task that already passed. Distinct from the agent-session **Failure Class** menu (ADR-030), which is unchanged — integration failures are never triaged as task failures, never requeued, and do not count toward the **Circuit Breaker**.
_Avoid_: calling it a task failure; adding it to the ADR-030 menu.

## Telemetry & Panel (ADR-012, ADR-019, ADR-022)

**Telemetry Archive**:
The user-level store of execution records at `~/.aet/telemetry/<main-worktree-dir>/<worktree-label>/{date}/{run-id}/{task-id}.jsonl` (override: `AET_TELEMETRY_ARCHIVE_DIR`). Task logs sit **five** levels below the root because the `{project-slug}` (e.g. `aiskills/main`) spans the first two — see `docs/telemetry-guide.md`.
_Avoid_: "execution log" — that term is reserved for `.agents/work-history.jsonl`; writing `{project-slug}` as a single path segment, which silently matches nothing.

**Project Slug**:
`<main-worktree-dirname>/<current-worktree-dirname>` (primary worktree labelled `main`, e.g. `aiskills/main`), derived by `derive_project_slug()` and shared by the telemetry archive and the gate-evidence reports tree (ADR-022). `AET_PROJECT_ID` overrides.
_Avoid_: origin-remote derived names (pre-ADR-022); using it for config resolution — config uses the **Config Slug** instead.

**Config Slug**:
The main-worktree-only identity (`<main-worktree-dirname>/main`, worktree label dropped) used solely for resolving the external config `~/.aet/{slug}/config.json`, so one personal config serves every linked worktree of a repo. Derived by `derive_config_slug()` (cfg-01). Distinct from the **Project Slug**, which keeps the per-worktree label for telemetry/reports granularity.
_Avoid_: conflating the two slugs; "fixing" the telemetry slug to match (the label is deliberate there, ADR-022).

**Run**:
One orchestrator invocation, recorded as one run directory in the telemetry archive. The execution vehicle for tasks — not the unit of intent.
_Avoid_: calling runs "projects".

**Project (telemetry/panel)**:
The repo-level grouping — first slug segment. The panel's top grouping level.
_Avoid_: "folder" in UI copy.

**Worktree (run attribute)**:
Where a run or session launched — second slug segment, or parsed from a record's raw `plan_file` prefix. An attribute/filter of a run, never a grouping level.

**Live Run (panel)**:
A run with no `last-run.json` whose archive activity is fresh — within `LIVE_FRESHNESS_MINUTES` of the newest recursive mtime, or with an mtime that advanced between panel polls (panel-live-executions PRD, lvp-01/lvp-02). A panel display status only.
_Avoid_: conflating with the queue's **Live Set** (active tasks in `refs/aet/tasks/*` and `refs/aet/meta/queue`) — the two share no code or data.

**Incomplete Run (panel)**:
A run with no `last-run.json` and stale archive activity — crashed, abandoned, or quiet mid-stage. Always rendered with its last-activity time, never as "success" or "crashed".

**Session Log**:
The transcript the **agent CLI itself** writes for one stage session, outside AET — kimi's `~/.kimi-code/sessions/**/agents/*/wire.jsonl`, Claude Code's `~/.claude/projects/<cwd-slug>/<sessionId>.jsonl`. AET reads it, never writes it; each adapter supplies its own reader (ADR-050). Source of **observed** **Test Run** records.
_Avoid_: "wire log" as the general term (that is kimi's schema specifically); confusing it with the **Telemetry Archive** (AET's own store) or the **Execution Log** (`.agents/work-history.jsonl`).

**Test Run (observed / claimed)**:
A `test_run` telemetry record, carrying `source` to say which of two things it is. **Observed** (`"wire"`) — extracted from the **Session Log**: real command, real timestamps, real exit code, no test counts. **Claimed** (`"verdict"`) — derived from a passing QA verdict: test counts, but null timing and a null `exit_code`, so it reads `result: "unknown"` rather than restating the verdict's own pass as a measurement. Duration, throughput, and pass-rate aggregates read observed records only; count aggregates read claimed records only, and say so. (ADR-051)
_Avoid_: aggregating the two populations together; reading a claimed record's `exit_code: 0` as a measurement; inferring provenance from field signatures on new records (pre-2026-07-26 records are provenance-unknown and are not backfilled).

**First-Pass Merge**:
A settled task that reached `merged` with every verdict kind required by its plan's **Stage Routing Key** passing, no failed **stage** telemetry record, and no **Rework**. Computed retroactively from settled history + telemetry archive + gate evidence by one shared definition consumed by the desk, `aet metrics`, and the scoreboard. (ADR-035, refining ADR-028; `test_run` clause removed by ADR-052)
_Avoid_: requiring verdicts for gates the plan routed to `skipped`; persisting a `first_pass` flag (derivation is query-side); disqualifying on a failed **Test Run** record (a red TDD step is not a second pass — ADR-052).

**Rework**:
Per task, the count of repeated **stage** telemetry records beyond the first per stage name, plus `failed → *` re-entry transitions. A task with zero rework is a candidate **First-Pass Merge**. (ADR-035; `test_run` records excluded by ADR-052)
_Avoid_: counting `failure_signatures` as rework (a separate signal); a second definition outside the shared counting core; counting **Test Run** records — they carry a `stage` field, and grouping them by it once produced 418 phantom rework units across 127 tasks (ADR-052).

**Cost per Merged Task**:
The sum of a task's stage telemetry (`token_count` / `cost_estimate`) across the whole **Telemetry Archive** — cross-run — reported with explicit coverage counts. Null-honest: all-null stays null (Kimi `usd` is null by design), never estimated. Distinct from **Per-Task Cost**, which is the settling-run rollup stored on the ledger record for desk display. Analytics only, per ADR-031. (ADR-035)
_Avoid_: reading it from the ledger `cost` field (under-counts reworked tasks); treating it as a budget or control signal.
