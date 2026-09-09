---
subject: projection-axis
---

# Optional GitHub Issues Adapter for the Work Queue

## Status

Superseded by ADR-032 (GitHub Issues Is a Projection, Not a Backend). Revises ADR-011 (Forward-Only Deterministic Work State). Annotated 2026-07-14 (ewl-04-git-refs-default-flip): Decision 1's "JSON is the default backend" remains true for unconfigured projects — the factory fallback is unchanged — but `aet-setup` now writes `git-refs` as the default configured backend; JSON is the documented opt-out for non-git or unconfigured contexts.

## Context

ADR-011 rejected moving the work queue to GitHub Issues to preserve the toolkit's agent- and infra-agnosticism and because GitHub has poor native DAG support. That decision kept the queue in local JSON files with plan files as the durable source of truth.

Since then, two needs have become clear:

1. **Visibility for non-agent collaborators.** Teams that already track work in GitHub Issues want tasks discoverable there without giving every teammate access to agent-specific queue files.
2. **Default must remain infra-agnostic.** Local-only and offline projects should not be forced to use GitHub or any external service.

The question is whether to offer GitHub Issues as an optional adapter while keeping the JSON backend as the canonical default.

## Decision

Add an optional GitHub Issues adapter to `aet-work`. The JSON file remains the canonical, infra-agnostic default; GitHub Issues is an opt-in mirror.

1. **JSON is the default backend.** Projects without `.agents/aet-work.json` or with `"task_backend": "json"` behave exactly as before.
2. **GitHub Issues is an adapter, not the source of truth.** The local JSON queue continues to hold the scheduling state; the GitHub backend mirrors tasks as issues and AET states as issue labels.
3. **Plan files remain canonical for content.** Issue bodies reference plan files; acceptance criteria stay in the PRD.
4. **One backend active at a time.** Configuration is read from `.agents/aet-work.json` at the start of every `aet-work` command.
5. **Forward-only switching.** Changing backends does not migrate active tasks or settled history. Existing issues or JSON records created under the previous backend are left untouched.
6. **Single writer for state.** `aet-state transition` remains the only code path that mutates state; the backend adapter only makes the transition durable on the configured store.
7. **`aet-setup` configures the backend.** It writes `.agents/aet-work.json`, detects the repository from `git remote origin`, and creates the required `aet:*` labels when GitHub is selected.

## Consequences

- **Easier:** Teams can expose agent tasks in GitHub Issues without changing the default architecture.
- **Easier:** Solo and offline projects continue to use the zero-dependency JSON backend.
- **Easier:** The DAG, dependency tracking, and plan-file content model remain unchanged.
- **Harder:** Two storage surfaces must be kept consistent for GitHub projects. Mitigated by the adapter keeping the JSON queue as the scheduling source of truth.
- **Harder:** Switching backends requires manual coordination because history is not migrated. This is intentional: it prevents accidental bulk mutations.

## Relation to ADR-011

ADR-011's core principle — state is recorded forward by code and trusted on read — remains valid. The GitHub adapter extends the "record forward" rule to issue labels: when `aet-state transition` runs, the adapter updates the issue label or closes the issue for terminal states. The queue file remains the operational source of truth; GitHub Issues is a durable mirror for human visibility.

## Alternatives Considered

1. **Move the queue entirely to GitHub Issues.** Rejected: violates infra-agnosticism and has poor native DAG support, as noted in ADR-011.
2. **Keep JSON only and ask users to mirror issues manually.** Rejected: it is error-prone and does not scale; an adapter provides a reliable, tested path.
3. **Support multiple backends simultaneously.** Rejected: it introduces split-brain risk and complicates the single-writer invariant. One active backend at a time keeps the model simple.
