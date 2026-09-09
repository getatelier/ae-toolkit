# PRD: Roadmap Phase 2 — The `aet` Binary

## Overview

Phase 2 of the AET roadmap (`content/fable-review/09-2026-07-10-roadmap.md`): the orchestrator survives as a subcommand of the contract engine rather than the identity of the product. One multicall `aet` binary wraps every operational command (doc 06 step 3, mechanical exec dispatch); all skills are rewritten to invoke `aet …` exclusively; and skills-lint v1 in CI parses every documented invocation against the real argparse tree — the #1 systemic wound (docs↔code reality gap, doc 01) becomes a merge failure instead of a cultural discipline. PATH pollution and the missing-dispatcher wound (doc 01 critical issue 3) retire for good: the phase ends with exactly one AET name on PATH — `aet`, self-linking and self-repairing, with the standalone installer absorbed into `aet install`. Brief: `docs/product-briefs/roadmap-p2-aet-binary-brief.md` (R-ids carried from there).

## Goals

- **G1**: One entry point — the toolkit's operational surface is `aet <subcommand>`, dispatching 1:1 to the existing binaries with zero behavior change; PATH carries exactly one AET name, self-maintained (R-1, R-2, R-3, R-5, R-11).
- **G2**: The reality gap becomes a merge failure — skills-lint validates every documented `aet` invocation against the real parser tree in `make validate` (R-6, R-7, R-3). Implements doc 06 P5.
- **G3**: The migration completes and stays complete — every skill, template, scaffold, and runtime hint speaks `aet`; the legacy-reference rule at error severity makes regression unmergeable; all seven legacy PATH names are pruned and the old dispatcher file is deleted — no alias, no shim (R-5, R-8, R-9).
- **G4**: The machine-readable seam exists — `aet status --json` for the Phase 4 desk and any future read-only surface (R-4).

## Non-Goals

- No new capabilities behind subcommands: no `aet gate submit`, `aet hooks install`, or git-refs default flip (Phase 3); no `aet desk` / `aet plan validate` (Phase 4); no adapters or `aet doctor` (Phase 6); no `aet eval` (Phase 7).
- No merging of binaries into one Python program; exec dispatch only. No behavior change to wrapped commands beyond `status --json` and hint-string text.
- skills-lint v1 is syntactic, not behavioral (`aet eval` is Phase 7's half of closing the gap).
- No packaging, distribution, rebrand, daemon, or MCP (Phase 8 triggers; doc 06 open questions stay open).
- Standing fences hold: repo-CI scripts stay make-internal; lint scope is packaged skill content + project scaffolding, not the historical corpus.

## Requirements

_Carried verbatim from the brief — R-trace discipline per rdm-02._

- **R-1**: A single `aet` multicall binary (`aet-work/bin/aet`) dispatches every operational toolkit command as a subcommand: queue/board (`add`, `review`, `status`, `next`, `sync`, `report`, `init-queue`), execution (`run`, `run-one`), state (`state <audit|heal|validate|transition|set-stage|record-merge>`), closure (`ship`), learning (`retro`, `mine-learnings`), config (`configure-backend`), setup (`install`). Dispatch is exec-based 1:1 wrapping of the existing binaries — no behavior change; no argument re-parsing beyond the existing documented `run`/`run-one` mappings (default queue file; plan-file positional); all other args forward verbatim. `install` is the one subcommand implemented inside `aet` itself (R-5).
- **R-2**: Cross-skill targets resolve via the installed-skills layout (resolved script path → skills root → sibling skill `bin/`), the pattern `ship:31` already uses. A missing sibling fails with a clear error naming the skill to install; an unknown subcommand exits 2 with a usage listing.
- **R-3**: The subcommand → target-binary table is a declarative, importable spec inside the `aet` binary, so tooling (skills-lint) validates against the same source of truth the dispatcher executes.
- **R-4**: `aet status --json` emits machine-readable queue status (documented, stable keys: per-task id/state/stage/blockers plus summary counts); human output and exit codes unchanged. This is the seam future read-only consumers (`aet desk`, any UI) build on.
- **R-5**: The end-state PATH surface is exactly one name: `aet`. `aet install` absorbs `install-aet-binaries`: it links `aet` into `AET_BIN_DIR` (default `~/.local/bin`), prunes all seven AET-managed legacy symlinks (`aet-work`, `aet-state`, `aet-retro`, `orchestrator`, `mine-learnings`, `configure-task-backend`, `install-aet-binaries`), and warns when the bin dir is missing from PATH — editing shell profiles stays manual, the one honest bootstrap step. The standalone `aet-setup/bin/install-aet-binaries` script is deleted; `aet-setup` prose and the Makefile bootstrap by path (`<skills-root>/aet-work/bin/aet install`). No alias, no shim, no deprecation window (owner decisions at the gate, 2026-07-11). Deletion and pruning ship in the final task of the phase (flip); until then the old names stay untouched and fully functional so every intermediate merge stays green.
- **R-6**: Every wrapped binary exposes its ArgumentParser via a `build_parser()` function (`parse_args` refactored to call it); behavior identical. This is what makes "parse against the real argparse tree" literal rather than aspirational.
- **R-7**: skills-lint v1 (`scripts/skills-lint`, wired into `make validate`): extracts every `aet …` invocation from code spans (fenced blocks and inline code) in packaged skill markdown (`aet-*/**/*.md`) and project scaffolding (`.agents/templates/*.md`, `.agents/commands/*.md`, `AGENTS.md`), and validates each against the real parser tree — unknown subcommand or unknown flag fails the build. Placeholder tokens (`<…>`, `{…}`, `…`, `$VARS`) are treated as opaque values. An explicit escape marker pair (`<!-- aet-lint: off -->` / `<!-- aet-lint: on -->`) exempts deliberately historical content (e.g. migration docs).
- **R-8**: skills-lint also fails on any legacy entry-point reference in linted files: command-position `aet-work`, `aet-state`, `orchestrator`, `aet-retro`, `mine-learnings`, `configure-task-backend`, `install-aet-binaries`, or `aet-*/bin/…` path invocations — except paths ending in `aet-work/bin/aet` (the binary itself; by-path bootstrap invocations are `aet` invocations and are lint-validated like any other) and escape-marked blocks. The rule ships warn-only and flips to error in the rewrite task — from then on it _is_ the "deleting the old names breaks nothing" gate, standing in CI.
- **R-9**: Every reference is rewritten to the `aet` surface — skill SKILL.md files, `references/` docs, `.agents/templates/`, `.agents/commands/`, `AGENTS.md`, `README.md`, `docs/CONVENTIONS.md` — and the runtime hint strings printed by the binaries themselves (e.g. in `src/aet/queue.py`) say `aet …`, so agents are never taught a legacy name at runtime.
- **R-10**: Tests: dispatcher routing (each subcommand reaches its target; run/run-one mapping; missing-sibling error; unknown subcommand exit 2), `aet install` behavior (fresh link, stale-link repair, legacy prune, idempotency — against a temp bin dir), self-repair on invocation, `build_parser()` importability for all twelve bins, `status --json` schema assertions, and skills-lint fixtures (valid invocation passes; unknown subcommand/flag fails; legacy name fails when strict; escape marker skips). `make validate` green demonstrates the exit gate mechanically.
- **R-11**: `aet` is self-maintaining on PATH: every invocation cheaply verifies its own symlink (one readlink) and silently repairs a missing or stale link, so toolkit updates never require re-running an installer — new subcommands dispatch internally and travel with the file. Multi-checkout resolution keeps today's semantics: the copy invoked wins; `AET_SKILLS_DIR`/`AET_BIN_DIR` override for dev. Repair never edits shell profiles and never touches non-AET files.

## User Stories

- As the owner, I run every toolkit operation through one command — `aet status`, `aet run-one <plan>`, `aet ship <task> <plan>` — instead of remembering which of six PATH names owns which verb (satisfies: R-1, R-2, R-5).
- As an agent following a skill, every command the skill teaches me parses and executes, because the skill could not have merged otherwise (satisfies: R-6, R-7, R-8).
- As a skill author, I get a CI failure the moment my prose references a flag that does not exist or a binary name that is retired — not a production incident weeks later (satisfies: R-7, R-8).
- As the Phase 4 implementer, I build `aet desk` on `aet status --json` instead of inventing a read surface (satisfies: R-4).
- As the Phase 3 implementer, I add `aet gate submit` as one more row in the spec table, and skills-lint covers it from the first mention (satisfies: R-3).
- As a user on a fresh machine or harness, my only bootstrap is one by-path `aet install`; from then on the binary maintains its own PATH link and toolkit updates never ask me to re-run an installer (satisfies: R-5, R-11).

## Acceptance Criteria

- [ ] `aet add|review|status|next|sync|report|init-queue|run|run-one|state|ship|retro|mine-learnings|configure-backend|install` each execute correctly — the wrapped ones with behavior identical to their underlying binary; `aet <unknown>` exits 2 with a usage listing; a missing sibling skill produces an error naming it (satisfies: R-1, R-2).
- [ ] `aet status --json` emits the documented schema and parses with `python3 -m json.tool`; human output unchanged (satisfies: R-4).
- [ ] Inserting `aet statuz` or `aet status --bogus` into any SKILL.md turns `make validate` red; the same invocation inside `aet-lint: off` markers does not (satisfies: R-7).
- [ ] After the rewrite task: zero legacy entry-point references in packaged skill content and scaffolding outside escape-marked blocks — enforced at error severity, so reintroducing `aet-work sync` in a skill fails the merge (satisfies: R-8, R-9).
- [ ] After cli-05: `aet install` against a bin dir yields exactly one AET link (`aet`) and prunes all seven legacy names; `command -v aet-work` finds nothing; `aet-work/bin/aet-work` and `aet-setup/bin/install-aet-binaries` no longer exist (satisfies: R-5).
- [ ] Deleting the `aet` symlink and invoking `aet` by path restores the link without user action; a stale link pointing at another checkout is repaired to the invoked copy; repair touches nothing but the AET-managed symlink (satisfies: R-11).
- [ ] The queue-guard hint (`src/aet/queue.py`) and all other runtime hint strings suggest `aet …` commands (satisfies: R-9).
- [ ] Every wrapped bin's `build_parser()` imports and returns an ArgumentParser in tests; dispatcher, lint, and `--json` components each have the named tests from R-10; `make validate` green (satisfies: R-6, R-10).

## Technical Notes

<!-- aet-lint: off -->
- **Ground truth (`f50d7b4`)**: frh-05 dispatcher at `aet-work/bin/aet-work` (exec-based, `DIRECT_COMMANDS` + `run`/`run-one` → orchestrator with `--queue-file`/`--plan-file` mapping) — `aet` grows from this file. Sibling resolution precedent: `aet-ship/bin/ship:31` (`Path(__file__).resolve().parent.parent.parent / "aet-work" / "bin" / "aet-state"`). `aet-state` subparsers: audit, heal, validate, transition, set-stage, record-merge (`aet-work/bin/aet-state:808+`). Orchestrator argparse at `:206` (`--queue-file`/`--plan-file` mutually exclusive group, `--repo-root`, `--cli-bin`, `--isolation`, `--max-jobs`, `--task-timeout`). `bin/status` currently has no `--json`. Installer allowlist + prune logic: `aet-setup/bin/install-aet-binaries:28-33,113-126`. Legacy runtime hint: `aet-work/lib/queue.py:397`. Existing test to extend: `tests/test_aet_work_dispatcher.py`.
- **Spec table shape**: an importable module-level structure in `aet-work/bin/aet` (name → target relpath + dispatch mode; `run`/`run-one` are the only mapped modes, everything else verbatim exec). skills-lint imports the binary via `importlib.util.spec_from_loader` + `SourceFileLoader` (the bins have no `.py` extension — the technique `tests/test_aet_state.py:13-17` already uses), reads the table, then imports each target's `build_parser()` and validates flags via `parser._actions` option strings and subparser choices.
<!-- aet-lint: on -->
- **Lint extraction**: fenced code blocks (` ```bash`, ` ```sh`, ` ```console `, and unlabeled) plus inline code spans; lines shlex-split; a token stream starting with `aet` is validated. Opaque tokens: `<…>`, `{…}`, `…`, `$VAR`/`$(…)`. Legacy rule matches command-position names and `aet-*/bin/…` paths only — prose mentions of file paths or concept names are not invocations and do not match.
- **Sequencing (additive-then-flip, every merge green)**: cli-01 (multicall dispatcher; old dispatcher and standalone installer untouched, not shimmed) ∥ cli-02 (build_parser × 12 + `status --json`) → cli-03 (lint, legacy rule warn-only — the tree still contains legacy references); cli-04 (`aet install` + on-invocation self-repair; split from cli-01 by the session-size guardrail) follows cli-01, parallel-safe with cli-03 → cli-05 (rewrite sweep incl. Makefile + flip legacy rule to error + delete `aet-work/bin/aet-work` and `aet-setup/bin/install-aet-binaries` + prune all seven legacy names) closes the phase. Skills keep working at every intermediate commit; `aet` exists and is linted before any skill references it; the old names stay functional only until the merge that removes their last reference — no deprecation window survives the phase.
- **Rewrite contract is a grep, not a file list**: the P1 (wfd) arc is merging while this phase waits and may add references (e.g. `validate-workflows` mentions); cli-05 enumerates its surface at implementation time. Known today: ~16 markdown files across `aet-work`, `aet-plan`, `aet-ship`, `aet-evolve`, `aet-setup`, `aet-validate-scope`, `aet-pipeline-plan`, plus `.agents/templates/plan-template.md`, `.agents/commands/`, `AGENTS.md`, `README.md`, `docs/CONVENTIONS.md`, and binary hint strings. `aet-work/references/migration-aet-state.md` documents old names deliberately → escape markers.
- **CI**: this repo's CI is `make validate` (+ pre-commit); skills-lint lands as `scripts/skills-lint` invoked there, beside wfd-04's `validate-workflows`.
- **Queue interaction**: the wfd batch may hold the run lease (frh-17) when plans are added; `aet-work add` uses the locked write path — if the lease rejects the mutation, the add step waits for batch completion and is re-run.
- Intake triage: enhancement — no reproducible defect; classification recorded here.
- Sizing: 5 plans (`cli-01…05`) vs the roadmap's ~3 — the lint and the flip split so the legacy rule lands warn-only first, and `aet install`/self-repair split out of cli-01 at story breakdown (dual-limit guardrail; `Split from: cli-01` recorded in cli-04); every task is parallel-batch-safe within its `blocked_by` edges.

## Open Questions

None blocking. **Resolved at the gate (2026-07-11, owner)**: no backward compatibility or deprecated functionality — the `aet-work` transition alias is rejected; clean cut in cli-05 (dispatcher and standalone installer files deleted, all seven PATH names pruned). And the manual bootstrap pain is dissolved rather than kept: `aet install` + on-invocation self-repair replace `install-aet-binaries` (owner gate feedback: it confused multiple times); other AET-consuming repos re-run `aet-upgrade`/`aet install`.

Remaining flagged choices:

1. **`configure-task-backend` surfaces as `aet configure-backend`**; bootstrap is a single by-path `aet install` — the only moment AET is ever invoked by path.
2. **`status --json` schema kept minimal v1** (per-task id/state/stage/blockers + summary counts); the Phase 4 desk is the first real consumer and extends it then.
3. **Phase ordering via queue edges**: cli-01/cli-02 are `blocked_by` wfd-04, so P1 → P2 ordering is enforced by the queue in one batch, exactly as P0 → P1 was.

## Divergence Summary

_Recorded: 2026-07-12 — Branch: cli-03-skills-lint_

### Changed from plan

- None — `scripts/skills-lint`, both rules, Makefile wiring, and the test suite landed as planned (Makefile line placed after `validate-workflows`, per the plan's "wherever wfd-04 left the target" allowance).

### Added (unplanned)

- Escape markers in `aet-pipeline-plan/SKILL.md` around the future `aet plan validate` reference — the real-tree integration check (`skills-lint --legacy=warn` exits 0) required exempting this forward reference; the file was not in the plan's Files to Modify.

### Deferred

- Plan task 5 (merge branch to main + integration verify) — runs at `aet-ship`; additive-then-flip batching keeps the merge as a separate stage.

---

_Recorded: 2026-07-12 — Branch: cli-05-legacy-retirement-sweep_

### Changed from plan (cli-05)

- None — the reference sweep, runtime-hint rewrite, deletions, Makefile bootstrap rewiring, unconditional prune, and `--legacy=error` flip all landed as planned; the sweep surface extended to example/panel files (`aet-release-prep/examples/minor-release.md`, `aet-setup/examples/*`, `aet-work/examples/README.md`, `aet-work/panel/README.md`) exactly per the plan's grep-at-implementation-time contract.

### Added (unplanned, cli-05)

- `aet-evolve/bin/aet-retro`: `mine-learnings` invocation switched from PATH lookup to direct sibling-binary resolution — required by the unconditional prune, which removes the legacy `mine-learnings` PATH name; regression coverage in `tests/test_aet_retro_telemetry.py::TestRunMineLearningsInvocation`.
- `tests/test_aet_dispatcher.py`: legacy-parity tests rewritten as direct argv assertions (the legacy dispatcher they compared against is deleted by this task).

### Deferred (cli-05)

- Plan task 5 (merge branch to main + integration verify) — runs at `aet-ship`; additive-then-flip batching keeps the merge as a separate stage.
- `PRODUCT.md` still lists `install-aet-binaries` as current functionality — outside the sweep's grep scope (flagged Info by aet-cso); owned by `aet-release-prep` at the next release.

---

_Stage: scope-validated_
_Validated: 2026-07-11_
_Next step: run `aet-work` (single-plan or multi-task queue)_
