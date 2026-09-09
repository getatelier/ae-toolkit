---
subject: worktree-project-identity
---

# Local Worktree Path as Telemetry Project Identity

## Status

Accepted (2026-07-11) — decided during the aet-panel investigation, ratified at the telemetry-hygiene PRD gate. Implemented by `thp-02-worktree-project-slug` / migrated by `thp-03-archive-slug-migration`.

## Context

`derive_project_slug()` (`aet-work/lib/telemetry.py`) identifies a project by the last two segments of the git **origin remote** URL. This repo's origin is `github.com:thebrightnest/ae-toolkit`, so every run filed under `thebrightnest/ae-toolkit` — a name the owner did not recognize when reviewing the telemetry panel ("why is aiskills missing?"). The slug names directories in two user-level stores: the telemetry archive `~/.aet/telemetry/{slug}/…` (ADR-012) and the gate-evidence reports `~/.aet/reports/{slug}/{task-id}/` (ADR-019, `evidence.py:96`).

The panel and `aet-work report` are local, single-machine tools, so cross-machine identity and folder-rename survival buy nothing here. Per-worktree visibility, by contrast, is actively wanted: which worktree a run launched from is a meaningful lens. The orchestrator pins `AET_REPO_ROOT` into every child session's env and `resolve_repo_root()` honors it before asking git, so identity is always the orchestrator's launch root — a run's sessions cannot scatter across per-task worktree identities.

## Decision

The project slug becomes `<main-worktree-dirname>/<current-worktree-dirname>`, with the primary worktree labelled `main`:

- this repo → `aiskills/main`; its panel worktree → `aiskills/aet-panel`
- detection: `git rev-parse --git-common-dir` → parent = main worktree; compared against the resolved repo root
- `AET_PROJECT_ID` / `AET_REPO_SLUG` env overrides are kept (escape hatch; also the way to merge two clones into one project)
- non-git directories keep the bare-directory-name fallback

Existing archive **and reports** project directories are migrated by a one-shot, dry-run-first rename script; no compatibility shim or dual-scheme support remains (project rule: no backward compat).

## Consequences

- Easier: owners recognize their projects; folder = repo, second segment = launch worktree; panel grouping and `aet-work report --project` work unchanged (two-segment shape preserved).
- Harder / accepted: two clones of one repo become two projects; two unrelated repos sharing a directory name under different parents merge; moving or renaming a folder starts a fresh project (out of scope by decision). Submodule checkouts are out of scope.
- Records never embed the slug, so migration is pure directory renames; evidence verdicts written before migration would be orphaned under old names unless the reports tree is renamed too — hence the migration covers both roots (fail-closed gates would otherwise just re-run stages).

## Alternatives Considered

- **Keep origin-remote identity** — rejected: unrecognizable names are the observed failure; breaks entirely for remoteless repos.
- **Rename map layered over origin identity** — rejected: two sources of truth for one name; every consumer would need the map.
- **Stable project-id file committed per repo** — rejected: per-repo setup burden and repo litter for a single-machine concern the filesystem already answers.
