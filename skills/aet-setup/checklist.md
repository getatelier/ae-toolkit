# AE Toolkit Setup Master Checklist

Use this checklist during every `/aet-setup` invocation. Every topic must be explicitly addressed — either implemented, documented as intentionally skipped, or flagged for future work.

---

## 1. Stack Detection

- [ ] Detect all languages/frameworks from config files and source extensions
- [ ] If ambiguous, infer from directory structure
- [ ] If still ambiguous, default to the most likely stack and document the assumption
- [ ] Note monorepo vs. single-stack

## 2. Architecture Pattern

- [ ] Identify the dominant architectural pattern (or lack thereof)
- [ ] Document layer rules and dependency direction
- [ ] If no pattern exists, suggest one based on project size and stack
- [ ] Document in `AGENTS.md`

## 3. Type Safety

- [ ] For every typed language: is strict mode enabled?
- [ ] Are all public functions type-annotated?
- [ ] Is dynamic typing banned except at explicit boundaries?
- [ ] Document specific flags/settings in `AGENTS.md`

## 4. Linting & Formatting

- [ ] Does every code directory have a linter configured?
- [ ] Does every code directory have a formatter configured?
- [ ] Are linter and formatter configs non-conflicting?
- [ ] Is there an auto-fix command?

## 5. Security Scanning

- [ ] Static source code analysis configured and passing?
- [ ] Dependency vulnerability audit configured and passing?
- [ ] Secret/credential scanning configured (pre-commit or git hooks)?
- [ ] All suppressions documented with justification?

## 6. Testing

- [ ] Unit tests exist for business logic?
- [ ] Integration tests exist for boundaries?
- [ ] Coverage target set and enforced?
- [ ] Test data uses factories/fixtures, not hardcoded values?
- [ ] Test suite runs in under 2 minutes?

## 7. Git Hooks & Local Automation

- [ ] Pre-commit hooks or git hooks installed?
- [ ] Hooks run: format check, lint, type check, security scan, tests?
- [ ] Root orchestration file exists (`Makefile` or `justfile`)?
- [ ] Key targets: install, dev, test, lint, format, type-check, security-audit?
- [ ] Every target is runnable and documented?
- [ ] Per-provider merge guard installed (`aet harness-guard install`) and blocks `gh pr merge` at the harness tool-call layer?

## 8. AI Guardrails (`AGENTS.md`)

- [ ] `AGENTS.md` exists at project root?
- [ ] Per-subproject `AGENTS.md` exists for monorepos?
- [ ] Contains explicit Forbidden list?
- [ ] Contains explicit Mandatory list?
- [ ] Guardrails are specific to the project's patterns, not generic copy-paste?

## 9. Documentation

- [ ] `docs/CONVENTIONS.md` exists with structure, naming, error handling?
- [ ] `docs/references/` exists with load-on-demand reference docs?
- [ ] Each reference doc is copied from the matching `aet-setup/examples/*.example` template?
- [ ] `docs/references/README.md` explains how to use the reference docs?
- [ ] Reference docs are focused and free of bloat so they stay load-on-demand?
- [ ] Root agent-context file (`AGENTS.md`, `CLAUDE.md`, etc.) contains a table pointing to each `docs/references/*.md` file?
- [ ] `docs/adr/README.md` exists explaining ADRs?
- [ ] `docs/adr/000-template.md` exists?
- [ ] README quick-start is current and accurate?

## 10. Observability

- [ ] Structured logging configured (timestamp, level, name, message)?
- [ ] Health check endpoint exists and checks critical dependencies?
- [ ] Third-party log noise reduced?
- [ ] Metrics/tracing documented as future or implemented?

## 11. Database Migrations

- [ ] If ORM detected: migration tool configured?
- [ ] If no ORM: document database access patterns?
- [ ] If migrations intentionally skipped: document why?

## 12. Dependency Locking

- [ ] Lockfile exists and is committed?
- [ ] Runtime version constraints documented?
- [ ] `lock` or equivalent target in orchestration file?
- [ ] No unpinned floating dependencies in production?

## 13. API Contracts

- [ ] If backend+frontend: schema generation configured?
- [ ] If backend+frontend: frontend type sync configured or documented?
- [ ] If API-only: schema documentation published?
- [ ] Sync command documented in `AGENTS.md`?

## 14. Git Workflow

- [ ] `.gitmessage` template for conventional commits?
- [ ] Branch naming conventions documented?
- [ ] Commitlint or equivalent configured (if easily supported)?
- [ ] `.gitignore` excludes active plans (`docs/plans/active/`) and generated agent artifacts (`.agents/work-history.jsonl`, `.agents/runs/`, `.worktrees/`)?

## 15. Task Backend Configuration

- [ ] `.agents/aet-config.json` (team mode) or `~/.aet/{config-slug}/config.json` (shadow mode) exists with a valid `integration_mode` (`pr-per-task` (default) or `single-pr`)?
- [ ] Neither config carries the `task_backend` key removed in 1.10? A stale key is ignored with a warning, but it means the file predates the upgrade.
- [ ] Projections are configured on the orthogonal `projections` axis when a forge mirror is desired?
- [ ] `gh` availability and authentication are verified before label creation (projection setup)?
- [ ] Switching backends is documented as forward-only (no history migration)?

---

## Post-Implementation Validation

- [ ] All new linters/formatters pass (or have zero false positives)
- [ ] Test suite passes
- [ ] Pre-commit hooks install successfully
- [ ] `AGENTS.md` is readable and actionable
- [ ] `make help` (or equivalent) shows all available targets
