# aet-setup Reference

Detailed reference material for the `aet-setup` skill.

## Generated Artifacts

When `/aet-setup` runs, it creates or updates the following artifacts.

### 1. `AGENTS.md` (root)

The most important file. Keep it under 200 lines. Contains:

- Project overview and stack
- Architecture pattern and layer rules
- Directory structure
- **AI Guardrails** section with explicit Forbidden and Mandatory lists
- **Agentic Workflow Guardrails** — PRD-first, plan-first, session separation rules
- **Context Budget** — context window discipline for the project
- Tooling reference (what runs where)
- **Reference Docs (load on demand)** — table pointing to `docs/references/*.md`
- Decision log (brief, high-level)

### 2. `docs/CONVENTIONS.md`

Human-readable patterns:

- Project structure and naming conventions
- Code style rules
- Testing conventions
- Error handling patterns
- API conventions (if applicable)

### 3. `.agents/` directory

Agent-neutral home for workflows, templates, and persistent state:

- `.agents/commands/README.md` — how command workflows work
- `.agents/commands/approval-checkpoint.md` — hard gate between design and implementation
- `.agents/smoke/` — session-level smoke checks and last-run record
- `.agents/templates/*.md` — PRD, plan, retro templates
- `.agents/validation-commands.json` — authoritative validation commands (calibrated during setup)
- `.agents/learnings.jsonl` — persistent learning log
- `.agents/work-history.jsonl` — settled task records (ignored by git)
- `.agents/ledger.jsonl` — content-addressed provenance ledger
- `.agents/.gitkeep`

Ensure `.gitignore` excludes generated agent workflow artifacts:

```gitignore
# Active/draft plan scratch
docs/plans/active/
.agents/work-history.jsonl
.agents/runs/
.worktrees/
```

### 4. `.agents/aet-config.json` (queue config)

Created by `aet configure --guided` during `aet-setup` Step 6. Sets the integration mode used by aet-work:

```json
{
  "integration_mode": "pr-per-task"
}
```

- `integration_mode`: `pr-per-task` (default) or `single-pr`.

There is no store to choose: `git-refs` is the only one. The `task_backend` key was removed in 1.10 and a config still carrying it is reported and ignored.

Use `--scope team` to write the config into `.agents/aet-config.json` (committed with the repo) or `--scope shadow` to write it to `~/.aet/{slug}/config.json` (nothing committed). The guided flow asks these two questions interactively.

GitHub Issues mirroring is configured on the `projections` axis. A forge is a projection, never a task store:

```json
{
  "integration_mode": "pr-per-task",
  "projections": [
    { "type": "github", "repo": "owner/name", "label_prefix": "aet" }
  ]
}
```

- `projections`: list of one-way mirrors. Each entry has `type` and type-specific keys.
- `projections[].repo`: repository for the GitHub Issues projection, `owner/name`.
- `projections[].label_prefix`: defaults to `aet`; all state labels use this prefix.

The projection dispatcher catches projection failures and warns on stderr; storage writes remain fail-closed.

See `aet-work/references/github-backend.md` for the label contract, `gh` CLI requirements, issue body format, and GitHub-to-local sync behavior.

### 5. `docs/references/` directory

Task-specific reference documents loaded on demand by the agent. Keep each focused and link to it from the root agent-context file (`AGENTS.md`, `CLAUDE.md`, etc.):

- `docs/references/README.md` — how to use reference docs
- `docs/references/api-conventions.md` — API patterns, error handling, auth
- `docs/references/testing-strategy.md` — test patterns, factory usage, coverage
- `docs/references/security-guidelines.md` — secrets handling, input validation, trust boundaries
- `docs/references/ui-conventions.md` — UI component priorities and design-token alignment
- `docs/references/worktree-ship-hygiene.md` — merge-base checks and PR scope red flags

### 6. `docs/` subdirectories (created by individual skills)

Each skill creates its own folder under `docs/` when it first produces an artifact:

- `aet-plan` → `docs/prds/` and `docs/plans/`
- `aet-evolve` → `docs/retros/`

`aet-setup` does **not** pre-create these. Skills own their own directories.

### 7. Tool configs

Linter, formatter, type checker, security scanner configs tailored to the detected stack.

### 8. Root orchestration

`Makefile` or `justfile` with targets: install, dev, test, lint, format, type-check, security-audit, clean

### 9. ADR template

`docs/adr/000-template.md` and `docs/adr/README.md`
