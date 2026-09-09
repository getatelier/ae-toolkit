# AE Toolkit

An integrated agentic engineering system. Skills are directories of instructions, examples, and reference material that guide an agent through each phase of the workflow — from discovery and planning to implementation, review, security, shipping, and release. They are designed to be installed together; the pipeline only works when the whole system is present.

---

## Current Version: 1.14.0

Last updated: 2026-09-09

---

## Core Features

### Planning Skills

Turn ideas into actionable, validated plans.

- **aet-plan** — PRD creation, goal clarification, atomic `plan.md` generation, and a `validate` command that checks plans against structure, scope, dependency, and traceability rules. Requirement coverage counts the work already finished for the same PRD, so a plan is only asked to trace what nobody has delivered yet, and each result names how many plans it checked and against what.
- **aet-pipeline-plan** — End-to-end planning pipeline that runs discovery, planning, and scope validation in sequence.
- **aet-validate-scope** — Stress-test plans against the existing domain model, terminology, and documented decisions.

### Execution Skills

Run plans with isolation, quality gates, and traceability.

- **aet-work** — Work queue management and sequential or parallel task execution. Spawns isolated sessions per task in git worktrees, with curated sprint intake, evidence-gated completion, live-run visibility in the panel, usage-cost telemetry, a git-refs task store that travels with the repository, detached-only run invocation with bounded completion reports, hybrid liveness supervision that lets a quiet-but-working session keep running, night-shift runtime resilience, configurable branch models including single-PR integration mode, shadow posture for projects that keep their board entirely local, multi-machine state sync via `refs/aet/*`, run-scoped handoff note injection, portable plan specs carried in the task record, recovery of missing stage verdicts without re-running the whole stage, one integration branch per PRD so concurrent epics never share a pull request, plan-quality validation at every entry to the board rather than only at `aet sprint add`, a single admission policy shared by every route onto the board, correction of a queued plan by editing the file and re-adding it, a run that stops and asks to be resumed when it meets a provider rate limit instead of retrying into the same wall, an epic declared once in the queue envelope rather than inferred on every invocation, preflight checks that refuse in the foreground before a run detaches, and a liveness check that reads process start time so a recycled process id is never reported as an active run.
- **aet-implement** — Fresh-session implementation from an approved `plan.md`. The tests it runs are chosen from what the change actually touches, derived from the code rather than a list somebody has to keep up to date, and it falls back to the whole suite whenever the change cannot be narrowed safely.
- **aet-tdd** — Test-driven development with red-green-refactor loops and vertical tracer bullets.

### Quality and Security Skills

Verify code before it ships.

- **aet-review** — Staff-level code review with multi-lens checks, supported by mechanical identity-conflation and boundary-contract lenses at `aet gate submit --stage review`.
- **aet-cso** — Diff-focused security audit. Verdicts are submitted via `aet gate submit` with built-in evidence builders.
- **aet-qa** — Automated QA with tiered validation. Runs the full suite unconditionally, and when it fails, compares the failures against the targeted set implement already ran so a gap in coverage is named rather than guessed at. Verdicts are submitted via `aet gate submit` with built-in pytest, summary, and divergence builders.
- **aet-verify** — Conditional live verification with evidence capture. Submits the `verify` verdict that the pre-merge gate reads, so a critical task cannot reach trunk without live verification having run.

### Shipping and Release Skills

Land code cleanly and document releases.

- **aet-ship** — Pre-merge validation, PR creation, merge verification, direct merge via `aet ship merge`, provider-specific merge-guard harness detection, squash-merge verification fallback, stacked PR split and trunk substitution, and optional branch deletion on close. Resolves a task id against the record across open, gate, close, merge, split, and verify; plan paths are no longer accepted. Which verdict a stage must show is read from the workflow definition rather than kept as a separate list, and a gate's default routing derives from the plan's work class. `aet ship open-epic` runs the gate and opens the pull request for an epic branch. The gate, the conflict detection and the commit count all run against the branch being merged rather than against whichever branch the checkout happens to be on.
- **aet-release-prep** — Release preparation: commit analysis, changelog updates, and version bump suggestions.
- **aet-sync-docs** — Sync the PRD to reflect what was actually built.

### Maintenance Skills

Keep projects and the toolkit itself healthy.

- **aet-setup** — Bootstrap or upgrade projects with best-practice documentation, AI guardrails, optional pre-push hook gates, and `aet setup verify` / `aet setup bootstrap` helpers for trunk resolution and required `.gitignore` entries. `verify` reports both directions of drift after an upgrade: an entry the toolkit needs that the file is missing, and an entry naming a file the toolkit no longer writes. It also prints the active epic declaration beside the resolved trunk and integration branch.
- **aet-upgrade** — Dependency and framework upgrade planning with breaking-change analysis.
- **aet-bug-report** — Structured bug investigation and fixing.
- **aet-evolve** — System evolution through retrospectives and rule updates. Mines telemetry archives and narrative reports for cross-project patterns, and includes `aet-retro` for automated post-run review.

### Context and Memory Commands

Carry context and lessons across runs.

- **aet context** — Loads git state, filesystem facts, canonical plan stages, budgets, rules digest, and durable insights into a structured payload for agent session start. Supports `--memories-only`, `--hook-json` SessionStart envelopes, and `PRIME.md` override.
- **aet learnings append** — Records append-only JSONL learnings with schema validation.
- **aet handoff** — Writes and reads run-scoped handoff notes so agents can pass context between sessions.
- **aet sprint intake** — Reads `aet:sprint` issues from GitHub, checks each candidate against the dependency graph, and admits it or refuses with the blocking reason named.
- **aet state reconcile** — Reports and clears refs stranded on a clone, so a board that drifted can be brought back in line without hand-editing refs.
- **aet epic** — Declares the active epic, shows it, and clears it. The declaration holds the integration branch, the pull request title, and a body file, so an epic pull request has somewhere to live before it ships.
- **aet breaker** — Shows the tracked failure signatures behind the circuit breaker and resets it. Clearing a tripped breaker no longer needs a low-level git ref command.
- **aet docs lint** — Checks a fact a document copies from the tree against the tree itself: a retired data path, an architecture-decision relation, or a code symbol an anchor names. A deliberate divergence is declared with an escape marker rather than left to decay.
- **aet state audit** — Reconciles stored task state against git and names any task record carrying no plan spec.

---

## Integrations

| Name                  | Description                                                                                                                          |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `make install-skills` | Symlinks all skills to `~/.agents/skills/` for local agent use.                                                                      |
| Agent CLIs            | Claude Code, Kimi, and Antigravity (`agy`) all drive the pipeline. The toolkit reads each one's session logs and usage figures, so runs are comparable whichever you use; for Antigravity, model and reasoning effort are selectable per session. |
| `aet` binary          | A single multicall binary that dispatches to every toolkit subcommand; `aet setup link` installs the console script on `PATH`. |
| `aet context`         | Session-start context loader that surfaces git state, plan stages, budgets, rules digest, and recent learnings. |
| `aet size` commands   | Report and backfill delivered diff-size measurements for closed plans to calibrate sizing estimates. |
| Telemetry panel       | A local, stdlib-launched viewer for the telemetry archive, with a Plans lens for browsing plans, pipeline progress, run history, test-run provenance badges, and session-log traceability. |
| GitHub Issues         | One-way projection of the board, plus `aet sprint intake` for reading `aet:sprint` issues as declared intent. Not a task store.       |
| git-refs backend      | The task store. Queue state lives in tracked git refs and travels with the repository; in shadow posture it stays entirely local and is never pushed.              |
| Git                   | All skills use git commands for branch, worktree, and merge operations; no agent-specific APIs required.                             |

---

## What's New

### What's New in v1.14.0

- **An epic is declared once instead of repeated on every run** — `aet epic set` records the integration branch, the pull request title, and a body file. Runs read the declaration, and each task is stamped with the branch it belongs to. A task that would integrate somewhere else halts and names the mismatch. `aet ship open-epic` opens the epic pull request without repeating any flag.
- **A run that cannot start says so** — the circuit breaker, the queue, the agent binary, and the worktree base are all checked before the run detaches. A failed check prints the reason and exits non-zero. Previously the command announced a started run and returned success while the background process gave up.
- **A blocked orchestrator is visible** — `aet status` shows a banner when the circuit breaker is tripped, and names a previous run that ended in failure. Status used to report tasks as ready and no failures while the orchestrator was hard-blocked. `aet breaker show` and `aet breaker reset` inspect and clear the breaker.
- **Checks read evidence instead of a cheap stand-in** — a finished run whose process id was reused is no longer reported as active. A branch that was created and never touched no longer counts as work in progress. Ship gates the branch it is about to merge, not whichever branch the checkout is on. A verdict carrying a placeholder summary no longer satisfies a stage.
- **Documents are checked against the code they describe** — a retired data path in skill prose, a broken relation between architecture decisions, and a code anchor whose symbol no longer exists are all caught by `aet docs lint`. A divergence that is deliberate is declared in the document rather than silently tolerated.
- **Draft plans stay out of the working tree** — plans in progress live in an ignored directory and settled plans are archived in git. A machine that never held the plan file can still close the task, so distributed execution no longer trips on a missing document.
- **The agent CLI that started the run drives the work** — a Claude Code session could previously dispatch its tasks to whichever other agent CLI happened to be installed. The calling agent is now detected from the running process, and a run started outside a recognised agent asks for the binary rather than guessing.
- **Git no longer hangs on a key it cannot unlock** — a repository whose remote needs an SSH key that is not loaded used to stall for minutes with nobody able to answer the prompt. It now fails in seconds and says why. A deploy key configured for a CI runner is left untouched.

**Upgrading from 1.13.x:** upgrade the skills alongside the CLI. Move draft plans into `docs/plans/active/`; `aet setup bootstrap` adds the ignore entry and the old flat path still resolves, so nothing has to move at once. `aet docs lint` gains three rules, one of which runs at error severity, so a repository whose architecture-decision records lack frontmatter will fail the lint until they carry it. Adapter selection no longer falls back to whatever is on `PATH`, so a run started outside a recognised agent CLI needs `--cli-bin` or `AET_CLI_BIN`. Declaring an epic is optional and existing configuration still works.

### What's New in v1.13.0

- **A queued plan can be corrected by editing it** — when a plan waiting on the board is invalidated by another task merging ahead of it, fixing it means editing the file and adding it again. Correcting one previously required deleting state on the shared remote that every other clone reads.
- **A runaway loop stops itself** — a task that kept relaunching against a closed provider rate limit, 22 times in the case that prompted this, is now halted by the run. The limit is recognised from the wording providers actually use, and the counters that decide when to stop survive the state being refreshed.
- **An interrupted stage keeps the work it finished** — when a session running several stages dies partway, the stages it completed and proved are kept, so the retry resumes rather than re-running finished work against a plan that no longer matches its own worktree.
- **Live verification is enforceable again** — the pre-merge gate reads the verdict the verify step writes, instead of a file nothing produced. Critical work can no longer reach trunk with the verification stage skipped.
- **Every route onto the board checks a plan the same way** — adding by hand, arriving from a GitHub issue, or going through the backlog all apply one admission policy.
- **What a task actually changed is recorded when it closes** — the difference between the plan and what landed is captured at closure rather than depending on a later documentation step.
- **Installing skills over an older install actually updates them** — linking skills now checks where each existing link points and repoints a stale one, instead of reporting success and leaving it. `aet setup verify` names any skill still loading from another checkout, so a fix that has not reached your sessions is visible rather than silent.
- **Shipping works on a project with no remote** — the pre-merge gate no longer requires an `origin` to fetch from, so a local-only repository can use the whole `aet ship` family.

**Upgrading from 1.12.x:** upgrade the skills alongside the CLI. The pre-merge gate now requires the verify verdict, and the skill that writes it gained that step in this release, so a CLI running ahead of skills from 1.12 or earlier can stop work at ship. `npx skills add ... --all` brings them level. Work already on the board is unaffected.

### What's New in v1.12.0

- **Antigravity joins the supported agent CLIs** — runs can be driven by `agy` alongside Claude Code and Kimi, producing the same telemetry, usage figures, and session traceability whichever you use. Model and reasoning effort are selectable per session.
- **A run driven by Antigravity no longer stops after five minutes** — the CLI's own five-minute deadline was cutting every stage short well inside the toolkit's own supervision window. Stages now run to the toolkit's ceiling, and output streams as the work happens, so a session that is interrupted leaves its progress behind instead of returning nothing.
- **Reports show real numbers again** — an archive-wide report reads the run summary it had been skipping, so tasks, cost, and wall-clock time are no longer reported as zero for runs that plainly happened.
- **Finished tasks clean up after themselves** — a task's worktree is removed once its work is committed, rather than being left behind by every task that did anything. Uncommitted work still stops removal and is named.
- **Both doors onto the board check a plan the same way** — a plan arriving from a GitHub issue is validated exactly as one added by hand, so which route a plan took no longer decides whether it was checked.
- **A refusal you cannot satisfy now explains itself** — when a plan cites a requirement it is itself introducing, the refusal says the check compares against requirements that already exist and points at the line that records your judgement, instead of reporting the requirement as unknown.

**Upgrading from 1.11.x:** `aet sprint intake` now refuses a plan that fails validation rather than admitting it; plans already on the board are unaffected. Antigravity sessions pick up the longer deadline and streamed output automatically.

### What's New in v1.11.0

- **A plan cannot slip onto the board unchecked** — `aet run-one` applies the same plan-quality validation `aet sprint add` does, so the two doors onto the board agree. When you need to run a plan anyway, `--skip-intake` does it and records that the task did not pass.
- **A rate limit stops the run instead of burning the queue** — hitting a provider quota or session limit now pauses the shift and puts the task back in the queue, rather than retrying into the same closed window and eventually setting the task aside as broken.
- **Plan validation stops asking for work already done** — requirement coverage counts what previous plans for the same PRD delivered, so a plan that legitimately covers part of a PRD is no longer flagged for the rest.
- **Validation results say what they checked** — every run names how many plans it looked at and what it judged coverage against, so a one-file check can no longer be mistaken for a full one.
- **One pull request per epic, even with several in flight** — in single-PR mode the integration branch comes from the PRD a task belongs to, so concurrent epics each carry their own branch and review.
- **Tests chosen from the change, not from a list** — the targeted tests a stage runs are derived from the code itself, so new code is covered the day it arrives instead of the day someone remembers to register it.
- **Clearer refusals** — a config left over from an earlier version now names the migration instead of printing a stack trace, and a rejected plan shows the exact line that overrides a check you have judged not to apply.

**Upgrading from 1.10.x:** `aet run-one` now refuses a plan that fails intake validation; pass `--skip-intake` to run it anyway. A run that meets a provider rate limit stops spawning even under `--on-failure continue`.

### What's New in v1.10.0

- **`aet --help` answers in one hop** — every command appears in a single sectioned index with its required arguments inline, and a mistyped command now suggests the right one and shows a runnable example.
- **Quiet sessions are no longer killed** — supervision watches the process tree and run log instead of stdout silence, so a long-running agent that has stopped printing keeps working.
- **Faster implement, stricter QA** — implement runs a targeted test set chosen from the changed paths, QA always runs the full suite, and a QA failure outside the targeted set is reported as a coverage gap.
- **Your board can stay entirely local** — a project with no committed AET config keeps its queue on the machine, pushes nothing, and says so once per run.
- **Sprint intake from GitHub** — label issues `aet:sprint` and `aet sprint intake` admits the ones whose dependencies allow it, naming the blocker for the ones it refuses.
- **Completed work stays completed across clones** — sealing a task leaves a durable marker, so a finished task can no longer reappear as live work on another machine.
- **Merges must show evidence** — a branch is recorded as merged only when there is a recorded merge commit or real movement past its base, closing a path where an untouched branch could be sealed as merged.

**Upgrading from 1.9.x:** the JSON task backend, `aet init-queue`, and the `docs/plans/archive/` directory are removed, and `aet ship` takes task ids rather than plan paths. A leftover `task_backend` config key is rejected with a migration message.

### What's New in v1.9.0

- **Plans travel with the task record** — start a task on one machine and the full plan spec reaches the worktree on another, without committing live plan files.
- **git-refs backend is tracked** — queue state lives in `refs/aet/*` by default and moves with the repository, so multi-machine handoffs no longer depend on a gitignored local file.
- **Sealed tasks stay sealed across clones** — terminal closure now pushes ref deletions to origin, preventing completed tasks from reappearing as live work.
- **Missing verdict recovery** — if a stage finishes but its verdict file is lost, the orchestrator runs a narrow recovery session instead of replaying the entire stage.
- **Cleaner Claude telemetry** — session logs from Claude Code now produce accurate test-run records, including piped commands and real transcript shapes.
- **Safer ledger** — the provenance ledger verifies every line on load and appends instead of rewriting, so a bad line cannot truncate the store.

### What's New in v1.8.0

- **New context commands** — `aet context` loads project state for session start, `aet learnings append` records lessons, and `aet handoff` passes notes between runs.
- **Mechanical review lenses** — identity-conflation and boundary-contract lenses catch mixed namespaces and boundary violations when you run `aet gate submit --stage review`.
- **More reliable shipping** — mechanical closure transaction, stacked PR split, squash-merge verification fallback, and `--delete-branch` on close.
- **Multi-machine state sync** — `refs/aet/*` push/fetch keeps queue state and verdicts in sync across clones without leaking local `~/.aet` files.
- **Generated CLI reference** — `aet docs generate` keeps `docs/CLI.md` current and machine-independent.
- **Cleaner plan lifecycle** — live plans are transient working copies and are archived to `docs/plans/archive/` at terminal closure; frontmatter `status` is no longer authoritative.
- **Atomic stage gates** — `aet state set-stage` and `aet gate submit` update the plan footer and ledger together, removing hand-built verdict JSON.

### What's New in v1.7.0

- **Local-only plans** — queue and run `docs/plans/*.md` files that exist only on your machine; the plan lands in its task branch's PR diff and terminal status is still written durably at closure.
- **Plan overlay snapshots** — the orchestrator always works from the latest local plan text in the worktree, so mid-sprint edits take effect without a separate publish step.
- **Focused PR diffs** — each task branch is seeded with only its own plan file, keeping implementation PRs free of unrelated planning documents.
- **Fail-closed closure** — `aet ship close` now refuses loudly when a plan file cannot be resolved instead of recording a merge silently.

### What's New in v1.6.0

- **Deterministic detached execution** — `aet run` and `aet run-one` now always execute detached with sensible internal defaults and return a bounded completion report instead of streaming logs.
- **Per-adapter supervision defaults** — stall and wall timeouts resolve from the active `CLIAdapter` instead of manual CLI flags.
- **Test-run provenance in telemetry** — the panel and desk distinguish observed wire captures from claimed verdicts, so aggregates no longer silently blend the two populations.
- **Adapter-dispatched session-log readers** — telemetry reads both Kimi wire logs and Claude Code transcripts through a shared dispatch seam.
- **Traceable stage records** — every stage record carries a `session_identifier` resolved by the adapter, linking it back to the session log that produced it.
- **Observable targeted validation scope** — `make validate` emits a machine-readable marker and the orchestrator classifies test runs as `full-suite` or `impact` from actual command output.
- **Task sizes in `aet status`** — status shows each task's declared S/M/L size from plan frontmatter.
- **Guided configuration** — `aet configure --guided` walks through scope and integration mode interactively, with unattended bypasses.

### What's New in v1.5.0

- **Configurable branch model** — `trunk_branch`, `integration_branch`, and `integration_mode` are resolved from config, environment, or CLI instead of hardcoding `main`; `aet setup verify` reports the resolved trunk and its provenance.
- **Single-PR integration mode** — squash multiple task branches into a shared integration branch instead of opening one PR per task, with serialized integration and re-validation after rebase.
- **`aet ship merge` direct merges** — merge a task branch straight into a target branch with pre-merge conflict detection; `--branch` defaults to `main`.
- **Bare task IDs across `aet ship`** — `open`, `gate`, `close`, and `merge` accept a bare task id and resolve it to the conventional plan path.
- **Delivered-size calibration** — `aet size report` and `aet size backfill` aggregate diff-size measurements from closed plans to improve future size estimates.
- **Cleaner intake and status UX** — `init-queue` only validates plans actually entering the sprint, and `aet status` summarizes empty sections in compact sentences.

### What's New in v1.2.0

- **Night-shift runtime resilience** — unattended runs now recover from stalls, overloads, and failures with circuit breakers, a stall watchdog, failure-taxonomy routing, and quarantine support.
- **Fail-closed plan intake** — `aet-work` rejects malformed plans at `add`, `init-queue`, and `sync` using the new `aet plan validate` check suite.
- **Optional zero-review auto-merge** — `desk --eligibility` and a track-record policy can let trusted, low-risk tasks merge without manual review; disabled by default.
- **Better ship decisions from `aet desk`** — risk-ranked awaiting-merge view, evidence bundles, and direct merge/abandon actions.
- **Smarter merge guards** — `aet-ship` detects provider-specific merge-guard requirements and adapts behavior accordingly.

### What's New in v1.1.0

- **Live execution panel** — `aet-work status` now shows running tasks with auto-refreshing live-run visibility and a cleaner dependency/blocker table.
- **Usage-cost telemetry** — agent CLI usage and kimi wire files are captured into the telemetry archive, with a cost view in the panel.
- **`aet gate submit` verdict writer** — record skill verdicts directly from the CLI, feeding the orchestrator's evidence-gated completion.
- **git-refs as the default task backend** — queue state now lives in git refs by default, with tamper-evidence and a pre-push hook gate in `aet-setup`.
- **Validation freshness** — verdicts carry a `tree_hash` and freshness query so QA gates can detect stale evidence.
- **Test-run extraction and classification** — wire logs yield structured test-run records classified by verdict scope.
- **Structural pattern mining** — `mine-learnings` and `aet-retro` can surface recurring structural patterns across projects.
- **Faster, slimmer validation** — `pytest-xdist` parallelizes the suite and `aet-setup` drops Prettier from the default scaffold.

### What's New in v1.0.0

- **One `aet` command for the whole toolkit** — a single multicall binary now dispatches to every subcommand, self-installs, and repairs `PATH` on invocation, replacing the many separate legacy binaries.
- **Local telemetry panel with a Plans lens** — browse plans, pipeline progress, consolidated timelines, and run history from a stdlib-launched viewer of the telemetry archive.
- **Curated sprint intake** — `aet-work` sync no longer auto-adds plans; intake parks them as ready or blocked so you decide what enters the queue.
- **More trustworthy unattended runs** — the orchestrator uses locked, atomic queue writes with a tamper-evident guard, requires a structured evidence verdict before completing a task, and shuts down batch children cleanly by process group.
- **git-refs task backend option** — `aet-work` can store queue state in git refs as an alternative to local JSON files or GitHub Issues.
- **Pipelines as data** — pipeline stage sequences are declared in a packaged workflow file and linted by `make validate`, instead of being hardcoded.

### What's New in v0.10.0

- **Automated run review with `aet-retro`** — after every `aet-work run`, `aet-evolve` can surface errors, timeouts, and improvement opportunities from telemetry archives and narrative reports.
- **GitHub Issues as a task backend** — `aet-work` can mirror the queue to GitHub Issues, so task state is visible to the whole team and survives local worktree cleanup.
- **Faster, quieter QA** — `aet-qa` now runs only the tests that touch changed files by default, falling back to the full suite when coverage requires it.
- **More resilient unattended runs** — the orchestrator uses per-task timeouts and inner heartbeats, refreshes worktrees from `origin/main`, and guarantees a final summary even when a task crashes.
- **Cleaner review focus** — `aet-review` filters out project-level noise so reviewers stay focused on the actual diff.

### What's New in v0.9.1

- **Correct installation URLs** — `README.md` now points to the right repository (`https://github.com/thebrightnest/ae-toolkit`), so `npx skills add` commands work out of the box.
- **Clearer setup path** — installation examples use the standard `.agents/skills` directory and show the correct helper-binary setup step.

### What's New in v0.9.0

- **Telemetry that never gets lost** — `aet-work` writes execution logs directly to the user-level archive, so background runs and deleted worktrees no longer lose telemetry before it can be mined.
- **One-click cross-project learning** — `aet-evolve mine-learnings` reads the archive directly without a manual `ingest-telemetry` step.
- **Right-sized isolation per task** — plans can declare `pipeline: minimal|standard|full` so low-risk tasks run faster and high-risk changes keep full stage isolation.
- **Run health at a glance** — every orchestrator run produces a `last-run.json` summary with success/failure counts and total time.

### What's New in v0.8.0

- **Telemetry learning system** — capture richer run data, warm worktree dependencies, reuse isolated stage sessions, scope tests to the diff, and archive findings across projects so the same lesson never has to be relearned.
- **Centralized skill binaries** — `aet-setup` now installs skill executables on `PATH` consistently, starting with telemetry mining tools.
- **Smarter queue intake** — `aet-work` reconciles terminal tasks from history and git automatically, and only validates new plans instead of re-scanning the entire queue.
- **Reliable unattended runs** — orchestrator children skip redundant main-hygiene checks, and merge verification works from recorded merge commits without a local branch.

### What's New in v0.7.0

- **Deterministic work state** — `aet-work` now records state forward through validated transitions, seals completed work to an append-only history log, and never re-derives status from git during normal reads.
- **Validated plan intake** — every plan must declare `id`, `blocked_by`, and `size` in YAML frontmatter; malformed or legacy plans are rejected at intake.
- **Reliable merge recording** — `aet-state record-merge` resolves the real squash-merge SHA automatically, so finished tasks never resurrect as unblocked.
- **Safer single-task runs** — `aet-work run-one` now enforces branch/worktree hygiene, confirms the plan file exists before spawning, and emits telemetry.
- **aet-design-system-creation commands** — new design-system, design-review, and design-check command workflows for design-driven projects.
- **aet-validate-scope closure checks** — planning and validation skills now enforce closure discipline before work proceeds.

### What's New in v0.6.0

- **aet-work** now shows only active tasks in `status` and archives terminal tasks during `cleanup`.
- **Unified orchestrator** cleanup is complete, with `aet-plan` implementation flows routed through `aet-work`.
- **aet-ship** and **aet-work** now guarantee clean PR diffs by branching worktrees from `origin/main`, rebasing independent branches before shipping, detecting stacked branches, and auditing PR scope.
- **Orchestrator reliability fixes** ensure real CLI flags are used, queue metadata is preserved, and untracked plans are copied into worktrees.

---

_This file is maintained by `aet-release-prep`. Do not delete historical "What's New" sections._
