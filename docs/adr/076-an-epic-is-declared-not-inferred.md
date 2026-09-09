---
subject: epic-identity
relates: [45]
---

# An Epic Is Declared, Not Inferred

## Status

Accepted. Amends ADR-045 (Epic Integration Branch and Per-Task Integration Mode)
regarding epic identity representation.

## Context

ADR-045 introduced the epic integration branch layer for `single-pr` mode,
generalizing the trunk-based workflow so that multi-plan deliverables in shared
repositories can integrate locally into a common feature branch and ship as a
single pull request. In ADR-045's original model, an epic's identity was
represented by its integration branch plus the PRD referenced by the plans, with
the branch derived from the PRD's filename stem or passed as a per-run `--base`
override.

This inference model had several limitations:

1. An epic spanning multiple PRDs or decomposing work without a 1:1 PRD
   filename match required repeating `--base` on every invocation.
2. The epic pull request title and body had nowhere to live prior to shipping.
3. Inferring the active branch meant tasks could diverge silently if a plan
   referenced a different PRD or if the active context shifted mid-sprint.

## Decision

1. **An epic is declared, not inferred.** An epic's identity (integration branch,
   PR title, PR body file) is an explicit declaration. The active epic is declared
   in the queue envelope (`refs/aet/meta/queue`) via `aet epic set <branch>` and
   read by the orchestrator. Filename-stem derivation is demoted to a fallback
   step in the resolution chain.
2. **One active epic at a time; mismatch halts.** A single queue envelope
   maintains at most one active epic declaration. When a task record is stamped
   with an `integration_branch` at intake, subsequent runs verify that the
   active resolution matches the stamped branch. Any divergence halts execution
   fail-closed with an actionable error naming the mismatch and recovery remedies.
3. **The declaration is not a persisted entity beyond the envelope key and
   task stamp.** No separate `docs/epics/` directory or new git ref is
   introduced. The declaration lives in the existing queue envelope metadata blob
   and is stamped onto task records (`task["integration_branch"]`) at intake.
4. **Full 8-step resolution order.** In `single-pr` mode, the integration branch
   resolves in the following strict order:
   1. CLI override (`--base` / `cli_base`) — provenance `cli`
   2. Environment variable (`AET_WORK_BASE_BRANCH`) — provenance `env`
   3. Task record stamp (`task["integration_branch"]`) — provenance `stamp`
   4. Parent document declared branch (`branch` in PRD frontmatter) — provenance `document`
   5. Envelope active epic (`read_epic()`) — provenance `epic`
   6. PRD filename stem fallback — provenance `prd`
   7. Config `integration_branch` — provenance `config`
   8. Trunk fallback — provenance `trunk`

   In `pr-per-task` mode, steps 3–6 are skipped, preserving ADR-045 Scenario A
   as the degenerate case.

## Consequences

- Operators declare the active epic once with `aet epic set` and drive execution
  with standard `aet run` and `aet ship open-epic` commands without repeating
  CLI flags.
- Task execution is deterministic: worktrees and local integration targets are
  guaranteed by the per-task stamp and protected by fail-closed mismatch halts.
- PRDs can optionally declare `branch` and `pr_title` in frontmatter to override
  filename-stem inference.
- Backward compatibility is maintained for repositories relying on config or
  filename-stem derivation.
