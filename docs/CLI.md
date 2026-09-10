<!-- AUTO-GENERATED: do not edit manually — run `aet docs generate` to refresh. -->

# AE Toolkit CLI Reference

## `aet run`

Run the orchestrator in batch mode.

### Options

- `--follow` *str* — Follow an existing run id.
- `--on-failure` *str* — triage|continue|halt
- `--task-timeout` *int* — Per-task timeout (s).
- `--cli-bin` *str* — Agent CLI binary path. Defaults to the agent CLI that invoked aet; required when no agent CLI is detected.
- `--base` *str* — Override the worktree base branch/ref.
- `--max-jobs` *int* — Max parallel tasks (batch mode). (default: `4`)

## `aet run-one`

Run the orchestrator for a single plan.

### Options

- `plan_file` *str* — Plan file path or task ID to run. (required)
- `--follow` *str* — Follow an existing run id.
- `--on-failure` *str* — triage|continue|halt
- `--task-timeout` *int* — Per-task timeout (s).
- `--cli-bin` *str* — Agent CLI binary path. Defaults to the agent CLI that invoked aet; required when no agent CLI is detected.
- `--base` *str* — Override the worktree base branch/ref.
- `--skip-intake` *boolean* — Run a plan that fails intake validation; the bypass is recorded. (default: `False`)

## `aet state`

Queue mutations and stage transitions.

### Subcommands

- `audit`: Reconcile stored state against git without mutating.
- `backfill-specs`: Backfill the portable plan spec into records that predate R-19.
- `heal`: Reconcile stored state against git and apply safe fixes.
- `reconcile`: Report/remove local refs stranded by the old model. Local-only; never touches origin.
- `record-merge`: Resolve and record the merge commit for a task.
- `reset`: Recompute a task from git and blockers, reset to ready/blocked, clear stale runtime fields.
- `set-stage`: Set the pipeline stage sub-state for an in-progress task.
- `transition`: Validate legality, then apply state change.
- `validate`: Check if a transition is legal.

## `aet state audit`

Reconcile stored state against git without mutating.

### Options

- `queue` *str* — Path to queue anchor. (default: `.agents/aet-queue`)

## `aet state heal`

Reconcile stored state against git and apply safe fixes.

### Options

- `queue` *str* — Path to queue anchor. (default: `.agents/aet-queue`)
- `--apply` *boolean* — Apply proposed changes; otherwise dry-run. (default: `False`)
- `--force` *boolean* — Override a live run lease and mutate the queue anyway (with a warning). (default: `False`)

## `aet state validate`

Check if a transition is legal.

### Options

- `task_id` *str* — Task ID. (required)
- `from_stage` *str* — Current stage. (required)
- `to_stage` *str* — Target stage. (required)
- `queue` *str* — Path to queue anchor. (default: `.agents/aet-queue`)

## `aet state reset`

Recompute a task from git and blockers, reset to ready/blocked, clear stale runtime fields.

### Options

- `task_id` *str* — Task ID. (required)
- `queue` *str* — Path to queue anchor. (default: `.agents/aet-queue`)
- `--apply` *boolean* — Apply the reset; otherwise dry-run. (default: `False`)
- `--force` *boolean* — Override a live run lease and mutate the queue anyway (with a warning). (default: `False`)

## `aet state backfill-specs`

Backfill the portable plan spec into records that predate R-19.

### Options

- `queue` *str* — Path to queue anchor. (default: `.agents/aet-queue`)
- `--rev` *str* — Git revision that still carries the plan files. (default: `b95538dd~1`)
- `--apply` *boolean* — Write the recovered specs; otherwise dry-run. (default: `False`)
- `--force` *boolean* — Override a live run lease and mutate the queue anyway (with a warning). (default: `False`)
- `--history-file` *str* — Backfill settled history JSONL instead of the live queue.

## `aet state transition`

Validate legality, then apply state change.

### Options

- `task_id` *str* — Task ID. (required)
- `from_stage` *str* — Current stage. (required)
- `to_stage` *str* — Target stage. (required)
- `queue` *str* — Path to queue anchor. (default: `.agents/aet-queue`)
- `--reason` *str* — Reason for transition (used as history evidence).
- `--dry-run` *boolean* — Show changes without applying them. (default: `False`)
- `--force` *boolean* — Override a live run lease and mutate the queue anyway (with a warning). (default: `False`)

## `aet state set-stage`

Set the pipeline stage sub-state for an in-progress task.

### Options

- `task_id` *str* — Task ID. (required)
- `stage` *str* — Pipeline stage to record. (required)
- `queue` *str* — Path to queue anchor. (default: `.agents/aet-queue`)
- `--dry-run` *boolean* — Show changes without applying them. (default: `False`)
- `--force` *boolean* — Override a live run lease and mutate the queue anyway (with a warning). (default: `False`)

## `aet state record-merge`

Resolve and record the merge commit for a task.

### Options

- `task_id` *str* — Task ID. (required)
- `queue` *str* — Path to queue anchor. (default: `.agents/aet-queue`)
- `--branch` *str* — Branch name to use for merge verification. Overrides the task's branch field.
- `--merge-commit` *str* — Merge commit SHA to record directly. Must be an ancestor of origin/<target-branch>.
- `--target-branch` *str* — Branch to verify the merge against. Defaults to the configured integration branch.
- `--plan` *str* — Deprecated and ignored: plan footer writes were removed (R-4/R-19).
- `--dry-run` *boolean* — Show changes without applying them. (default: `False`)
- `--force` *boolean* — Override a live run lease and mutate the queue anyway (with a warning). (default: `False`)

## `aet state reconcile`

Report/remove local refs stranded by the old model. Local-only; never touches origin.

### Options

- `queue` *str* — Path to queue anchor. (default: `.agents/aet-queue`)
- `--apply` *boolean* — Remove stranded refs; otherwise dry-run. (default: `False`)
- `--force` *boolean* — Override a live run lease and mutate the queue anyway (with a warning). (default: `False`)

## `aet backlog`

Backlog curation commands.

### Subcommands

- `add`: Add a plan to the backlog.

## `aet backlog add`

Add a plan to the backlog.

### Options

- `target` *str* — Plan file path or task ID to add to the backlog (required)
- `--plans-dir` *str* — Directory containing atomic plan markdown files (default: `docs/plans`)
- `--config` *str* — Path to AET backend configuration (default: `.agents/aet-config.json`)
- `--queue-file` *str* — Path to queue anchor (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to work-history.jsonl (default: `.agents/work-history.jsonl`)

## `aet breaker`

Circuit breaker inspection and reset.

### Subcommands

- `reset`: Reset circuit breaker and clear refs/aet/breaker.
- `show`: Show circuit breaker tracked failure signatures and trip status.

## `aet breaker show`

Show circuit breaker tracked failure signatures and trip status.

### Options

- `--json` *boolean* — Emit machine-readable JSON representation. (default: `False`)
- `--repo-root` *path* — Repository root (defaults to git root or current working directory).

## `aet breaker reset`

Reset circuit breaker and clear refs/aet/breaker.

### Options

- `--force` *boolean* — Reset without interactive confirmation. (default: `False`)
- `--repo-root` *path* — Repository root (defaults to git root or current working directory).

## `aet desk`

Review cockpit for awaiting_merge tasks.

### Options

- `--eligibility` *boolean* — Show per-class clean-merge counts and zero-review eligibility. (default: `False`)
- `--policy` *str* — Path to the zero-review policy JSON. (default: `.agents/review-policy.json`)
- `--queue-file` *str* — Path to queue anchor (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to the settled work-history JSONL (also used for eligibility). (default: `.agents/work-history.jsonl`)
- `--plans-dir` *str* — Directory containing atomic plan markdown files (default: `docs/plans`)
- `--json` *boolean* — Emit a machine-readable JSON projection. (default: `False`)

### Subcommands

- `abandon`: Abandon a task with a recorded reason.
- `merge`: Merge a PR and record the task as merged.

## `aet desk merge`

Merge a PR and record the task as merged.

### Options

- `task_id` *str* — Task ID to merge. (required)
- `--queue-file` *str* — Path to queue anchor (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to the settled work-history JSONL. (default: `.agents/work-history.jsonl`)

## `aet desk abandon`

Abandon a task with a recorded reason.

### Options

- `task_id` *str* — Task ID to abandon. (required)
- `--reason` *str* — Required reason for abandoning the task. (required)
- `--queue-file` *str* — Path to queue anchor (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to the settled work-history JSONL. (default: `.agents/work-history.jsonl`)

## `aet docs`

Documentation linting and syncing.

### Subcommands

- `generate`: Generate the CLI reference markdown file.
- `lint`: Lint documentation against declarative rules.

## `aet docs lint`

Lint documentation against declarative rules.

### Options

- `--rules` *str* — Rules file (default: .agents/doc-rules.yaml under repo root)
- `--repo-root` *str* — Repository root (default: git root or current directory)
- `--severity` *str* — Minimum severity to enforce: 'error' (default) or 'warning'. (default: `error`)

## `aet docs generate`

Generate the CLI reference markdown file.

### Options

- `--output` *path* — Output file path (default: docs/CLI.md under repo root).

## `aet epic`

Active epic declaration and inspection.

### Subcommands

- `clear`: Clear the active epic declaration.
- `set`: Declare the active epic in the queue envelope.
- `show`: Show the active epic declaration.

## `aet epic set`

Declare the active epic in the queue envelope.

### Options

- `branch` *str* — Integration branch for the epic. (required)
- `--title` *str* — Human-readable epic title.
- `--body-file` *str* — Path to markdown body file describing the epic.
- `--create` *boolean* — Declare the epic before creating its branch. (default: `False`)
- `--config` *str* — Path to AET configuration file. (default: `.agents/aet-config.json`)
- `--queue-file` *str* — Path to queue anchor. (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to work history. (default: `.agents/work-history.jsonl`)

## `aet epic show`

Show the active epic declaration.

### Options

- `--config` *str* — Path to AET configuration file. (default: `.agents/aet-config.json`)
- `--queue-file` *str* — Path to queue anchor. (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to work history. (default: `.agents/work-history.jsonl`)

## `aet epic clear`

Clear the active epic declaration.

### Options

- `--config` *str* — Path to AET configuration file. (default: `.agents/aet-config.json`)
- `--queue-file` *str* — Path to queue anchor. (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to work history. (default: `.agents/work-history.jsonl`)

## `aet gate`

Fail-closed verdict writer and review board renderer.

### Subcommands

- `review`: Print a human-readable backlog review grouped by pipeline stage.
- `submit`: Validate and write a stage verdict.

## `aet gate submit`

Validate and write a stage verdict.

When ``--evidence`` is omitted the command builds the verdict payload
from the supplied options. In that mode ``AET_TASK_ID`` must be set.

### Options

- `--stage` *str* — Verdict stage: qa, review, cso, sync-docs, or verify (required)
- `--verdict` *str* — Declared verdict; must match the payload's verdict field (required)
- `--evidence` *str* — Path to the verdict JSON payload file
- `--from-pytest` *str* — Path to a pytest JSON report (qa builder mode)
- `--summary` *str* — One-line verdict summary
- `--divergence` *str* — Divergence item or file path (sync-docs builder mode; repeatable) (default: `[]`)
- `--test-command` *str* — Override the test command recorded in qa verdicts

## `aet gate review`

Print a human-readable backlog review grouped by pipeline stage.

By default the board is read from the active task backend so it works even
when no plan files are present. Pass ``--plans-dir`` to render from plan
files instead.

### Options

- `--plans-dir` *str* — Directory containing atomic plan markdown files (legacy mode)

## `aet handoff`

Run-scoped handoff note commands.

### Subcommands

- `append`: Append one entry to the run's handoff note.
- `show`: Render the run's handoff note as a prompt block.

## `aet handoff append`

Append one entry to the run's handoff note.

### Options

- `--stage` *str* — Stage name recording this entry. (required)
- `--decision` *str* — Repeatable decision taken in this stage. (default: `[]`)
- `--pre-existing-failure` *str* — Repeatable pre-existing failure encountered in this stage. (default: `[]`)
- `--validation-command` *str* — Repeatable validation command run in this stage. (default: `[]`)
- `--evidence-path` *str* — Path to the verdict evidence produced by this stage.
- `--run-id` *str* — Run id (default: $AET_RUN_ID).
- `--repo-root` *str* — Repository root (default: current directory).

## `aet handoff show`

Render the run's handoff note as a prompt block.

### Options

- `--run-id` *str* — Run id (default: $AET_RUN_ID).
- `--repo-root` *str* — Repository root (default: current directory).

## `aet hooks`

Git hook installation and management.

### Subcommands

- `check`: Check gate evidence for pushed refs read from stdin.
- `install`: Generate the self-contained .git/hooks/pre-push shim.

## `aet hooks install`

Generate the self-contained .git/hooks/pre-push shim.

### Options

- `--repo` *str* — Repo root (default: current git toplevel).

## `aet hooks check`

Check gate evidence for pushed refs read from stdin.

### Options

- `--repo` *str* — Repo root (default: current git toplevel).

## `aet learnings`

Append-only learning journal commands.

### Subcommands

- `append`: Append one canonical learning entry to ``.agents/learnings.jsonl``.

## `aet learnings append`

Append one canonical learning entry to ``.agents/learnings.jsonl``.

### Options

- `--problem` *str* — What went wrong or what was misunderstood. (required)
- `--layer` *str* — The layer (file, command, skill, etc.) where the issue lives. (required)
- `--fix` *str* — The concrete change that prevents recurrence. (required)
- `--prevents` *str* — The failure this learning prevents. (required)
- `--trigger` *str* — Keyword trigger(s) for retrieval (repeatable). (default: `[]`)
- `--recurrence` *int* — How many times this issue has recurred (positive integer).
- `--file` *path* — Path to the learnings JSONL file. (default: `.agents/learnings.jsonl`)

## `aet plan`

Plan-quality commands.

### Subcommands

- `validate`: Validate plan files for intake quality.

## `aet plan validate`

Validate plan files for intake quality.

### Options

- `plans` *str* — Plan files or directories to validate (default: docs/plans/*.md)

## `aet plans`

Bulk plan operations and corpus linting.

### Subcommands

- `lint`: Lint the docs/plans corpus for settled/live misclassification.

## `aet plans lint`

Lint the docs/plans corpus for settled/live misclassification.

### Options

- `--plans-dir` *str* — Plans directory to lint (default: docs/plans under repo root)

## `aet queue`

Work queue sync and related operations.

### Subcommands

- `sync`: Reconcile the existing work queue (never scans docs/plans).

## `aet queue sync`

Reconcile the existing work queue (never scans docs/plans).

### Options

- `--queue-file` *str* — Path to queue anchor (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to work-history.jsonl (default: `.agents/work-history.jsonl`)
- `--plans-dir` *str* — Deprecated and ignored: sync no longer scans the plans directory. (default: `docs/plans`)
- `--config` *str* — Path to AET queue backend configuration (default: `.agents/aet-config.json`)
- `--force` *boolean* — Override a live run lease and mutate the queue anyway (with a warning). (default: `False`)

## `aet setup`

Setup and bootstrap commands.

### Subcommands

- `bootstrap`: Write AET ignore entries to the project ``.gitignore``.
- `link`: Link ``aet`` into the bin dir.
- `skills`: Symlink AE Toolkit skills into agent skills directories.
- `verify`: Verify that the installed `aet` on PATH matches the expected link.

## `aet setup link`

Link ``aet`` into the bin dir.

### Options

- `--bin-dir` *str* — Target bin directory.
- `--dry-run` *boolean* — Print actions without executing. (default: `False`)

## `aet setup skills`

Symlink AE Toolkit skills into agent skills directories.

### Options

- `--skills-dir` *str* — Target skills directory.
- `--agent` *str* — Target agent: claude-code, kimi, cursor, generic.
- `--dry-run` *boolean* — Print actions without executing. (default: `False`)
- `--force` *boolean* — Replace non-symlink collisions with symlinks. (default: `False`)

## `aet setup verify`

Verify that the installed `aet` on PATH matches the expected link.

Resolves what `aet` actually runs on PATH and reports when it is not the
copy just installed. Also prints the resolved trunk branch and how it was
derived (config, detected from ``refs/remotes/origin/HEAD``, or fallback
to ``main``). Read-only: never edits PATH, shell profiles, or the link
itself. Exits 0 even when shadowed — the install succeeded, but the user
will experience a different copy.

### Options

- `--bin-dir` *str* — Target bin directory.
- `--dry-run` *boolean* — Print actions without executing. (default: `False`)

## `aet setup bootstrap`

Write AET ignore entries to the project ``.gitignore``.

### Options

- `--path` *str* — Project root to write .gitignore into (default: current directory).

## `aet ship`

Pre-merge gate, PR creation, and post-merge closure.

### Subcommands

- `close`: Record post-merge closure for a task.
- `default`: Run the gate and, if it passes, open a PR (default behavior).
- `gate`: Run the pre-merge validation gate.
- `merge`: Run the gate, detect conflicts, merge directly into a target branch, and close.
- `open`: Run the gate and open a PR for the plan.
- `open-epic`: Run the gate and open a PR for an epic branch.
- `record-merge`: Hidden alias for close.
- `split`: Split the PR range into caller-supplied commit groups.
- `verify`: Verify a branch has merged without mutating state.

## `aet ship default`

Run the gate and, if it passes, open a PR (default behavior).

### Options

- `plan` *str* — Task id of the plan to ship (use `aet sprint add` to intake a plan). (required)
- `--base` *str* — Override the PR base branch/ref (default: resolved trunk or stacked parent).
- `--dry-run` *boolean* — Show what would be done without making changes. (default: `False`)

## `aet ship gate`

Run the pre-merge validation gate.

### Options

- `plan` *str* — Task id of the plan to ship (use `aet sprint add` to intake a plan). (required)
- `--base` *str* — Override the PR base branch/ref (default: resolved trunk or stacked parent).
- `--dry-run` *boolean* — Show what would be done without making changes. (default: `False`)

## `aet ship open`

Run the gate and open a PR for the plan.

### Options

- `plan` *str* — Task id of the plan to ship (use `aet sprint add` to intake a plan). (required)
- `--base` *str* — Override the PR base branch/ref (default: resolved trunk or stacked parent).
- `--dry-run` *boolean* — Show what would be done without making changes. (default: `False`)

## `aet ship open-epic`

Run the gate and open a PR for an epic branch.

### Options

- `branch` *str* — Integration branch to open PR for (default: active epic declaration).
- `--base` *str* — Override the PR base branch/ref (default: resolved trunk).
- `--dry-run` *boolean* — Show what would be done without making changes. (default: `False`)

## `aet ship merge`

Run the gate, detect conflicts, merge directly into a target branch, and close.

### Options

- `plan` *str* — Task id of the plan to ship (use `aet sprint add` to intake a plan). (required)
- `--branch` *str* — Target branch to merge into (default: resolved trunk branch).
- `--dry-run` *boolean* — Show what would be done without making changes. (default: `False`)

## `aet ship split`

Split the PR range into caller-supplied commit groups.

### Options

- `plan` *str* — Task id of the plan to ship (use `aet sprint add` to intake a plan). (required)
- `--base` *str* — Override the PR base branch/ref (default: resolved trunk or stacked parent).
- `--message` *str* — Commit message for one group. Repeat for each group.
- `--paths` *str* — Comma-separated paths for one group. Repeat for each group, after its --message.
- `--dry-run` *boolean* — Show what would be done without making changes. (default: `False`)

## `aet ship verify`

Verify a branch has merged without mutating state.

### Options

- `task_id` *str* — Task ID to verify. (required)
- `plan_or_queue` *str* — Plan path (when first arg is a task ID) or queue path (when first arg is a plan).
- `queue` *str* — Path to the queue anchor. (default: `.agents/aet-queue`)
- `--squash-fallback` *boolean* — Enable diff-based squash-merge fallback when ancestry and gh fail. (default: `False`)
- `--branch` *str* — Branch name to verify. Overrides the task's branch field.
- `--target-branch` *str* — Target branch to verify the merge against (default: configured integration branch).

## `aet ship close`

Record post-merge closure for a task.

### Options

- `task_id` *str* — Task ID to close (use `aet sprint add` to intake a plan). (required)
- `plan` *str* — Deprecated and ignored: plan paths are no longer accepted (R-3).
- `queue` *str* — Path to the queue anchor. (default: `.agents/aet-queue`)
- `--branch` *str* — Branch name to use for merge verification. Overrides the task's branch field.
- `--merge-commit` *str* — Merge commit SHA to record directly. Must be an ancestor of the resolved trunk branch.
- `--target-branch` *str* — Target branch the source branch merged into (default: configured integration branch). Use 'main' when closing an epic whose integration branch merged to trunk.
- `--dry-run` *boolean* — Show what would be done without making changes. (default: `False`)
- `--delete-branch` *boolean* — After successful closure, delete the remote and local feature branch. (default: `False`)

## `aet ship record-merge`

Hidden alias for close.

### Options

- `task_id` *str* — Task ID to close (use `aet sprint add` to intake a plan). (required)
- `plan` *str* — Deprecated and ignored: plan paths are no longer accepted (R-3).
- `queue` *str* — Path to the queue anchor. (default: `.agents/aet-queue`)
- `--branch` *str* — Branch name to use for merge verification. Overrides the task's branch field.
- `--merge-commit` *str* — Merge commit SHA to record directly. Must be an ancestor of the resolved trunk branch.
- `--target-branch` *str* — Target branch the source branch merged into (default: configured integration branch). Use 'main' when closing an epic whose integration branch merged to trunk.
- `--dry-run` *boolean* — Show what would be done without making changes. (default: `False`)
- `--delete-branch` *boolean* — After successful closure, delete the remote and local feature branch. (default: `False`)

## `aet size`

Delivered-size measurement and reporting.

### Subcommands

- `backfill`: Backfill delivered_size for settled history records.
- `report`: Report delivered size by declared S/M/L label.

## `aet size report`

Report delivered size by declared S/M/L label.

### Options

- `--history-file` *str* — Path to work-history.jsonl (default: `.agents/work-history.jsonl`)
- `--since` *str* — Only include tasks settled on or after this date (YYYY-MM-DD)
- `--json` *boolean* — Print the machine-readable projection instead of the human report (default: `False`)

## `aet size backfill`

Backfill delivered_size for settled history records.

### Options

- `--history-file` *str* — Path to work-history.jsonl (default: `.agents/work-history.jsonl`)
- `--repo-root` *str* — Repository root for resolving plan files and merge commits (default: `.`)
- `--json` *boolean* — Print the machine-readable result instead of the human summary (default: `False`)
- `--min-yield` *int* — Minimum number of newly measured records required for success

## `aet sprint`

Sprint queue management.

### Subcommands

- `add`: Promote an approved plan into the sprint.
- `intake`: Read aet:sprint issues from GitHub and admit valid candidates.

## `aet sprint add`

Promote an approved plan into the sprint.

### Options

- `target` *str* — Plan file path or task ID to promote (required)
- `--queue-file` *str* — Path to queue anchor (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to work-history.jsonl (default: `.agents/work-history.jsonl`)
- `--plans-dir` *str* — Directory containing atomic plan markdown files (default: `docs/plans`)
- `--config` *str* — Path to AET backend configuration (default: `.agents/aet-config.json`)
- `--force` *boolean* — Override a live run lease and mutate the queue anyway (with a warning). (default: `False`)

## `aet sprint intake`

Read aet:sprint issues from GitHub and admit valid candidates.

### Options

- `--queue-file` *str* — Path to aet-queue (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to work-history.jsonl (default: `.agents/work-history.jsonl`)
- `--plans-dir` *str* — Directory containing atomic plan markdown files (default: `docs/plans`)
- `--config` *str* — Path to AET backend configuration (default: `.agents/aet-config.json`)
- `--force` *boolean* — Override a live run lease and mutate the queue anyway (with a warning). (default: `False`)

## `aet configure`

Configure the AET project config.

### Options

- `--trunk-branch` *str* — Set the trunk branch name.
- `--integration-mode` *str* — Set the integration mode.
- `--integration-branch` *str* — Set the integration branch name.
- `--scope` *str* — Write to project config or user config (default: project if in-tree config exists).
- `--non-interactive` *boolean* — Fail if a required value is missing instead of prompting. (default: `False`)
- `--migrate` *boolean* — Rename legacy .agents/aet-work.json to .agents/aet-config.json. (default: `False`)
- `--guided` *boolean* — Run the two-question guided setup flow (scope + integration mode). (default: `False`)
- `--shared` *boolean* — Declare this project shared across devices (writes .agents/aet-config.json). (default: `False`)

## `aet context`

Emit session workflow context as JSON plus a stage banner.

### Options

- `target` *str* — Optional ticket number, task id, or plan path to pin active_plan.
- `--json` *boolean* — Emit the JSON battery only. (default: `False`)
- `--budget` *str* — Rendering budget: auto, cli, or mcp.
- `--max-lines` *int* — Cap the number of rendered lines (human/hook modes).
- `--memories-only` *boolean* — Emit only the stage line and compact learnings. (default: `False`)
- `--hook-json` *str* — Wrap output in a SessionStart envelope for the named harness.

## `aet harness-guard`

### Subcommands

- `check`: Report which merge guard is installed for the detected harness.
- `install`: Detect the harness and generate the matching merge guard.

## `aet harness-guard install`

Detect the harness and generate the matching merge guard.

## `aet harness-guard check`

Report which merge guard is installed for the detected harness.

## `aet metrics`

Report cross-task metrics over settled history.

### Options

- `--history-file` *str* — Path to work-history.jsonl (default: `.agents/work-history.jsonl`)
- `--since` *str* — Only include tasks settled on or after this date (YYYY-MM-DD)
- `--json` *boolean* — Print the machine-readable projection instead of the human report (default: `False`)

## `aet mine-learnings`

Scan archived telemetry for recurring patterns.

### Options

- `--archive-dir` *path* — Telemetry archive root.
- `--propose` *boolean* — Print suggested skill edits (never writes files). (default: `False`)

## `aet next`

Pick the next ready task.

### Options

- `--queue-file` *str* — Path to queue anchor (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to work-history.jsonl (default: `.agents/work-history.jsonl`)
- `--plans-dir` *path* — Directory containing atomic plan markdown files (default: `docs/plans`)

## `aet panel`

Launch the AET panel server.

## `aet reconcile`

Reconcile live plans with their GitHub issue mirrors.

### Options

- `--apply` *boolean* — Apply corrective writes (default is a dry run) (default: `False`)
- `--config` *str* — Path to AET backend configuration (default: `.agents/aet-config.json`)
- `--plans-dir` *path* — Directory containing atomic plan markdown files (default: `docs/plans`)
- `--queue-file` *str* — Path to queue anchor (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to work-history.jsonl (default: `.agents/work-history.jsonl`)
- `--json` *boolean* — Emit the raw reconcile report as JSON (default: `False`)

## `aet release-prep`

Analyze commits since the last tag and suggest a version bump.

### Options

- `--repo-root` *path* — Repository root (default: current working directory).

## `aet report`

Print execution telemetry summary.

### Options

- `--project` *str* — Project slug (defaults to the current repository)
- `--run-dir` *str* — Path to a specific run directory in the archive
- `--task-log` *str* — Path to a single task JSONL file
- `--since` *str* — Only include records at or after this ISO-8601 timestamp
- `--prune` *int* — Prune telemetry runs older than DAYS (dry run unless --force)
- `--force` *boolean* — Actually delete prune candidates (default is a dry run) (default: `False`)

## `aet performance-report`

Cost, tokens and stage time per PRD for the current project.

### Options

- `--project` *str* — Archive project directory (defaults to the current repository)
- `--worktree` *str* — Limit to one worktree label (default: every worktree of the project)
- `--prds` *path* — PRD directory (default: docs/prds under the repository root)
- `--since` *str* — Only include stages starting at or after this ISO-8601 timestamp
- `--out` *path* — Write markdown here instead of stdout
- `--json` *path* — Write the full JSON payload here

## `aet retro`

Generate a retro from AET telemetry, split by project-level and AET-level fixes.

### Options

- `--archive-dir` *path* — Telemetry archive root (default: ~/.aet/telemetry). (default: `~/.aet/telemetry`)
- `--project-slug` *str* — Project slug in the telemetry archive (default: writer-derived <dir>/<label>).
- `--lookback-days` *int* — How many days of telemetry to read for the current project (default: 7). (default: `7`)
- `--output` *path* — Retro output path (default: docs/retros/YYYY-MM-DD-aet-retro.md).
- `--no-mine` *boolean* — Skip mine-learnings and only use the current project's recent telemetry. (default: `False`)

## `aet status`

Show work queue status, active detached runs, systemic circuit breaker
warnings, and last-run telemetry diagnostics.

### Options

- `--queue-file` *str* — Path to queue anchor (default: `.agents/aet-queue`)
- `--history-file` *str* — Path to work-history.jsonl (default: `.agents/work-history.jsonl`)
- `--plans-dir` *path* — Directory containing atomic plan markdown files (default: `docs/plans`)
- `--json` *boolean* — Print a machine-readable JSON projection instead of the human report (default: `False`)

## `aet validate-workflows`

Lint workflow-as-data files.

### Options

- `--repo-root` *str* — Repository root used for skill resolution (default: cwd) (default: `.`)
