---
subject: namespace-taxonomy
---

# Namespace Taxonomy: Deterministic Code vs. Judgment Skills

## Status

Accepted

## Context

Source: [docs/prds/namespace-consolidation-prd.md](../prds/namespace-consolidation-prd.md) (R-1).

The 2026-07-19 tooling-usage retro exposed namespace collisions between CLI subcommands and skills/binaries. The same word was doing two different jobs — one deterministic, one judgment-based — and the collision caused docs, muscle memory, and code to drift out of sync (for example, `.agents/commands/aet-work.md:42` states "`aet ship` opens the PR" while its own workflow sends closure to a separate bare `ship` binary).

The command-surface inventory at the time of the audit was:

- **20 skills:** `aet-bug-report`, `aet-cso`, `aet-design-system-creation`, `aet-evolve`, `aet-extract-stack`, `aet-implement`, `aet-pipeline-plan`, `aet-plan`, `aet-prime`, `aet-qa`, `aet-release-prep`, `aet-review`, `aet-setup`, `aet-ship`, `aet-sync-docs`, `aet-tdd`, `aet-upgrade`, `aet-validate-scope`, `aet-verify`, `aet-work`.
- **23 `aet` subcommands:** `sprint`, `backlog`, `desk`, `review`, `status`, `next`, `sync`, `report`, `metrics`, `reconcile`, `init-queue`, `state`, `gate`, `plan`, `run`, `run-one`, `ship`, `retro`, `mine-learnings`, `configure-backend`, `hooks`, `harness-guard`, `install`.
- **~25 standalone binaries across skill `bin/` directories**, including `aet-ship/bin/ship`, `aet-evolve/bin/aet-retro`, `aet-evolve/bin/mine-learnings`, `aet-setup/bin/configure-task-backend`, `aet-setup/bin/harness-guard`, `aet-setup/bin/hooks`, and the `aet-work/bin/` family (`aet`, `aet-state`, `backlog`, `desk`, `gate`, `init-queue`, `metrics`, `next`, `orchestrator`, `plan`, `reconcile`, `report`, `review`, `sprint`, `status`, `sync`, `validate-workflows`).

The collisions were:

| Word | CLI / binary | Skill | Problem |
| ---- | ------------ | ----- | ------- |
| `ship` | `aet ship` + bare `ship` binary | `aet-ship` | Two `ship` executables with different scopes (PR gate vs. closure). |
| `evolve` | (assumed) `aet evolve` subcommand missing | `aet-evolve` | Users expected a CLI counterpart; none exists because the work is judgment. |
| `review` | `aet review` (board renderer) | `aet-review` (code review skill) | Same word, completely different jobs. |
| `plan` | `aet plan` (plan validation) | `aet-plan` (planning skill) | Same word, completely different jobs. |
| `sync` | `aet sync` (queue sync) | `aet-sync-docs` (docs sync skill) | Same word, completely different jobs. |

Before `pkg-11` rewrites the CLI surface in Typer, we need a durable taxonomy that decides what becomes code/CLI and what stays a skill, plus naming conventions that prevent future collisions.

## Decision

### Separation principle

Deterministic work becomes code/CLI; judgment work stays in skills. After proper separation, no two things share a name.

- **Deterministic** = the output is fully specified by inputs and rules (queue sync, plan validation, merge-gate evidence submission, ship mechanics).
- **Judgment** = the output depends on model discretion, interpretation, or human-like reasoning (plan authorship, code review, release-notes prose, rule/template editing).

### Per-side naming convention

Both sides inherit the noun-scoped, nested-verb convention already established by `gib-06` (`aet state <sub>`, `aet sprint add`, `aet backlog add`):

- CLI deterministic commands use the form `aet <noun> <verb>`.
- Skills keep their `aet-<noun>` directory name and are triggered by natural-language intent, not by a subcommand.

The following shapes are rejected:

- Flat hyphenation (`aet queue-sync`, `aet validate-plan`) — it obscures the noun/verb boundary.
- A bare noun with no verb (`aet board`, `aet plan`) — it reads like a skill name and invites collision.

### Collision resolutions

| Collision | Disposition | Notes |
| --------- | ----------- | ----- |
| `ship` | Retire the bare `ship` binary. `aet ship` is already correctly named and covers the full ship workflow (pre-merge gate, PR creation, post-merge closure), completing the boundary ADR-007 already drew. The question of whether `aet-ship` SKILL.md keeps any judgment residue or is fully retired is `nc-03c`'s decision, not this ADR's. | No CLI rename; only the standalone binary is removed. |
| `evolve` | `aet-evolve` stays skill-only. Its deterministic half already lives in `aet retro` and `aet mine-learnings`. Add a friendly `aet evolve` stub error: "`aet evolve` is a skill — activate it, or see `aet retro` / `aet mine-learnings` for deterministic counterparts." | The stub is a guardrail, not a feature. |
| `review` | Rename the CLI subcommand `aet review` to `aet gate review`. `gate` becomes the noun scope for deterministic checking/review operations; `gate submit` remains the verdict writer. | The board renderer moves under the `gate` group. |
| `plan` | Keep the CLI surface as `aet plan validate`. The top-level `plan` entry is a noun-scoped group, not a bare command; the deterministic work is the `validate` verb. | Distinguishes the deterministic validator from the `aet-plan` judgment skill. |
| `sync` | Rename the CLI subcommand `aet sync` to `aet queue sync`. `queue` becomes the noun scope for queue-management operations. | Lays the groundwork for future queue commands (e.g. `aet queue init` replacing `aet init-queue`). |

### Rename mechanism

Every rename is atomic and alias-free by default. The old subcommand name is retired in the same merge that ships the new one, using the transition vehicle `gib-06` already proved:

1. Remove the old dispatcher entry in the same commit that adds the new nested entry.
2. Extend `scripts/skills-lint` to validate the new noun-scoped shape.
3. Sweep canonical docs and every live skill that invokes the old name.
4. Add a grep-guard regression test that fails if the old name reappears in live code or docs.

No shims, no aliases, no incremental deprecation window.

## Consequences

- **Easier:** The namespace is unambiguous — a user knows whether `aet <noun> <verb>` is deterministic code or whether they need to activate a skill.
- **Easier:** `pkg-11` has a single source of truth for naming new and migrated subcommands.
- **Easier:** The `ship`/`review`/`plan`/`sync`/`evolve` collisions are resolved atomically, without leaving legacy aliases to maintain.
- **More difficult:** Existing scripts, muscle memory, and docs that use `aet review`, `aet sync`, or bare `ship` must be updated in the same merge.
- **More difficult:** `scripts/skills-lint` must learn one more nested-subcommand family (`gate`, `plan`, `queue`).

## Alternatives Considered

- **Shims or aliases (`aet review` → `aet gate review` with `aet review` kept as alias).** Rejected. The project has a no-backward-compat standing rule; aliases are a deprecation window that would leave the collision alive.
- **Incremental deprecation window.** Rejected. It would let the old and new names coexist across merges, which is exactly the drift failure mode this ADR is meant to prevent.
- **Flat hyphenation (`aet gate-review`, `aet queue-sync`, `aet validate-plan`).** Rejected. It repeats the shape `gib-06` already rejected for `add`; it hides the noun/verb boundary and makes tab completion less discoverable.
- **Bare noun with no verb (`aet board`, `aet gate`, `aet queue`).** Rejected. A bare noun reads like a skill trigger and invites the same collision we are solving.
- **Promote `aet-review` / `aet-plan` / `aet-sync-docs` to CLI commands and retire the skills.** Rejected. Those skills perform judgment work (review reasoning, plan authorship, divergence classification); forcing them into deterministic CLI commands would either fake determinism or balloon the CLI with model-driven subcommands.
