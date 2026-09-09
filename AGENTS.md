# AE Toolkit Repository — Agent Context

## Project Overview

This is the source-of-truth repo for the **Agentic Engineering Toolkit (AE Toolkit)** — an integrated system of agentic engineering skills. Skills are directories with a `SKILL.md` file (YAML frontmatter + markdown instructions). They are designed to be installed together; the pipeline only works when the whole system is present.

## Stack

- **Content format:** Markdown with YAML frontmatter
- **Build / packaging:** GNU Make + `zip`
- **Quality:** markdownlint (staged/manual), ruff, pytest, custom skill-structure validator, workflow lint
- **Dev dependencies:** `pyproject.toml` optional-dependencies group `dev` (install with `pip install -e .[dev]`); runtime dependencies follow ADR-037

## Directory Structure

```
├── src/aet/                # Versioned Python package for the aet CLI
├── skills/                 # One directory per skill (content only)
│   ├── SKILL.md            # Skill instructions (YAML frontmatter + markdown)
│   ├── examples/           # Usage examples
│   └── references/         # Detailed reference docs
├── docs/                   # Human-readable documentation
│   ├── CONVENTIONS.md      # Skill authoring conventions
│   ├── use-cases.md        # Workflow scenarios
│   └── adr/                # Architectural Decision Records
├── .agents/                # Agent-neutral workflow infrastructure
│   ├── commands/
│   ├── reference/
│   ├── templates/
│   ├── learnings.jsonl
│   └── ledger.jsonl
├── scripts/                # Maintenance tooling (validation, hooks, release guards)
│   └── archive/            # One-off migrations that have already run
├── tests/                  # pytest suite
└── Makefile                # Dev orchestration
```

## Tooling Reference

| Command                 | What it runs                                                                         |
| ----------------------- | ------------------------------------------------------------------------------------ |
| `make help`             | Show all available targets                                                           |
| `make install-skills`   | Symlink all skills to `~/.agents/skills/`                                            |
| `make add-skill NAME=x` | Scaffold a new skill directory                                                       |
| `make install-editable` | Ensure the `aet` package is installed editable in the local venv                     |
| `make lint`             | Run markdownlint on all markdown files (manual / staged-only)                        |
| `make lint-py`          | Run ruff on Python files                                                             |
| `make test`             | Run pytest suite                                                                     |
| `make validate`         | Run lint-py + workflow lint + skills-lint + skill-structure validator + `aet plans lint` + `aet docs lint` + test (pytest skipped for prose-only changes) |
| `aet status`            | Show queue health and plan drift; use after queue/state edits                        |
| `aet plans lint`        | Lint the live `docs/plans/` corpus; settled-ness is recorded in the provenance ledger (ADR-055) |
| `aet docs lint`         | Lint documentation against the declarative rules in `.agents/doc-rules.yaml`          |
| `aet docs generate`     | Regenerate `docs/CLI.md` from the Typer command tree                                 |
| `make install-hooks`    | Install pre-commit hooks                                                             |

## Skill Structure Validator

`scripts/validate-skills.sh` checks every skill directory for:

- `examples/` and `references/` subdirectories exist
- `SKILL.md` has valid YAML frontmatter with `name` and `description`
- `name` matches the directory name
- `SKILL.md` is under 400 lines (warns on legacy skills over limit)
- All relative internal markdown links resolve

## AI Assistant Guardrails

### Forbidden

- Never delete or rename a skill directory without updating README.md skill table
- Never commit the `content/` directory (it is gitignored; used for local scratch)
- Never add a new skill without `examples/` and `references/` subdirectories
- Never write skill instructions that assume a specific AI agent (keep them agent-agnostic)
- Never introduce new skill patterns without checking `docs/CONVENTIONS.md` first

### Mandatory

- Match validation to the change; do not default to the heaviest suite:
  - **Code, skill, or workflow changes** → run `make validate` before completion.
  - **Prose-only / documentation changes** → run `make lint` (or the relevant doc linter); skip the full build/test suite.
  - **Queue or state bookkeeping** (plan status drift, history cleanup, state fixes) → verify with the specific tool surface, e.g., `aet status`, `aet plans lint`, or `aet state audit`.
  - **Frontmatter-only plan edits** → `aet status` plus `aet plans lint` is sufficient;
    do not run the full suite unless the change drives code paths.
- Always update `docs/CONVENTIONS.md` if you introduce a new skill pattern
- Always keep `SKILL.md` under 400 lines; move deep detail to `references/`
- Always use YAML frontmatter with `name` and `description` in every new SKILL.md
- Always ensure `description` explicitly states when to trigger the skill
- Always add an ADR in `docs/adr/` for structural changes to the toolkit itself

### Agentic Workflow Guardrails

- Always produce a PRD before writing code for any feature >1 day of work
- Always review the plan.md before implementation; never skip human validation
- Always branch worktrees from `origin/main` and rebase independent branches onto `origin/main` before shipping; never let a stale or ahead local `main` leak into a PR diff
- **Design-to-implementation hard gate** — Free-form design conversations are not implementation approval. After the user approves a design proposal ("yes", "sounds good", "go ahead", or similar), STOP and confirm scope before writing files: _"This will modify [N files]: [list]. Approve to proceed?"_ Do not begin editing until the user explicitly confirms.
- **Analysis-to-action discipline** — When your own analysis identifies a violation of a documented principle (ADR, convention, guardrail), state the conclusion and propose the fix. Do not present options that preserve a pattern you have proven wrong. The user chooses between valid implementations of the correct direction, not whether to keep a known error.
- Always run self-validation that covers the change before declaring a task complete (see the Mandatory validation tiering above)
- Always update `.agents/learnings.jsonl` after a bug or misalignment
- Never plan and implement in the same session; clear context between phases
- Use `docs/plans/` for atomic plan.md files, `docs/roadmaps/` for roadmaps, and `docs/prds/` for PRDs. A skill that needs a directory outside this set creates it on first use.
- File anything known-but-unstarted in `content/backlog/` — one file per item with a `trigger`; never leave it as prose in a session or as a "to be done" line in a report. That folder is local and untracked (`content/` is gitignored); never `git add` it
- Use sub-agents for research; keep main context clean
- Load `.agents/reference/` docs only when working on the relevant task type

## Context Budget

- Keep AGENTS.md under 200 lines; detailed rules live in `.agents/reference/`
- Prime command: load only core files + recent commits, not the full codebase
- Planning session: free-form conversation OK, but clear before implementing
- Sub-agents: use for any research consuming >50k tokens
- If context feels "full" (agent repeating itself, missing obvious things), clear and restart

## Decision Log

- **Content + Python package repo:** The repository contains both skill content and an installable Python package (`src/aet/`). See ADR-036.
- **Runtime dependency policy:** Standard library for glue; dependencies for formats, protocols, and UI; one dependency per plan with its own security review. See ADR-037.
- **Directory-based distribution:** Skills are installed together from this repo via `npx skills add ... --all`. Individual `.skill` zip artifacts are no longer produced or tracked. See ADR-016 and ADR-018.
- **Directory layout:** Skills live under `skills/` as pure content; all tool code lives under `src/aet/`. See ADR-038.
- **CLI/skill namespace taxonomy:** Deterministic work becomes code/CLI (`aet <noun> <verb>`), judgment stays in skills, and collisions are resolved by atomic alias-free renames. See ADR-039.
- **No CI:** All gates local via pre-commit + Make. Keeps the repo portable and free of vendor lock-in.
- **Trimmed tooling:** Dropped cspell, lychee, detect-secrets, and prettier. Cosmetic formatting (prettier) produced churn without catching real defects; the quality surface is structure (`validate-skills`), semantics (`skills-lint`, `validate-workflows`), and code (`ruff`, `pytest`). Markdownlint remains as a light, staged-only guard.
- **Narrowed base hygiene for plans:** `docs/plans/` is outside the intake durability gate. Untracked/modified plans are ignored by base hygiene, local branches may be ahead when only plan paths diverge, and `aet sprint add` no longer accepts `--allow-untracked`. The durable write for plan paths happens only at terminal closure (`merged`/`abandoned`), which records the settled state in the provenance ledger (ADR-055). See ADR-054 and ADR-055.
