---
subject: plan-atomicity-boundary
---

# Work Queue Plan Atomicity Boundary

## Status

Accepted

## Context

The `aet-work` skill treats every `.md` file in `docs/plans/` as an executable task. There was no guardrail to distinguish atomic implementation plans from roadmaps, audits, or meta-plans. This broke the 1:1 mapping between queue entries and plan files that `aet-pipeline-implement` expects, causing:

- Pipeline mis-routing when non-atomic documents were fed into `aet-pipeline-implement`
- Context bloat from multi-phase roadmaps entering the execution queue
- Worktree confusion when a single "plan" spanned multiple branches

The gap was between planning (where any markdown document could be produced) and queue management (which assumed every `.md` in `docs/plans/` was a single-session task).

## Decision

Enforce a directory-based structural boundary:

| Directory        | Content                                               |
| ---------------- | ----------------------------------------------------- |
| `docs/plans/`    | Atomic, implementable task plans ONLY                 |
| `docs/roadmaps/` | Multi-phase roadmaps, completion trackers, meta-plans |
| `docs/audits/`   | Testing audits, strategy reviews, gap analyses        |
| `docs/prds/`     | Product Requirements Documents (already established)  |

Skill changes to enforce this boundary:

1. **`aet-work/SKILL.md`** — `init-queue` and `sync` explicitly state that `docs/plans/` is for atomic plans only. `sync` gains an atomicity validator: if a plan references other plan files or contains multiple "Phase" sections, it emits a warning and skips the file.

2. **`aet-plan/SKILL.md`** — Instructs agents to save atomic plans to `docs/plans/{ticket-id}-plan.md` and roadmaps/audits/meta-plans to `docs/roadmaps/` or `docs/audits/`.

3. **`aet-pipeline-plan/SKILL.md`** — References the directory constraint in its `aet-work sync` step, making it clear that only atomic plans from `docs/plans/` are synced.

4. **`docs/CONVENTIONS.md`** — Documents the directory convention with a lookup table and rules.

## Consequences

- **Easier:** The work queue maintains a 1:1 mapping with implementable tasks. Every queued task is guaranteed to fit in a single agent session.
- **Easier:** Users have clear guidance on where to save different planning artifacts.
- **Harder:** Users must exercise discipline to save documents in the correct directory. The atomicity validator in `aet-work sync` catches violations but requires manual relocation.
- **Harder:** Existing consumer repos may have non-atomic plans in `docs/plans/`. Migration is documented but not enforced.

## Alternatives Considered

1. **Content heuristics** — Auto-detect non-atomic plans by scanning for "Phase" headers or cross-references. Rejected: overkill for this fix; directory separation is simpler and more explicit.
2. **File-naming convention** — Enforce `-plan.md`, `-roadmap.md`, `-audit.md` suffixes and scan by pattern. Rejected: directory location is the primary gate; filename convention is advisory only.
3. **Schema validation in work-queue.json** — Add an `atomic` boolean flag to queue entries. Rejected: pushes the problem to ingestion time rather than creation time; does not teach users where to save files.
