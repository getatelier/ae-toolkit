---
subject: canonical-verdict-path
---

# One Canonical Verdict Path per (Task, Kind), Published in Every Session Shape

## Status

Accepted (2026-07-11). Amends ADR-019. Implements plan `docs/plans/frh-18-group-evidence-path-contract.md`.

## Context

ADR-019 established the structured-gate-evidence contract: checking skills write a verdict to `~/.aet/reports/{project-slug}/{task-id}/{kind}.json`, and the orchestrator's fail-closed gate reads it back via `derive_project_slug(repo_root)` (the main-worktree slug, `<main-dir>/main`).

On 2026-07-11 `thp-04-retention-prune-cli` was marked `failed` three times despite complete, verified work. Root cause: `run_stage` exports the gate-canonical path as `AET_EVIDENCE_PATH`, but `run_stage_group` exported no evidence path at all. A group-session agent therefore fell back to the skill's default rule, whose `{project-slug}` was undefined; agents that hand-computed it from the worktree CWD wrote to `<main-dir>/<worktree>/...`, which the gate cannot see. Verdict existed, gate failed closed, task failed — and the footer still advanced, so re-runs reproduced the failure indefinitely. The behavior was nondeterministic: agents that used `evidence.write_verdict` with defaults landed on the gate path by luck (batch children inherit `AET_REPO_ROOT`). An implicit contract with two viable interpretations is the defect.

## Decision

1. **Canonical resolver.** `aet-work/lib/evidence.py` provides `resolve_verdict_path(task_id, kind, project_slug=None)` with a three-step precedence:
   1. `$AET_EVIDENCE_PATH` (single-stage sessions; unchanged).
   2. `$AET_EVIDENCE_PATH_<KIND>` — kind uppercased, non-alphanumeric → `_` (e.g. `sync-docs` → `AET_EVIDENCE_PATH_SYNC_DOCS`).
   3. Default: `evidence_path(task_id, kind, project_slug)`.
2. **Group sessions publish per-kind paths.** `run_stage_group` sets `AET_EVIDENCE_PATH_<KIND>` for every evidence-bound stage in the runnable span, computed with the identical formula `run_stage` uses. Writers and the gate share one derivation regardless of session shape.
3. **Writer contract.** The four checking skills name `resolve_verdict_path` as the canonical helper and state the three-step precedence. Improvised slug computation from the worktree CWD is out of contract.
4. **Gate diagnostics.** The `missing {kind} verdict` message includes the resolved path the gate read, so a future mismatch is a one-line diagnosis.

## Consequences

- Exactly one canonical verdict location exists per (task, kind), and it is delivered to writers explicitly in both session shapes; no agent ever needs to derive a slug.
- Recovery from verdicts written to legacy worktree-slug paths is a one-line `cp` to the canonical location.
- The gate's failure message is self-explaining; the next path mismatch costs minutes, not hours.

## Alternatives Considered

- **Dual-read gate fallback** (gate also reads the worktree-slug path) — rejected: entrenches two write locations and weakens the fail-closed design.
- **One verdict manifest file per group session** (`AET_EVIDENCE_MANIFEST` JSON) — rejected: more machinery than per-kind env vars for at most four kinds; env vars match the existing single-stage contract.
