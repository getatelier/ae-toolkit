# AE Toolkit Conventions

This document defines the patterns and standards for authoring, editing, and maintaining skills in this repository.

---

## Project Structure

Each skill lives in its own directory under `skills/`:

```
skills/<skill-name>/
├── SKILL.md              # Required. Skill instructions (YAML frontmatter + markdown body)
├── examples/             # Required. Usage examples and sample outputs
│   └── README.md
└── references/           # Required. Detailed reference material, edge cases, deep dives
    └── README.md
```

Skills are installed together from this repository via `npx skills add ... --all`. The pipeline only works when the whole system is present.

## Maintenance Scripts

`scripts/` contains repository-maintenance tooling: validation scripts, git
hooks, and release guards. One-off data migrations that have already been
applied are archived in `scripts/archive/` with a README explaining the release
they shipped in. Do not add new migrations to the root of `scripts/`; either
archive them after use or turn them into reusable maintenance scripts.

### Validate Gate

`make validate` is the repo's only safety net. It runs every check, fail-fast.
When a change touches nothing but prose, pytest is skipped entirely; the
remaining lint stages still run. This fast path is safe only because no test
module reads Markdown from the checkout outside `tests/`. Any new test that
does so will fail the regression guard in `tests/test_change_scope.py`.

For code changes, `make validate` asks `src/aet/change_scope.py` for the
smallest safe set of pytest targets, and `change_scope` derives them from the
source: `src/aet/test_deps.py` reads which test files reference which modules —
by import or by the quoted-path idiom that feeds `SourceFileLoader` — and
follows those references transitively, so a test driving an entry point counts
for everything that entry point reaches. Nothing is hand-maintained, and no
target is named that does not exist.

Selection **fails toward the full suite**: any `conftest.py`, shared fixture,
undetermined diff, or code path no test reaches returns `tests/` rather than
risk a silent skip, and a change reaching most of the suite is reported as the
full suite rather than as a long file list.

The installer smoke test (`tests/installer/test_installer.py`) is included when
`scripts/install.sh` changes, because the test names the script, and when
`src/aet/cli/setup.py` changes, because `test_deps.BOUNDARY_EDGES` declares it.
That declaration is for coverage crossing a boundary the source cannot show — a
test driving a shell script that invokes the CLI exercises the Python behind it
while naming neither the module nor anything that imports it. Entries need a
reason; `tests/test_change_scope.py` fails when one names a file that moved, and
when a source file no test reaches is not on the acknowledged list.

### Documentation Lint Escape Markers

When prose must deliberately mention retired paths, historical commands, or code
patterns that violate documentation governance rules (such as migration guides
or historical citations in PRDs/ADRs), wrap the exempt span in escape markers:

```markdown
<!-- aet-lint: off -->
Deliberately unmigrated reference or historical command.
<!-- aet-lint: on -->
```

Both `scripts/skills-lint` and `aet docs lint` (`src/aet/docs_lint.py`) honour
these markers and strip escaped spans before rule evaluation. An unclosed `off`
marker (`<!-- aet-lint: off -->` with no subsequent `<!-- aet-lint: on -->`)
treats the exemption as running through to the end of the document.

## Package-Deliverable Rules

AE Toolkit is installed together, not à la carte. Skills may reference shared conventions, cross-skill rules, and toolkit-level docs because the whole system is present at runtime.

Rules:

- Put rules that are specific to one skill inside that skill's files (`SKILL.md`, `references/`, `examples/`, or scripts in `<skill>/bin/`).
- Put cross-cutting rules in toolkit-level docs (`.agents/reference/`, `AGENTS.md`, `docs/CONVENTIONS.md`).
- It is fine for a skill to reference another skill or a shared convention by name (e.g., "run `aet-validate-scope` next"). Do not rely on hardcoded paths that assume a specific install location.
- If a rule must be visible to an agent that reads only the skill file (e.g., when a skill is pasted into chat), include the essential version of that rule directly in `SKILL.md` or link to a skill-level reference doc.

## Skill Binaries

Skills are pure content (markdown instructions, examples, and references). All executable helpers have been extracted into importable Python modules under `src/aet/cli/<name>.py`. There are no executable scripts inside skill directories.

Rules:

- Skill instructions must invoke helpers through the `aet` dispatcher (e.g. `aet state record-merge`), not by hardcoded agent-specific paths or retired binary names.
- Skills that depend on helpers must include a **Prerequisites** section telling the user how to install the `aet` dispatcher onto `PATH`.
- `aet setup link` requires the `aet` Python package to be installed first. Skill installers must not assume that `npx skills` (which copies markdown content) installed the package; document `pip install` from the repo or PyPI as the prerequisite step.
- The canonical installer is `aet setup link`, implemented in `src/aet/cli/setup.py` and exposed through the installed console script (`aet = "aet.cli:main"`). It symlinks `aet` into `~/.local/bin` (or `AET_BIN_DIR`).
- `make install-skills` in this repo installs the package editable and runs `aet setup link` automatically for the local development workflow.

## AET Configuration

`aet-work` reads its integration config through an external-first
precedence chain so that AET can run without committing any AET _config_ to a
shared repo. ADR-048 records the two-layer model and the rename from the legacy
`.agents/aet-work.json` file.

### Resolution Order

Config is resolved in this order; the first source that exists wins:

1. `AET_WORK_CONFIG` environment variable (path to a JSON config file)
2. `~/.aet/{config-slug}/config.json` (shadow / personal layer)
3. In-tree `.agents/aet-config.json` (team layer)
4. Built-in defaults (`{"trunk_branch": null, "integration_branch": null, "integration_mode": "pr-per-task"}`)

`{config-slug}` is the main-worktree identity derived by `derive_config_slug()`;
it drops the worktree label so one personal config serves every linked worktree
of the same repo. `AET_PROJECT_ID` or `AET_REPO_SLUG` override the derived slug.
The in-tree file is resolved against the repository root
(`git rev-parse --show-toplevel`), never the process cwd.

### Adoption Modes

| Mode   | Where config lives                    | Best for                                        |
| ------ | ------------------------------------- | ----------------------------------------------- |
| Team   | `.agents/aet-config.json` (committed) | Whole team shares one backend/mode setup.       |
| Shadow | `~/.aet/{config-slug}/config.json`    | Solo adoption on a shared repo; zero footprint. |

A project nobody has configured is **local (shadow)** by default; no command
pushes `refs/aet/*` or creates committed AET artifacts. Use `aet configure --shared`
as the explicit one-command way to declare a project shared across devices; it
writes `.agents/aet-config.json` and sets `integration_mode` to `pr-per-task` if
not specified. `--scope project` is the same writer for direct, non-declarative
writes, and `--scope user` writes the shadow file.

Use `aet configure --guided` to choose the mode and integration mode in two
questions; the command writes the file in the right place with valid values.
Guided mode exposes the same choice as `--scope team|shadow`.

### Shadow Mode Setup

Keep AET config out of the repo entirely:

```bash
aet configure --guided --scope shadow --integration-mode pr-per-task
```

This writes config to `~/.aet/{config-slug}/config.json` and touches nothing
inside the repo. Plans, PRDs, and other project artifacts remain versioned in
`docs/` as usual; only the AET backend/mode config leaves version control.

### Team Mode Setup

For self-hosted or team-wide AET adoption, commit the config in-tree:

```bash
aet configure --guided --scope team --integration-mode pr-per-task
```

This writes `.agents/aet-config.json`. Because reads are external-first, an
external config (if present) will still take precedence.

### Upgrading from the Legacy File

If the repo contains only the legacy `.agents/aet-work.json` file, any
config-reading command fails closed and names the migration command:

```bash
aet configure --migrate
```

`--migrate` renames the file to `.agents/aet-config.json` (using `git mv` when
the file is tracked) and refuses to overwrite an existing new file.

### Branch / Integration Model

Three settings control how AET maps tasks to branches and merges. Config values
are resolved external-first.

| Setting              | Meaning                                                                 |
| -------------------- | ----------------------------------------------------------------------- |
| `trunk_branch`       | The final merge target for every task (e.g., `main`, `master`).         |
| `integration_branch` | The parent branch for feature work and the base for stacked work.       |
| `integration_mode`   | `pr-per-task` (default) or `single-pr`.                                 |

`aet setup verify` prints the resolved `trunk_branch`, `integration_branch`, and
`integration_mode` with provenance — `config`, `detected` from
`refs/remotes/origin/HEAD`, or `fallback` to `main`.

#### Resolution Order

**`trunk_branch`** is resolved in this order:

1. `trunk_branch` in config
2. `git symbolic-ref refs/remotes/origin/HEAD`
3. Fallback to `main`

**`integration_branch`** is resolved in this order (in `single-pr` mode):

1. `--base` CLI flag (`cli_base`)
2. `AET_WORK_BASE_BRANCH` environment variable
3. Task record stamp (`task["integration_branch"]`)
4. Parent document declared branch (`branch` in PRD frontmatter)
5. Envelope active epic (`aet epic set` / `read_epic()`)
6. PRD filename stem fallback
7. `integration_branch` in config
8. `trunk_branch` fallback (via the same trunk resolution above)

In `pr-per-task` mode, steps 3–6 are skipped, preserving Scenario A as the degenerate case.

**`integration_mode`** is resolved from config only; it defaults to `pr-per-task`
and must be one of `pr-per-task` or `single-pr`.

This is a branch/integration model, not a worktree model. Worktrees are a
mechanical implementation detail; the integration branch is the semantic input.

#### Scenario: One Engineer, Shared Repo, Plans on a Feature Branch, `single-pr`

You want to keep all plan updates on one feature branch and ship them through a
single PR, while still using AET's queue and state machine locally.

1. Configure `single-pr` mode (e.g. in shadow config so the repo stays free of AET config):

   ```bash
   aet configure --guided --scope shadow --integration-mode single-pr
   ```

2. Declare the active epic branch, title, and PR body:

   ```bash
   aet epic set docs-roadmap --title "Docs: Roadmap implementation"
   ```

3. Run tasks against the declared epic:

   ```bash
   aet run
   ```

   `aet-work` uses `docs-roadmap` as the worktree base, stamps tasks at intake,
   and integrates tasks locally into `docs-roadmap`.

4. Open the epic pull request targeting trunk:

   ```bash
   aet ship open-epic
   ```

## Planning Artifact Directories

The `docs/` directory has strict boundaries for planning documents. Only atomic, implementable task plans may live in `docs/plans/active/` (or legacy `docs/plans/`); all other planning artifacts belong in their designated directories.

| Directory             | Purpose                                                                          | Queue Ingestion                                           |
| --------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `docs/plans/active/`  | Active, in-progress task plans (single session). Untracked / gitignored by default. | Yes — admitted to the board via `aet sprint add` / `backlog add` |
| `docs/plans/archive/` | Settled plans moved at closure. Versioned by default (or optionally ignored).    | No                                                        |
| `docs/prds/`          | Product Requirements Documents                                                   | No                                                        |
| `docs/roadmaps/`      | Multi-phase roadmaps, completion trackers, meta-plans                            | No                                                        |
| `docs/audits/`        | Testing audits, strategy reviews, gap analyses                                   | No                                                        |
| `content/backlog/`    | Known-but-unstarted items: accepted debt, undecided ideas, multi-phase roadmaps. One file per item, indexed by `content/backlog/README.md`. **Local and untracked** — `content/` is gitignored | No                                                        |

Rules:

- Plans are authored in `docs/plans/active/<id>.md`. At terminal closure (`aet ship close` and `aet ship merge`), if present locally, they are archived to `docs/plans/archive/<id>.md` and staged into git if `docs/plans/archive/` is tracked. If absent (e.g. multi-agent/worker environments), closure logs an informational notice and succeeds without error.
- A document in `docs/plans/active/` or `docs/plans/` that references other plan files or contains multiple "Phase" sections is non-atomic and must be moved to `docs/roadmaps/` or `docs/audits/`.
- The task-list-length check is no longer an intake filter; plan size is measured after implementation, not gated before it (see ADR-046). A plan that is genuinely non-atomic belongs in `docs/roadmaps/` or `docs/audits/` by the ADR-006 atomicity boundary, not because a proxy count rejected it.
- An item that is known but not started — accepted debt, an idea nobody has decided on, a roadmap whose tracks are unplanned — belongs in `content/backlog/`, one file per item with a `trigger` in its frontmatter. That folder lives under gitignored `content/`, so it is working state on one machine rather than a repository artifact; a reference to it from a tracked document will not resolve in a fresh clone. An item leaves the folder by becoming a PRD or by being deleted. `docs/roadmaps/` remains the ADR-006 destination for non-atomic planning _output_; the two are not the same thing.
- Directory creation is the user's responsibility; skills document the convention but do not auto-create directories.

## Plan Frontmatter Contract

Every atomic plan file in `docs/plans/active/` (or legacy `docs/plans/`) must begin with YAML frontmatter:

```yaml
---
id: { ticket-id }
size: S/M/L
blocked_by:
  - { blocker-id }
---
```

- `id` must match the plan filename stem and be unique within the PRD family.
- `blocked_by` is the authoritative dependency list; prose dependency sections are ignored by `aet queue sync`.
- `size` is the S/M/L complexity label from the guardrail model.
- `stage` lives only in the task record, never in plan frontmatter.

`aet queue sync` validates the contract and fails closed on missing or duplicate IDs, unknown blockers, mismatched filenames, or invalid size values.

## SKILL.md Format

### YAML Frontmatter

Every `SKILL.md` must begin with YAML frontmatter:

```yaml
---
name: skill-name
description: Explicit trigger description. When to use this skill. What user requests should activate it.
---
```

Rules:

- `name` must match the directory name.
- `description` is the trigger. Be explicit about invocation conditions (e.g., "Use when the user asks to create a skill, update a skill, or write skill instructions").
- No other frontmatter keys unless justified.

### Body Structure

1. **H1 Title** matching the skill name.
2. **When to Use** — bullet list of explicit trigger situations.
3. **Instructions** — procedural steps the agent must follow. Use imperative voice.
4. **Examples** (optional) — if present, keep brief and link to `examples/README.md` for full samples.
5. **Rules** (optional) — hard constraints ("Never...", "Always...").

Length: Keep `SKILL.md` under 400 lines. Move deep detail to `references/`.

## Writing Style

- **Imperative voice:** "Scan the project", "Research best practices", "Run the test suite".
- **Explicit triggers:** The `description` and "When to Use" section should make invocation unambiguous.
- **No agent assumptions:** Skills must work with Claude, Kimi, Cursor, Codex, or paste-into-chat. Do not reference tool-specific syntax unless unavoidable.
- **Concise over verbose:** Agents have context windows. Every sentence should carry instructions, not fluff.

## Naming Conventions

- Skill directories: kebab-case (`aet-setup`, `aet-validate-scope`).
- Files inside skills: `SKILL.md`, `README.md` (examples/references).
- ADR files: `NNN-title-in-kebab-case.md`.

## Error Handling

- If a skill cannot complete its task, it must explain why and what the user should do next.
- Never silently skip a step because a file is missing; document the skip in output.

## Task Size Guardrails

All planning output must be implementable in a single agent coding session. Use the context-budget + coherence model to shape the plan; the actual diff size is measured at closure, not guessed at intake (see ADR-046).

### Guardrail Model

A plan/task is a candidate for splitting when **two or more** of the following signals are true. One tripped signal is a prompt to justify the shape in writing, not an order to split.

1. **Expected diff guidance** (skill-level only, not validator-enforced):
   - Task: > 600 expected diff lines.
   - Story: > 1,200 expected diff lines.
2. **Human-time sanity check** (skill-level guidance, not validator-enforced):
   - Story: > 2 human-days.
   - Task: > 1 human-day.
3. **Subsystem coherence** (skill-level guidance):
   - Touches files in more than 2 distinct implementation subsystems. A _subsystem_ is a bounded module or layer with its own ownership boundary — in this repo, for example: `src/aet/` (CLI code + its tests), `skills/` (skill content), `.agents/` (workflow infrastructure). `docs/` changes and the tests that belong to a code change do not count as additional subsystems; code + its tests are one concern.
   - Requires maintaining more than one major architectural invariant at a time.
4. **Context budget** (skill-level guidance):
   - Loading the plan + all files to modify + relevant tests would exceed ~60k tokens for a task or ~100k tokens for a story.

No plan-time proxy for diff size is enforced at intake. Two proxies have been measured and retired: file count, and task-list length. The latter correlated with delivered code diff at only **r = 0.30**, with a flat relationship past roughly six task-list lines, so `validate_size()` no longer rejects on task-list length. See ADR-046 for the full measurement and the decision to move size measurement to closure.

### Size Labels

Every task must carry an S/M/L label. A label is an advisory prediction calibrated against measured delivery, not an intake limit.

| Label | Human Time             | Expected Diff Lines |
| ----- | ---------------------- | ------------------- |
| S     | ≤ 2 hr                 | ≤ 150               |
| M     | ≤ 1 day                | ≤ 600               |
| L     | > 1 day OR > 600 lines | — justify above 1500 |

An L task must be re-evaluated against the full model above and is split only if it actually exceeds a limit.

### Auto-Split Rule

When a task exceeds two or more signals from the model:

1. Split along vertical-slice boundaries (behavior, entity, layer, or subsystem).
2. Re-evaluate each child against the full model. Repeat recursively.
3. **Max split depth = 3.** If a child still fails, mark it `⚠️ ATOMIC OVERSIZED` and surface for explicit user approval.
4. Document splits with `Split from: {parent-id}` and suffix IDs (`01a`, `01b`).

### Floor Test

The opposite mistake is also possible: splitting a coherent feature into plans that are each too small to justify their own per-task pipeline. A plan/task is a candidate for merging with a sibling when **two or more** of the following signals are true. One tripped signal is a prompt to justify the shape in writing, not an order to merge.

1. **Expected diff below the calibrated floor threshold** (skill-level guidance):
   - Task: expected diff ≤ 50 headline lines.
   - _Basis:_ measured across 7 settled `S` tasks in this repo via `plan_size.delivered_size`, the smallest non-zero delivered headline diff was 45 lines (median 262, range 0–465). The threshold is rounded to the nearest 10 from that observed minimum, not guessed as half the `S` ceiling. See ADR-046 for the measurement model.
2. **Subsystem coherence** (skill-level guidance):
   - Touches files in exactly one implementation subsystem and maintains no architectural invariant.
3. **Files to Modify overlap with a linearly-ordered sibling** (reported by `aet plans lint`):
   - More than 50% of the smaller plan's `Files to Modify` set overlaps with a sibling it is linearly ordered against (`blocked_by` that sibling, or blocked by it transitively).
4. **Docs-only with a single sibling as its sole consumer** (reported by `aet plans lint`):
   - Every file in `Files to Modify` is under `docs/`, and exactly one sibling lists this plan in its `blocked_by`.

The cost unit is **per-task stage sessions**, not branch/PR/review overhead. Under ADR-045 §4, per-task branches are ephemeral and local in `single-pr` mode, and there is one PR per epic. What remains is the per-task stage pipeline — each task runs its own worktree seed plus `tdd`/`implement`/`qa`/`review`/`cso`/`sync-docs` sessions with verdicts — and telemetry already records `token_count` and `cost_estimate` for each stage.

When two or more signals are true, merge the work into a sibling plan instead and record the rationale. This check is advisory — it prompts a written justification, it does not block at scope validation.

## Recorded-Forward Work Queue State

Workflow state is recorded at transition time and trusted on read.

- `aet state transition` is the only writer of `tasks[].state`.
- `aet status`, `aet next`, and the orchestrator read stored `state` directly and make zero git calls on the read path.
- `aet state audit` reconciles stored state against git ground truth on demand; it never runs during normal operation.
- The `git-refs` backend stores queue state in `refs/aet/*` and pushes/fetches from origin; there is no non-git task store.

### Legal Transitions

```text
sync:        ∅ → planned
sync:        planned → blocked            (pending_blockers > 0)
sync:        planned → ready              (pending_blockers == 0)
transition:  blocked → ready              (last blocker reached terminal)
transition:  ready → in_progress          (branch + worktree recorded)
transition:  in_progress.stage advances   (tdd → implement → qa → review → cso → sync-docs)
transition:  in_progress → awaiting_merge (pipeline exited 0; NOT terminal)
transition:  awaiting_merge → merged      (TERMINAL; merge_commit verified once)
transition:  any → abandoned (reason)     (TERMINAL)
transition:  in_progress → failed         (needs inspection; may re-enter)
```

Terminal states are `merged` and `abandoned`. Only terminal states satisfy blockers; `awaiting_merge` does not.

### Live / Settled Partition

The `git-refs` backend stores only non-terminal tasks in `refs/aet/tasks/*`. When a task reaches a terminal state, the writer appends its final record and history to `.agents/work-history.jsonl` and drops the per-task ref atomically. Settled history is retained for auditability but is never loaded for scheduling.

## Base Hygiene

The orchestrator's pre-run hygiene check protects against building worktrees from a dirty or stale base. It is narrowed for plan paths but remains fail-closed for everything else.

Rules:

- Untracked or modified files under `docs/plans/` (including `docs/plans/active/`) are ignored by the dirty check and by the ahead-of-origin check. A local branch may be ahead of `origin/main` when every diverging path is in `docs/plans/`.
- Non-plan dirty paths still halt the run.
- A branch that is behind `origin/main` still halts.
- A mixed commit containing both `docs/plans/` and non-plan paths still halts.
- `aet sprint add` no longer has an `--allow-untracked` flag. Untracked plans in `docs/plans/active/` are the normal intake state; the durability write happens only at terminal closure (`merged`/`abandoned`).
- Untracked plans are load-bearing work in progress. `git clean -fdx`, git-following backups, or any process that discards untracked files can destroy queued/in-progress plans.

### Multi-machine state

Queue state travels with the repo via `refs/aet/*` on origin; a fresh clone must fetch it explicitly with `git fetch origin 'refs/aet/*:refs/aet/*'`. The Provenance Ledger and Execution Log are gitignored working-tree files with no transport. Config, telemetry, and reports stay machine-local in `~/.aet`. Offline work is safe; closure is the syncing boundary.

## Execution Mode

Skills with interactive approval gates must respect the execution-mode contract so they work correctly in both interactive sessions and unattended orchestration.

### Contract

```
Environment variable: AET_EXECUTION_MODE
  - unset or "interactive"  → Default. Hard gates enforced.
  - "unattended"            → Orchestrator/background mode. Gates bypassed with logging.
```

### Gate Bypass Protocol (Unattended Mode)

When `AET_EXECUTION_MODE=unattended` is detected at an approval checkpoint:

1. **List scope.** Still enumerate intended files and magnitude (audit trail).
2. **Log bypass.** Print exactly: `🤖 Unattended mode (AET_EXECUTION_MODE=unattended) — skipping interactive approval. Proceeding with: ~N files, ~M lines changed.`
3. **Continue.** Proceed to the next step; do not ask the user.

### Gates That Must Still Stop in Unattended Mode

Not all gates are bypassed. The following categories **must** halt execution even in unattended mode:

- **ATOMIC OVERSIZED tasks** — No human available to approve scope override. Hard stop with non-zero exit code.
- **Critical security findings** (`aet-cso` Critical/High) — Unattended mode must not auto-approve security risks.
- **Merge verification failures** (`aet-ship`, `post-ship-verify`) — Mechanical check; failure is a hard stop.
- **Autonomous merge** (an agent issuing a PR merge / `gh pr merge`) — The merge action is a human decision; skills are merge-neutral and must not instruct an agent to merge a PR. Fail-closed even in unattended mode (see ADR-029).

### Author Checklist

When adding a new approval gate to a skill:

- [ ] Gate checks `AET_EXECUTION_MODE` before prompting
- [ ] Unattended path logs the bypass with the exact emoji + wording above
- [ ] Gate is categorized as "bypassable" or "hard stop even in unattended mode"
- [ ] Autonomous-merge is fail-closed; skills never instruct a PR merge

## Branch Lifecycle

### Feature Branches

- Branch naming: `<task-id>` or `<type>/<task-id>-<slug>` (e.g., `waf-03-aet-ship-branch-lifecycle`).
- The actual branch name is stored in the work queue `branch` field.
- Feature branches are deleted locally **and remotely** after successful merge verification.
- Do **not** append post-merge commits (plan stage updates, review reports, release bumps) to a branch that has already been merged.

### Release Commits

- `chore(release)` commits and `VERSION` file bumps are **only allowed on `main`**.
- The pre-commit hook rejects release commits on non-main branches.
- `aet-ship` does not bump versions; release versioning is a future skill responsibility.

## Repository Hooks

Hook sources live in `scripts/hooks/`, but the **pre-push** hook is not symlinked by hand. Install it with the dispatcher, which generates a self-contained `.git/hooks/pre-push` shim:

```bash
aet hooks install
```

The **pre-commit** hook is still symlinked from `.git/hooks/`:

```bash
ln -s $(pwd)/scripts/hooks/pre-commit .git/hooks/pre-commit
```

### pre-push

The generated shim is self-contained — it needs no committed AET file, so it installs cleanly on a repo whose team does not use AET. On each push it:

1. Short-circuits (exits 0 immediately) when **all** pushed refs are branch deletions, so `git push origin --delete` is not blocked.
2. Runs the AET gate-evidence check (`aet hooks check`): for each pushed **task branch** (branch name matches a `docs/plans/<id>.md`), it refuses the push unless every required gate — `qa` and `review` always, `cso` unless `security_review: skipped`, `sync-docs` unless `docs_sync: skipped` — has a recorded `pass` verdict. Non-task branches are a no-op, and no build/coverage gate is imposed by AET itself.
3. Chains to the optional repo-local companion `scripts/hooks/pre-push` when that file is present and executable. In this repo the companion runs `make validate`; a repo that does not use AET omits it and the chain is skipped.

`aet hooks install` is idempotent and never clobbers a pre-existing non-AET hook — it warns and leaves it in place. Re-run it to regenerate a prior AET shim.

### pre-commit

Runs the AE Toolkit quality checks:

- **markdownlint** (`make lint`) on staged markdown files only
- **secrets scan** (via `pre-commit run`, which includes `detect-private-key`)

If the `pre-commit` framework is not installed, the hook falls back to `make lint`.

## Retired Document Paths

`docs/bugs/`, `docs/retros/`, `docs/audits/`, `docs/product-briefs/` and
`reports/` were removed on 2026-08-28, along with the root-level
`aet-toolkit-defects.md`. Every document in them was triaged first; what survived
is recorded as backlog items, and the documents themselves remain in git history.

Citations to those paths written before that date are historical provenance and
resolve in history rather than in a checkout. They are correct as records of what
motivated a decision and are not to be rewritten: an ADR is immutable once
accepted, and a stale path in a Status line is a weaker defect than an edited
decision record. Roughly eighty such citations exist, the ADR corpus included.

`~/.aet/reports/` is unrelated and live: it is the per-machine verdict archive
(`evidence.DEFAULT_REPORTS_DIR`), not the removed `reports/` directory.

## Cross-Project Feedback Channel

Projects that use the AE Toolkit may produce retros with findings relevant to the toolkit itself. These are surfaced through a defined `reports/` convention.

### Reports Directory

Each project maintains a `docs/retros/` directory (or equivalent) for retrospectives. Toolkit-relevant retros are marked and mined periodically.

### Toolkit-Relevant Marker

A retro is toolkit-relevant when its frontmatter includes:

```yaml
---
toolkit-relevant: true
---
```

### Required Sections

Every toolkit-relevant retro must contain:

- **Problem** — What went wrong, with concrete example
- **Root cause** — Why it happened (systemic layer, not individual mistake)
- **Fix** — What was changed in the project
- **Prevents** — What rule, check, or gate would have prevented it

### Mining Procedure

Run `aet-evolve --toolkit` periodically (monthly, or after every 5 retros) to scan `reports/*.md` files with `toolkit-relevant: true` and propose toolkit-level changes. See `aet-evolve/SKILL.md` for the full procedure.

The orchestrator writes execution telemetry directly to `~/.aet/telemetry/{project-slug}/{date}/{run-id}/`. Run `aet mine-learnings` periodically to scan the archive for recurring patterns (dependency issues, repeated loops, stage failures, review noise) and propose toolkit-level skill edits.

## Runtime Failure Handling

`aet run` accepts `--on-failure={triage|continue|halt}` (default `triage`). Skills and agents that invoke the batch runner may rely on this default, so new skills should document when they need a non-default mode.

`aet run` accepts `--max-jobs=<n>` (default `4`, maximum `8`) to control batch concurrency. `aet run-one` does not accept this flag.

### Failure taxonomy

All task failures are classified into one of five classes before routing:

- `environment` — missing tool/dependency, network, auth, or permission problem.
- `flaky` — non-deterministic test or transient runtime failure.
- `design` — assertion, lint/style, type, name, or syntax error.
- `timeout` — killed by wall-clock or silence timeout.
- `canceled` — killed by signal or orchestrator shutdown.

### Integration Failure

In `single-pr` mode, a rebase conflict or a post-rebase validation failure is an **Integration Failure** — an engine-level outcome, not a member of the five-class ADR-030 menu above. The task passed; the combination did not. Integration Failures are marked `failed` with an integration signature for human review, are never triaged as task failures, and do not increment the per-task circuit breaker.

- `triage` (default): spawn a triage session that emits `{class, action: requeue|quarantine}`. `requeue` transitions `failed → ready`; `quarantine` transitions to `quarantined`. An errored or unparseable verdict falls back to the nsr-01 default action.
- `continue`: mark `failed` and keep spawning new tasks.
- `halt`: mark `failed` and stop spawning new tasks.

The per-task circuit breaker overrides every mode: three identical signatures on one task always quarantine it.

## Test Parallelization

The orchestrator test suite runs under `pytest-xdist` with `--dist=loadgroup`.
Tests that contend for the same mutable resource are grouped so they serialize
on one worker; tests that contend for different resources run on different
workers concurrently.

When adding an orchestrator test that needs isolation, assign it to the
resource-scoped subgroup that matches the mutable resource it touches:

| Group name      | Shared resource it protects                              |
| --------------- | -------------------------------------------------------- |
| `process-group` | Real orchestrator subprocesses and process-group lifecycle. Files in this group may spawn the orchestrator CLI and rely on signal/process-group isolation. |
| `cwd`           | The process-wide current working directory (`os.chdir`, `monkeypatch.chdir`). |
| `telemetry-dir` | Telemetry archive paths and orchestrator state helpers that do not spawn heavy subprocesses or mutate git repos. |
| `git-repo`      | Temporary git repositories created and mutated by the test. |

Rules:

- Do not reintroduce the legacy monolithic `xdist_group("orchestrator")` marker.
- Place a test in the group of its most restrictive shared resource.
- The regression guard in `tests/orchestrator/test_xdist_groups.py` lists the
current file-to-group mapping and must be updated when a new orchestrator file
joins the grouped set.

## Versioning

Skills are versioned implicitly by git commit. No separate version field in frontmatter.
