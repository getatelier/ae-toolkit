# PRD: CLI/Skill Namespace Consolidation

## Overview

The 2026-07-19 tooling-usage retro exposed three agent-facing frictions — `aet run` timing out in the foreground, hesitation around the `aet ship` workflow, and `aet evolve` failing as a nonexistent subcommand. Two of the three trace to namespace collision: `aet ship` (opens the PR) collides with a separate bare `ship` binary (does closure) — still live in `.agents/commands/aet-work.md`, which currently asserts "`aet ship` opens the PR" as though that were the whole workflow — and `aet-evolve` the skill collides with an assumed-but-nonexistent `aet evolve` subcommand. The foreground timeout is a distinct root cause — an unsafe default execution mode, not a naming problem — and rides in this workstream as R-6 because it surfaced in the same retro, not because the taxonomy fixes it. The retro's fixes were documentation; documentation drifts, and already has: the command doc above was written the same session the retro closed. This workstream applies the agreed organizing principle — **deterministic work becomes code/CLI, judgment stays in skills, and after proper separation no two things share a name** — to restructure the command surface, promote deterministic skills to code, and daemonize the orchestrator. It is injected into the pkg-* package-extraction roadmap: the taxonomy ADR lands before pkg-11 (Typer consolidation) is implemented, and the ship/release-prep/sync-docs promotions extend **Phase A1**'s existing (but currently incomplete) skill-code migration list — not a new "Phase A4," which already means dependency adoption (PyYAML, filelock, Typer, panel framework).

## Goals

- A documented namespace taxonomy (ADR) that defines the deterministic/judgment split, naming conventions for each side — building on the noun-scoped, nested-verb convention already established for `aet sprint add`/`aet backlog add` (gib-06), not a fresh scheme — and a no-collision rule, settled before pkg-11 rewrites the CLI surface.
- Every current collision (ship, review, plan, sync, evolve) resolved by atomic rename: old name retired in the same merge that ships the new one, no alias, no shim — the gib-06 precedent, not a new transition mechanism.
- aet-ship and aet-release-prep promoted to code, following the proven aet-work/aet-evolve pattern (code does mechanics, skill keeps judgment); aet-sync-docs gets the same treatment only for whatever slice of its comparison step turns out to be genuinely mechanical (see R-5) — it is not assumed to be a peer of the other two.
- `aet run`/`aet run-one` self-daemonize so no agent harness configuration or doc discipline is needed to run them safely.
- Agent-facing docs corrected where they currently instruct wrong behavior.

## Non-Goals

- Renaming skills that are correctly judgment-only (aet-plan, aet-review, aet-cso, aet-qa, aet-evolve, etc.) — they stay as-is unless a collision forces a change.
- Track B distribution work (installer, `aet skills` lifecycle, PyPI) — already owned by the pkg roadmap.
- Splitting aet-setup (420-line SKILL.md) — noted as future work; not in this workstream.
- Changing `pkg-*` plans other than pkg-06 (cross-skill extraction, amended to add release-prep.sh and sync-docs scope alongside its existing ship entry) and pkg-11 (Typer consolidation, amended with the rename tasks) — every other `pkg-*` plan is untouched beyond the roadmap's Phase A1 file-list update.
- The aet-setup split and panel framework work remain pkg-12/roadmap scope.

## Requirements

- **R-1**: A namespace taxonomy ADR records the separation principle (deterministic → code/CLI; judgment → skill), per-side naming conventions (inheriting the noun-scoped, nested-verb convention gib-06 already established, e.g. `aet state <sub>`, `aet sprint add` — not ad hoc hyphenation), the no-collision rule, and the rename spec for every current collision (ship, review, plan, sync, evolve). Renames are atomic and alias-free by default, per the no-backward-compat standing rule and the gib-06 precedent (`docs/plans/gib-06-command-groups-sprint-add.md`); shims/aliases are recorded under Rejected Alternatives, not offered as the transition mechanism.
- **R-2**: The CLI rename spec is implemented by amending **pkg-11** (`docs/plans/pkg-11-typer-consolidation.md`) directly — it is already `status: queued`, `blocked_by: pkg-06`, and currently scoped as strictly behavior-preserving ("preserving flags, defaults, and help text"), so the rename tasks are new additions to that plan, not free riders on work it already scopes. Phase A1 extraction plans that land before the ADR remain behavior-preserving (old names move unchanged).
- **R-3**: `aet ship` becomes a single code entry point covering the full ship workflow (pre-merge gate checks, PR creation, post-merge closure) — completing the boundary `docs/adr/007-ship-release-prep-separation.md` already drew (ship owns merge verification; release-prep owns release docs), not redrawing it. The legacy `ship` bare binary and `~/.local/bin/ship` symlink are removed; aet-ship SKILL.md is reduced to judgment residue or retired.
- **R-4**: aet-release-prep's deterministic pipeline is promoted into the package as `aet release-prep`; `release-prep.sh` moves from the skill root into the package; the SKILL.md keeps only judgment (release-notes prose, version-bump recommendation review).
- **R-5**: aet-sync-docs has no existing script — unlike R-3/R-4, there is nothing to promote. `aet sync-docs` ships only the genuinely mechanical slice (changed-file diffing, task-list checkbox state, resolving the active plan/PRD pair) as structured output; classifying a change as changed/added/deferred against plan intent stays skill judgment unless a follow-up design spike demonstrates it can be made deterministic. This requirement does not presume that spike's outcome.
- **R-6**: `aet run` and `aet run-one` self-daemonize: they return immediately with a run ID, and progress is followed via `aet run --follow <id>` / `aet status`; a `--foreground` flag preserves attached execution for debugging.
- **R-7**: Known agent-facing doc/tooling drift is corrected: `.agents/commands/aet-work.md`'s false "`aet ship` opens the PR" claim, `ship` added to the installer's legacy-prune list, and the pkg roadmap's Status Tracker table resynced in full to reality — not only pkg-01/pkg-02, but Phase A0 (ADRs 036/037/038 already Accepted; table still says "pending") and Phase A1's actual plan-level progress.
- **R-8**: `content/backlog/aet-package-extraction-roadmap.md` is updated to inject this workstream accurately: the taxonomy ADR referenced pre-pkg-11-implementation; the ship/release-prep/sync-docs promotions added to **Phase A1**'s file list (which currently omits release-prep.sh and any sync-docs script — a pre-existing gap this closes), with pkg-06 amended to match; daemonization referenced against its actual dependency (pkg-04, not pkg-06); Phase A4 is left describing dependency adoption only.

## User Stories

- As the toolkit maintainer, I want a written taxonomy that settles what may be a skill vs a CLI command, so that future skills are organized correctly by construction instead of by retro (satisfies: R-1, R-2).
- As an agent operator, I want `aet ship` to be one deterministic command for the whole ship workflow, so that shipping never requires cross-namespace knowledge (satisfies: R-3).
- As an agent operator, I want release prep fully automated and docs-sync's genuinely mechanical steps automated, so that model discretion is spent only where classification actually requires judgment (satisfies: R-4, R-5).
- As an agent operator, I want `aet run` to detach itself and report a run ID, so that no foreground timeout can kill a batch regardless of harness (satisfies: R-6).
- As an agent, I want the operational docs to describe the CLI as it actually behaves, so that following the docs never produces a wrong action (satisfies: R-7).
- As the toolkit maintainer, I want the pkg roadmap to show where this workstream plugs in, so that the two efforts can't drift apart (satisfies: R-8).

## Acceptance Criteria

- [ ] The taxonomy ADR exists in `docs/adr/`, every collision identified in the 2026-07-19 audit has a settled resolution in it, renames are specified as atomic and alias-free by default, and shims/aliases appear only under Rejected Alternatives (satisfies: R-1).
- [ ] `docs/plans/pkg-11-typer-consolidation.md` is amended to reference the taxonomy ADR as its naming source of truth and carries the rename tasks; no pkg Phase A1 plan performs a rename (satisfies: R-2).
- [ ] After promotion, the full ship workflow (gate → PR → closure) runs through `aet ship` subcommands only, consistent with ADR-007's ship/release-prep boundary; `which ship` returns nothing after `aet install` (satisfies: R-3).
- [ ] `aet release-prep` executes the full deterministic pipeline with no executable script remaining at the skill root (R-4); `aet sync-docs` executes only the mechanical slice defined in R-5 — or ships no CLI surface at all, if the spike finds none is safely separable — with divergence classification remaining skill judgment either way (satisfies: R-4, R-5).
- [ ] `aet run` invoked in a short-timeout foreground shell returns successfully within seconds with a run ID, and the batch continues to completion detached (satisfies: R-6).
- [ ] `aet-work.md` describes the ship workflow as implemented; installer prune list includes `ship`; the roadmap's Status Tracker table is resynced in full — including Phase A0 showing Accepted and Phase A1's actual plan-level progress, not only pkg-01/pkg-02 (satisfies: R-7).
- [ ] The pkg roadmap references the taxonomy plan before pkg-11's implementation and lists the ship/release-prep/sync-docs promotions as additions to **Phase A1**'s file list, with pkg-06 amended accordingly; daemonization is referenced against pkg-04; Phase A4 remains dependency-adoption-only (satisfies: R-8).

## Technical Notes

- The promotions (R-3, R-4) depend on **pkg-06** (cross-skill extraction, `blocked_by: pkg-04`) — its file list already covers `aet-ship/bin/ship` (task 1) and `aet-release-prep/release-prep.sh` (task 5), but task 5 currently relocates the script to `scripts/release-prep.sh`, explicitly annotated "not a Python subcommand — repo tooling, not package code" — the opposite disposition from R-4's promotion goal. This workstream amends pkg-06's task 5 to convert `release-prep.sh` into a Python `aet release-prep` subcommand rather than a relocated shell script, and adds a new task for whatever slice of aet-sync-docs R-5's spike finds mechanical (aet-sync-docs has no task in pkg-06 today). R-6 (daemonization) touches `aet-work/bin/orchestrator`, which is extracted earlier, in **pkg-04** (A1c) — not pkg-06. R-6 carries its own `blocked_by: pkg-04` edge, independent of the promotions, so it isn't queued behind pkg-06 unnecessarily.
- R-2's rename spec is implemented by amending pkg-11 directly (already `status: queued`, `blocked_by: pkg-06`, strictly behavior-preserving as written) — not by finding free space in it.
- The transition vehicle for every rename is the mechanism gib-06 already proved (`docs/plans/gib-06-command-groups-sprint-add.md`, merged 2026-07-19): retire the old subcommand with no alias in the same merge that ships the new one, extend skills-lint to validate the new shape, sweep canonical docs + live skills, add a grep-guard regression test. No new "legacy-shim" mechanism is introduced.
- Unlike aet-ship (`aet-ship/bin/ship`) and aet-release-prep (`aet-release-prep/release-prep.sh`), aet-sync-docs has no existing script — its comparison step is entirely skill prose today. R-5's mechanical half is not proven; treat it as net-new deterministic-vs-judgment design work, not a relocation.
- Daemonization design constraints: orchestrator already has telemetry, per-task logs, and usage envelopes (nsr/frh hardening); detach-and-follow is a presentation-layer change, not new infrastructure. Must preserve the existing per-task timeout/stall-watchdog semantics.
- Collision evidence, restated durably rather than left in session discussion: `.agents/commands/aet-work.md` stated "`aet ship` opens the PR" while its own workflow sent closure to a *separate* bare `ship <task-id> <plan-path>` binary — the clearest live instance of the ship/ship collision, written the same session the retro tried to fix it. `aet evolve` failing as an unknown subcommand reproduces directly against the current CLI. The taxonomy ADR should restate both as its collision table, plus the full 2026-07-19 command-surface inventory (20 skills, 23 CLI subcommands, ~25 bin executables).
- R-3 completes the boundary `docs/adr/007-ship-release-prep-separation.md` already drew (ship owns merge verification; release-prep owns release docs) — it does not redraw it.
- aet-evolve stays a skill (rule/template editing is judgment); `aet retro` / `aet mine-learnings` remain its code half. A friendly `aet evolve` stub error ("this is a skill — activate it, or see `aet retro`") is an option for the taxonomy to decide.

## Open Questions

- Exact new names for colliding subcommands, evaluated in the ADR against the noun-scoped, nested-verb convention gib-06 already established (`aet state <sub>`, `aet sprint add`, `aet backlog add`) — candidates like `aet review` → `aet gate review`, `aet plan` → `aet plan validate`, `aet sync` → `aet queue sync`. A flat hyphenated form (e.g. `aet queue-sync`, `aet validate-plan`) or a bare noun with no verb (`aet board`) repeats the shape gib-06 already rejected for `add`, and should not be the default candidate.
- Whether aet-ship retains any skill residue after R-3 (readiness judgment) or is fully retired.
- Whether daemonization uses fork/detach, a daemon lockfile + `aet run --follow`, or reuses the panel server as the run supervisor.
- Whether `aet evolve` gets a helpful stub error or stays absent from the CLI namespace.
- Whether R-5's mechanical slice is worth a standalone `aet sync-docs` invocation at all, or should only ever run inside the pipeline — an output of the design spike, not assumed here.

## Intake Triage

Classified as **feature/enhancement** (reorganization + promotion), not a reproducible defect — confirmed at pipeline intake 2026-07-19. The underlying defects (foreground timeout, doc drift) are captured as requirements R-6/R-7 rather than bug reports because the fix is structural.

## Divergence Summary

*Recorded: 2026-07-20 — Branch: nc-06-run-daemonization*

### Changed from plan

- Task 8 (tests): In addition to the two planned new test files, the existing `tests/cli/test_aet_dispatcher.py` was updated so the run/run-one mapping tests exercise the new default-detached path through mocked `subprocess.Popen` and keep the legacy `_exec()` path covered under `--foreground`.

### Added (unplanned)

- `scripts/skills-lint`: Extended the `run`/`run-one` grammar with dispatcher-only flags `--foreground` and `--follow` so the skill-instruction linter recognizes them as valid even though the orchestrator parser does not declare them.

### Deferred

- Task 9 (merge to main and integration verification): intentionally left for the `aet-ship` stage.

## Divergence Summary — nc-03a ship gate

*Recorded: 2026-07-21 — Branch: nc-03a-ship-gate-as-code*

### Changed from plan

- Task 4 (test-suite/coverage invocation): Hardened `AET_SHIP_TEST_CMD` and `AET_SHIP_COVERAGE_CMD` execution from `shell=True` to `shlex.split(cmd)` + `shell=False` after a security-audit finding. The functional behavior (configurable test/coverage commands) is unchanged.

### Added (unplanned)

- `.agents/commands/aet-work.md`: Updated ship workflow examples to `aet ship gate <plan>` and `ship record-merge ...`, correcting the pre-existing "`aet ship` opens the PR" drift (R-7).
- `tests/cli/test_build_parsers.py`, `tests/fixtures/skills-lint/valid.md`, `tests/ship/test_merge_governance.py`: Updated to match the new `ship record-merge` subcommand syntax.
- Security-audit report and verdict recorded under `/tmp/aet-reports/nc-03a-ship-gate-as-code/` and submitted via `aet gate submit`.

### Deferred

- Task 10 (merge branch to main and verify integration): intentionally left for the `aet-ship` stage.

---

*Stage: synced*
*Next step: run `aet-ship`*
