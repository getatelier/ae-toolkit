---
subject: two-layer-config-model
---

# Two-Layer Config Model: Committed Team File, External Shadow File

## Status

Accepted. Builds on ewl-07 (external-first config precedence,
`docs/plans/ewl-07-non-invasive-config-root.md`) and ADR-022 (project slug
derivation), and preserves ADR-044 (per-run integration branch) and ADR-045
(epic integration mode). Implemented by the cfg-01..05 plan set under
`docs/prds/aet-config-file-overhaul-prd.md`.

## Context

AET's project config lived at `.agents/aet-work.json`, resolved relative to the
process cwd, with an external-first chain (`AET_WORK_CONFIG` env →
`~/.aet/{slug}/config.json` → in-tree file → defaults) added by ewl-07. Three
structural problems surfaced with real consumers (2026-07-24):

1. **Two adoption modes, no vocabulary.** A team adopting AET wants a committed
   config shared by every checkout; a solo dev on a shared repo ("shadow mode")
   wants zero committed files. Both were possible but undocumented, and neither
   had a sanctioned home.
2. **cwd-relative in-tree resolution.** Running `aet` from a subdirectory or a
   linked worktree silently missed the in-tree file and fell back to defaults —
   a silent revert to trunk-based mode.
3. **Worktree-labelled config slug.** The external config path used
   `derive_project_slug()`, which labels each linked worktree
   (`<main-dir>/<worktree>`, ADR-022). A personal config written from the main
   checkout was invisible from a linked worktree, pushing users toward
   forgettable env-var pinning (`AET_PROJECT_ID`).

## Decision

1. **Two layers, one mechanism.** The in-tree file, renamed to
   `.agents/aet-config.json`, is the *team layer*: commit it and every clone,
   checkout, and worktree resolves it. The external
   `~/.aet/{slug}/config.json` is the *shadow layer*: personal, never
   committed, and first in precedence so a solo dev can override a committed
   team config locally. Shadow mode requires nothing in the repo — the
   ewl-07 non-invasiveness bar is preserved.
2. **Repo-root-anchored resolution.** The in-tree path resolves against the
   repository root (`git rev-parse --show-toplevel`), never the cwd.
3. **A config-specific slug.** `derive_config_slug()` returns the
   main-worktree identity (label dropped) and is used only for config
   resolution. `derive_project_slug()` is unchanged: telemetry and gate
   evidence keep per-worktree granularity (ADR-022).
4. **Clean rename, fail closed.** `.agents/aet-work.json` is not read as a
   fallback. When only the legacy file exists, resolution raises a
   `LegacyConfigError` naming `aet configure --migrate`, which performs the
   git-aware rename. The failure mode this refuses is a silent revert to
   trunk-based defaults.
5. **A CLI writer.** `aet configure` (renamed atomically from
   `configure-backend` per ADR-039) writes any of the four config keys with
   `--scope project|user`, validating values at write time. A `--guided` flow
   asks the two setup-time questions (scope as `team|shadow`, integration mode)
   and writes a valid config without hand-editing JSON. `--migrate` performs
   the git-aware rename from `.agents/aet-work.json` to `.agents/aet-config.json`.
6. **Per-run branch override.** `aet run` and `aet run-one` accept and forward
   `--base <branch>` to the orchestrator, so the per-epic integration branch
   remains a runtime input (ADR-044) and is reachable from the installed CLI.
7. **Inspectability.** `aet setup verify` prints the resolved `integration_mode`,
   `integration_branch`, and `trunk_branch` with provenance (config / detected /
   fallback).

## Consequences

- Existing installs with `.agents/aet-work.json` break loudly on upgrade, with
  a one-command remedy (`aet configure --migrate`) and an upgrade guide. The
  blast radius is small: the file is rare in the wild.
- Two slug identities now exist by design. CONTEXT.md records the Config Slug
  / Project Slug distinction; conflating them is the named misuse.
- All direct readers of the old path (orchestrator explicit call sites,
  `worktree.py` `symlink_dependencies`, `reconcile.py`, `sprint.py`) move to
  the new filename in cfg-01 — the rename is mechanical but broad.
- `integration_branch` stays out of the committed file (ADR-044): team files
  carry team-wide keys; the per-epic branch remains a per-run input
  (`--base`, now forwarded by the `aet` dispatcher).

## Alternatives Considered

- **Gitignored in-tree file for shadow mode** — rejected: untracked files do
  not propagate to linked worktrees, and the gitignore edit is itself a
  committed change to a shared file (ewl-07's rejection stands).
- **Silent fallback read of the legacy file** — rejected: hides the upgrade
  from unattended agent runs and delays the rename forever.
- **Env-var pinning (`AET_PROJECT_ID`) as the documented shadow path** —
  rejected: forgettable per-shell state; the config-specific slug makes it
  unnecessary.
- **Changing `derive_project_slug()` to drop the label globally** — rejected:
  telemetry/reports consumers rely on per-worktree identity (ADR-022).
