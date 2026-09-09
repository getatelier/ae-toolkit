---
name: aet-setup
description: Bootstrap or upgrade any software project with best-practice documentation, code quality enforcement, local automation, and AI guardrails. Part of the Agentic Engineering Toolkit (AE Toolkit). Use when starting a new project, inheriting a codebase without standards, or wanting to prevent AI-generated "fast slop." Adapts to any stack through research-driven detection. Triggers on requests like "set up project quality," "enforce code standards," "bootstrap best practices," or "prevent AI slop."
---

# aet-setup

Bootstrap or upgrade any software project with best-practice documentation, code quality enforcement, local automation, and AI guardrails — without hardcoded templates or paid CI services.

## When to Use

- Starting a new project and want solid foundations
- Inheriting an existing project that lacks quality standards
- Tired of writing the same "setup best practices + enforce quality + no AI slop" prompt
- Want reusable, research-driven setup that adapts to any stack

## Invocation

```
/aet-setup
```

Auto-detects stack, infers sensible defaults, suggests key decisions, and implements everything.

```
/aet-setup stack="backend-lang + frontend-lang + sqlite"
```

Explicit stack declaration. Skips detection. Useful for new/empty repos.

```
/aet-setup stack="backend-lang + frontend-lang + postgres" enforce-security=true containerize=true
```

With optional flags to override sensible defaults.

## Commands

### `install-binaries`

Put the `aet` dispatcher on `PATH` so skills like aet-work, aet-ship, and aet-evolve can invoke their helpers (`aet state`, `aet run`, `aet mine-learnings`, etc.).

**Prerequisite:** `npx skills` copies skill markdown only; the `aet` Python package must be installed first. See [references/install-binaries.md](references/install-binaries.md) for the full procedure.

## Philosophy

**Research-driven, not template-driven.** This skill does not ship hardcoded config files for every possible stack. Instead it:

1. **Detects** the stack from existing files (or accepts explicit declaration)
2. **Researches** current best practices for that stack (using web search when needed)
3. **Audits** the current project state against the master checklist
4. **Implements** tailored configs, docs, and automation
5. **Guards** against AI slop with explicit rules in `AGENTS.md`

The skill **suggests** important topics but never blocks waiting for user input. It uses common-sense defaults.

## Master Checklist

For every project, ensure these topics are addressed. Use auto-detection; fall back to sensible defaults.

| #   | Topic                    | How to Detect                                                        | Sensible Default                                                  |
| --- | ------------------------ | -------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 1   | **Stack**                | Look for build/config files (e.g., package manifests, build configs) | Ask user if ambiguous; default to detected                        |
| 2   | **Architecture pattern** | Framework used, directory structure conventions                      | Clean/hexagonal for backends; component-based for frontends       |
| 3   | **Type safety**          | Presence of type checker config, strict flags                        | Strict mode enabled everywhere                                    |
| 4   | **Linting & formatting** | Presence of linter/formatter configs                                 | Dominant tools for the language, configured and runnable          |
| 5   | **Security scanning**    | Presence of static analysis, dependency audit, secret scanning       | **Enable by default** — never optional                            |
| 6   | **Testing**              | Presence of test runner config                                       | Unit + integration for backend; unit + component for frontend     |
| 7   | **Git hooks**            | Presence of pre-commit config or git hooks                           | pre-commit with lint/type-check/test/security gates               |
| 8   | **AI guardrails**        | Presence of `AGENTS.md`                                              | Generate with explicit forbidden/mandatory rules                  |
| 9   | **Documentation**        | Presence of docs, README quality                                     | `AGENTS.md` + `docs/CONVENTIONS.md` + ADR process                 |
| 10  | **Observability**        | Presence of structured logging, metrics, tracing                     | Structured logging + health checks at minimum                     |
| 11  | **DB migrations**        | Presence of ORM + migration tool                                     | Migration tool if ORM detected; document if intentionally skipped |
| 12  | **Dependency locking**   | Presence of lockfiles                                                | Enforce lockfile; add runtime version constraints                 |
| 13  | **API contracts**        | Presence of schema generation, type sync                             | Schema auto-gen for backend; frontend type sync if applicable     |
| 14  | **Git workflow**         | Presence of commit message template, branch conventions              | Conventional commits; branch naming conventions                   |

## Execution Steps

When invoked, follow this sequence:

### Step 1: Discovery

Scan the project root for stack indicators. Look for:

- Build/config files (package manifests, build tool configs, lockfiles)
- Source file extensions
- Framework-specific files

If multiple stacks detected, treat as monorepo.

### Step 2: Research (if needed)

If the stack is novel or you're unsure about current best practices, search the web:

- "{detected framework/language} best practices {current year}"
- "{detected framework/language} code quality tools {current year}"
- "{detected framework/language} security scanning setup"

Focus on tooling that is:

- **Maintained** (active repository, recent releases)
- **Widely adopted** (used by major projects)
- **Compatible** with the existing dependency versions

### Step 3: Audit

Compare the current project against the Master Checklist. For each item:

- **Present & good** → note it
- **Present but weak** → flag for upgrade
- **Missing** → flag for creation

Produce a concise audit report (bullet list, max 1 page).

### Step 4: Propose

Show the user:

1. Detected stack
2. Top 5 gaps found
3. What will be created/modified

Example:

```
Detected: Backend API + Frontend SPA + SQLite (monorepo)

Top gaps:
- No AGENTS.md (AI has no guardrails)
- No security scanning (static analysis, dependency audit)
- No dependency locking (lockfile missing)
- No DB migration tool (ORM present but no migrations)
- Frontend lacks a11y and bundle analysis

Will create/modify:
- AGENTS.md, docs/CONVENTIONS.md
- backend config (add security tools, test factories)
- frontend config (add a11y linting, bundle analyzer)
- .pre-commit-config.yaml (enhanced hooks)
- Makefile (add security-audit, type-check targets)
- docs/adr/000-template.md
```

### Step 5: Implement

Create/modify files. Always:

- **Prefer editing existing files** over creating new ones
- **Preserve existing conventions** when they conflict with "best practice" — document the deviation in `AGENTS.md`
- **Make minimal changes** — don't rewrite the project
- **Ensure all hooks/tools are local** — no paid CI services

### Step 6: Configure Task Backend

Run `aet configure --guided` to write the AET config in two questions:

1. **Scope** — `team` writes `.agents/aet-config.json` (committed with the repo); `shadow` writes `~/.aet/{slug}/config.json` (nothing committed).
2. **Integration mode** — `pr-per-task` or `single-pr`.

The guided flow detects existing config, shows current values, and asks before overwriting. In unattended contexts (`AET_EXECUTION_MODE=unattended` or `--scope`/`--integration-mode` flags), it skips prompts and writes directly. There is no store to select — `git-refs` is the only one — and the removed `task_backend` key is not written; projections are configured on the `projections` axis. See `aet-work/references/github-backend.md` for the label contract and sync behavior.

### Step 7: Validate

Before finishing:

1. Run the newly added linters/formatters — they should pass (or have zero false positives)
2. Run the test suite — it should pass
3. Verify pre-commit hooks can install
4. Confirm `AGENTS.md` is readable and actionable
5. Run validation calibration as the final setup completion step — plant a trivial error, confirm each command in `.agents/validation-commands.json` fails, then revert

## Methodology by Topic

### AI Context Files (`AGENTS.md`)

Always generate `AGENTS.md` at project root and per-subproject. It must contain: project overview, stack, architecture, directory structure, tooling reference table, AI Guardrails (Forbidden + Mandatory), Context Budget, Agentic Workflow Guardrails (PRD-first, plan-first, design-to-implementation hard gate), and a "Reference Docs (load on demand)" table pointing to `docs/references/*.md`. Keep it under 200 lines; detailed rules live in `docs/references/` and are loaded on demand. Generate guardrails from the project's actual patterns, not a template.

### Agentic Workflow Infrastructure (`.agents/`)

Create `.agents/` at project root as the agent-neutral home for workflows, templates, and persistent state:

```
.agents/
├── commands/
│   ├── README.md              # How to use command workflows
│   └── approval-checkpoint.md # Hard gate between design and implementation
├── smoke/                     # Session-level smoke checks
│   ├── README.md              # How to run and extend smoke checks
│   └── checks.sh              # Executable smoke suite (stack-specific)
├── templates/
│   ├── prd-template.md        # PRD structure
│   ├── plan-template.md       # Plan.md structure
│   └── retro-template.md      # Retro document structure
├── validation-commands.json   # Authoritative commands that must fail calibration
├── learnings.jsonl            # Persistent learning log
└── .gitkeep
```

Create `docs/references/` at project root for task-specific reference documents that are loaded on demand. Scaffold them from the templates in `aet-setup/examples/`:

| Source template (`aet-setup/examples/`) | Copied to target project as                |
| --------------------------------------- | ------------------------------------------ |
| `reference-README.md.example`           | `docs/references/README.md`                |
| `testing-strategy.md.example`           | `docs/references/testing-strategy.md`      |
| `api-conventions.md.example`            | `docs/references/api-conventions.md`       |
| `security-guidelines.md.example`        | `docs/references/security-guidelines.md`   |
| `ui-conventions.md.example`             | `docs/references/ui-conventions.md`        |
| `worktree-ship-hygiene.md.example`      | `docs/references/worktree-ship-hygiene.md` |

`aet-setup` only scaffolds foundational infrastructure — not empty folders for skills that may never be invoked. Each skill creates its own `docs/` subdirectory on first use. Keep reference docs focused and free of bloat so they remain genuinely load-on-demand. Document in `AGENTS.md` that they are loaded on demand. If the project uses a different root agent-context file (e.g., `CLAUDE.md` for Claude Code), place the same "Reference Docs (load on demand)" table there.

Add a smoke-check home at `.agents/smoke/` for session-level foundation checks. Smoke checks run **once per session** (not per task) to confirm the project boots, core services are healthy, and primary auth/CRUD paths still work.

**AET skill binaries:** If the project uses aet-work, aet-ship, or aet-evolve, ensure the `aet` dispatcher is on `PATH`. Run `aet setup link`. `make install-skills` from the toolkit repo runs it automatically. Document this in `AGENTS.md` so future sessions do not silently fall back to manual steps.

### Type Safety

For every typed language in the project:

- Enable the strictest available compiler/interpreter settings
- Document the specific flags in `AGENTS.md`
- Ban implicit dynamic typing (`any`, `interface{}`, `void*`, etc.) except at explicit boundaries

### Linting & Formatting

Every code directory must have an automated lint check, with a formatter configured as a manual convenience rather than a blocking gate:

- Use the dominant tools for the detected language/framework
- Ensure formatter and linter configs don't conflict
- Line length: pick a standard (80, 100, or 120) and enforce it everywhere
- Keep formatting out of the validation gate — provide a manual `make format` target if wanted, but do not add a format check to `make validate` or the commit/push path

### Security Scanning

Security is non-optional. For every stack:

- **Static analysis:** scan source code for vulnerabilities (e.g., unsafe deserialization, injection risks)
- **Dependency audit:** scan installed packages for known CVEs
- **Secret scanning:** detect accidentally committed credentials, API keys, tokens
- Add suppression comments (e.g., `# nosec`) only with explicit justification
- Document all security exceptions in `AGENTS.md`

### Testing

Define the testing pyramid:

- **Unit tests:** Fast, deterministic, no I/O. Mock external dependencies.
- **Integration tests:** Test boundaries (API endpoints, DB queries, external calls).
- **Coverage target:** Default 80%, but adjust to reality if the project is far below.
- **Test data:** Use factories/fakers. Never hardcode domain values in tests.

### Smoke Checks

Smoke checks verify that the project is alive. Scaffold `.agents/smoke/checks.sh` and add a `make smoke` target to the root orchestration. Standard checks:

- **Boot check** — the application starts without crashing
- **Dev services** — required local services (DB, cache, queue) are reachable
- **Login / auth handshake** — the primary identity path returns success
- **Primary CRUD** — one read and one write through the main data path

Run smoke checks **once per agent session**, not before every task. Record the result in `.agents/smoke/last-run.json` with timestamp and status. If smoke fails, halt task work and fix the foundation first.

### Validation Calibration

Before trusting any validation gate, prove it can actually fail. Calibration is a one-time setup ritual:

1. **Plant a trivial error** — introduce a deliberate lint error, failing test, or type mismatch
2. **Run the authoritative command** — the validation must report failure
3. **Revert the planted error** — restore the codebase to clean
4. **Record** — write the authoritative commands to `.agents/validation-commands.json`:

   ```json
   {
     "commands": [
       { "name": "lint", "command": "make lint" },
       { "name": "type-check", "command": "make type-check" },
       { "name": "test", "command": "make test" }
     ]
   }
   ```

Agents must use the commands listed in `.agents/validation-commands.json` as the source of truth for "does validation pass?" Never assume a new check works until calibration has demonstrated it failing.

### Git Hooks & Local Automation

All quality gates must run locally:

- Create `.pre-commit-config.yaml` or git hooks running: lint, type check, security scan, tests
- Create root orchestration (`Makefile` or `justfile`) with: install, dev, test, lint, format, type-check, security-audit, smoke
- Ensure every target actually works

### Git Workflow

Enforce commit conventions and branch naming:

- Add `.gitmessage` template for conventional commits
- Add branch naming conventions to `AGENTS.md`
- Optional: add commitlint if easily supported by the stack

### Dependency Locking

Reproducible builds are mandatory:

- Ensure lockfiles exist and are committed
- Add runtime version constraints (e.g., minimum language/runtime version in package config)
- Add a `lock` or equivalent target to the orchestration file

### Database Migrations

If an ORM or database abstraction is detected:

- Research the standard migration tool for that ORM
- Set it up OR document why migrations aren't needed (e.g., SQLite in dev only, schema-less DB)

### API Contracts

If backend and frontend are separate stacks in the same repo:

- Generate a machine-readable schema from the backend (OpenAPI, tRPC, GraphQL)
- Generate or sync frontend types from the schema
- Document the sync command in `AGENTS.md`

### Observability

Structured logging is the minimum:

- Replace basic logging with structured format (timestamp, level, name, message)
- Add a health check endpoint that verifies critical dependencies
- Reduce third-party log noise to warning level by default

### Accessibility (Frontend)

If a frontend is detected:

- Add a11y linting rules to the frontend linter config
- Document a11y requirements in `AGENTS.md`
- Enforce: keyboard accessibility, image alt text, form labels, semantic HTML

### Documentation

Humans need conventions docs; AI needs guardrails:

- Generate `docs/CONVENTIONS.md` with: structure, naming, error handling, state management patterns
- Create `docs/adr/` with template and README explaining ADRs
- Do **not** create `docs/product-briefs/`, `docs/prds/`, or `docs/plans/` here — each skill creates its own folder on first use
- Explain what an ADR is: a short document capturing a significant architectural decision, its context, and its consequences

## Generated Artifacts

See `aet-setup/references/README.md` for the full artifact list. Key outputs include `AGENTS.md`, `docs/CONVENTIONS.md`, the `.agents/` directory, `docs/references/` (copied from the `aet-setup/examples/*.example` templates), root orchestration (`Makefile`/`justfile`), and ADR templates.

When creating `.agents/`, ensure `.gitignore` excludes generated workflow artifacts:

```gitignore
# Active/draft plan scratch
docs/plans/active/
.agents/work-history.jsonl
.agents/runs/
.worktrees/
```

## Per-Provider Merge Guard

When setting up a project, install a harness-level merge guard that blocks `gh pr merge` at the provider's tool-call layer. This is the only surface that refuses the command under session auto/bypass mode.

- Detect the active harness from workspace markers (`.claude/` → `claude-code`, `.kimi-code/` → `kimi`).
- Use the lightweight adapter registry in `src/aet/harness_guard.py` to map `harness_id → adapter`.
- Run `aet harness-guard install` (or the equivalent setup step) to generate the provider-specific guard.
- Unsupported/undetected harnesses must fail safe: print a named gap and exit non-zero — never silently pass.
- Generated guards are Mode-1 config (under `.claude/`, gitignorable) and non-clobbering.

## AI Guardrails Template

Every `AGENTS.md` must include guardrails with **Forbidden**, **Mandatory**, **Agentic Workflow**, and **Context Budget** sections. See `examples/AGENTS.md.example` for the full template.

## Rules

- **Never use paid CI services** — all automation must be local (pre-commit, Make, git hooks, scripts)
- **Security is not optional** — always include security scanning tools
- **Don't over-engineer** — if the project is a small script, don't force enterprise architecture
- **Respect existing choices** — if the project already uses a specific package manager or build tool, don't switch unless asked
- **Document deviations** — if you choose not to follow a "best practice", explain why in `AGENTS.md`
- **Keep it runnable** — every command in the Makefile must actually work
- **Suggest, don't block** — propose key decisions but never halt waiting for user input
