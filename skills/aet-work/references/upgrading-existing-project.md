# Upgrading an Existing AET Project to the Forward-Only State Model

## When to read this

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy files and schemas in upgrade guide -->
You have an existing project that uses the AE Toolkit (aet-work) and its work queue is still on the old model:

- `tasks[].status` is the only field.
- `merge_verified` or `done` appear as terminal statuses.
- The queue contains many already-finished tasks.
- `docs/plans/*.md` files lack YAML frontmatter (`id`, `blocked_by`, `size`).
- `.agents/work-archive.json` is still the record of completed work.

This guide brings the project onto the FODS state model (`state`, `history[]`, live/settled partition) without breaking the queue.
<!-- aet-lint: on -->

## Goal of backward compatibility

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy storage files in backward compatibility section -->
New AET scripts should **ignore old formats safely**:

- Old human-readable plan sections (`## Dependencies`, `## Blocked by`) are not parsed as machine truth.
- Old storage files (`.agents/work-archive.json`, `scripts/.aet-work-orchestrator.log`) are not read by `sync` or the orchestrator.
- Legacy statuses (`done`, `merge_verified`) are normalized to canonical terminal states during intake.
- Already-settled records are dropped from the board by `sync` (see known issue below).

The boundary is the **validated frontmatter contract**. Anything outside that contract is either human prose or legacy data and must not affect scheduling.
<!-- aet-lint: on -->

## One-time upgrade procedure

### 1. Install the latest AET skills

Update the skills in `~/.agents/skills/` (or wherever they are installed). For this repo that is done with:

```bash
make install-skills
```

For other projects, copy or symlink the latest `aet-work/` skill directory.

### 2. Back up current state

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy files in backup step -->
```bash
cp .agents/work-queue.json .agents/work-queue.json.pre-fods-backup
cp .agents/work-archive.json .agents/work-archive.json.pre-fods-backup 2>/dev/null || true
```
<!-- aet-lint: on -->

### 3. Migrate plan files to the frontmatter contract

If plan files do not yet have frontmatter, run the migration helper:

```bash
python3 scripts/archive/migrate-plans-to-frontmatter.py --plans-dir docs/plans --dry-run
python3 scripts/archive/migrate-plans-to-frontmatter.py --plans-dir docs/plans --apply
```

Review the reconciliation report it emits. Every plan must have:

```yaml
---
id: <filename-stem-or-explicit-id>
blocked_by: []
size: S | M | L
work_class: normal
---
```

`status` has been removed from the plan frontmatter contract (ADR-055). Do not
add or migrate a `status` key.

### 4. Seal legacy terminal tasks to settled history

Run the heal command once to move terminal tasks that predate the automatic seal:

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy queue file path in upgrade command -->
```bash
aet state heal --apply .agents/work-queue.json
```
<!-- aet-lint: on -->

This appends terminal tasks to `.agents/work-history.jsonl` and removes them from the live queue. The command prints what it sealed.

### 5. Reconcile the open-work board

```bash
aet queue sync
```

This drops terminal records and rebuilds the blocker DAG. Re-add any approved plans that should be on the board with `aet sprint add`.

### 6. Record merges for already-merged branches

For any task whose branch is already merged to the resolved trunk branch but the queue still shows it as active:

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy queue file path in upgrade command -->
```bash
aet state record-merge <task-id> .agents/work-queue.json
```
<!-- aet-lint: on -->

Repeat for each merged task. The command resolves the real squash-merge SHA via `gh` (or a diff-equivalence fallback) and seals the task to history automatically.

### 7. Audit and clean up

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy queue file path and cleanup commands -->
```bash
aet state audit .agents/work-queue.json
```

Fix any discrepancies by transitioning tasks to the correct state or recording merges.

Then remove stale artifacts:

```bash
# Old archive file (no longer read)
mv .agents/work-archive.json .agents/references/work-archive-legacy.json 2>/dev/null || true

# Old orchestrator log (if present)
rm -f scripts/.aet-work-orchestrator.log

# Stale worktrees and branches for merged tasks
git worktree list | grep -v '(main)'  # inspect before deleting
git branch --merged main | grep -v '^\* main$'  # inspect before deleting
```
<!-- aet-lint: on -->

### 8. Validate

Run the project's validation gates:

```bash
make validate
```

or, for non-toolkit projects, the equivalent lint/test command.

## Worktree dependency warmup (optional)

If your project has large dependency directories that are expensive to recreate in every worktree, you can declare them in `.agents/aet-config.json`:

```json
{
  "symlink_dependencies": [
    {
      "name": "node_modules",
      "source": "app/node_modules",
      "target": "app/node_modules"
    },
    { "name": "vendor", "source": "api/vendor", "target": "api/vendor" }
  ]
}
```

The orchestrator symlinks each `source` (relative to the repo root) into `target` (relative to the new worktree) when a worktree is created. Missing sources are reported as `environment_issue` telemetry events rather than halting the pipeline.

## Ongoing maintenance

<!-- aet-lint: off -->
<!-- Deliberate citation of legacy queue file in maintenance instructions -->
- Never edit `.agents/work-queue.json` by hand.
<!-- aet-lint: on -->
- Use `aet state transition` for state changes.
- Use `aet state record-merge` when a PR merges.
- Run `aet state audit` when you suspect drift.
- Keep `docs/plans/*.md` frontmatter complete so intake stays fail-closed.
