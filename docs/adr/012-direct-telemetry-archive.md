---
subject: direct-telemetry-archive
---

# Direct Telemetry Archive and Per-Task Logs

## Status

Accepted

## Context

The AE Toolkit originally wrote execution telemetry to a project-local file,
`.agents/execution.log.jsonl`, and required a separate `aet-evolve ingest-telemetry`
step to copy it into the user-level archive at `~/.aet/telemetry/`. This design
had several operational problems:

- **Telemetry was lost by default.** `aet-work run` runs the orchestrator in the
  background. Users had to remember to run `ingest-telemetry` afterwards, and
  worktrees could be deleted before archiving happened.
- **Concurrent writes to one file.** Parallel task processes all appended to the
  same JSONL file, creating a race condition.
- **Extra ceremony.** The two-step write-then-archive flow added friction without
  adding unique value; sanitization and project tagging can happen at write time.
- **No per-plan pipeline control.** Every task paid the same isolation overhead
  regardless of size or risk.

## Decision

1. The orchestrator writes telemetry **directly** to the user-level archive:

   ```
   ~/.aet/telemetry/{project-slug}/{date}/{run-id}/
       ├── last-run.json
       ├── {task-id}.jsonl
       └── ...
   ```

2. Each task gets its own JSONL file, eliminating concurrent writes to a shared
   log. `last-run.json` records the run summary and completion status.

3. Absolute paths are sanitized to `{REPO_ROOT}` and `{HOME}` placeholders at
   write time.

4. `aet-evolve ingest-telemetry` is removed. `aet-evolve mine-learnings` reads the
   archive directly when the user chooses to run analysis.

5. Plan frontmatter gains a simple `pipeline: minimal|standard|full` field that
   overrides the orchestrator's `--isolation` default for that task.

6. `.agents/execution.log.jsonl` is no longer created. `.gitignore` examples are
   updated to exclude only `.agents/work-history.jsonl` and orchestrator logs.

## Consequences

- Telemetry survives project worktree deletion by default.
- Parallel task execution is safer because each task writes its own file.
- The telemetry workflow is one-way: write automatically, analyze manually.
- Plan authors can trade isolation for speed on low-risk tasks, or enforce full
  isolation on high-risk changes.
- Historical planning artifacts that referenced `ingest-telemetry` and
  `.agents/execution.log.jsonl` remain as records of the original design but are
  superseded by this ADR.

## Alternatives Considered

- **Keep `ingest-telemetry` and add a hook.** Rejected because hooks are
  unreliable across different agent runtimes and do not solve the lost-telemetry
  problem.
- **Write to both project-local and archive.** Rejected because the user asked
  for a single source of truth and less cleanup.
- **One file per run instead of per task.** Rejected because it would reintroduce
  concurrent writes in parallel batch mode.
