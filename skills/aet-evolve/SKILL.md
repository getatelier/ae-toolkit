---
name: aet-evolve
description: System evolution through retrospectives and rule/command/template updates. Use after a bug, misalignment, or completed development cycle. The highest-leverage long-term skill — one improved command saves hours across dozens of future sessions. Triggers on requests like "retro this," "the agent made this mistake again," "update our rules," or "system evolve."
---

# aet-evolve

System evolution for agentic engineering. When the agent makes a mistake, don't just fix the bug — fix the system that allowed it.

## When to Use

- After a bug or misalignment in a completed PIV loop
- The agent repeated a mistake it made before
- You had to manually correct the same pattern multiple times
- You want to improve the AI layer (rules, commands, templates)
- End of sprint / weekly retrospective

## Context

Run `aet context` and parse its JSON for session context (branch, repo
state, AGENTS.md, learnings, active plan/PRD stage); print the stage
banner it emits. Do not ask the user for this context manually.

## Prerequisites

`aet mine-learnings` and `aet metrics` must be on `PATH`. Run `aet setup link` once after installing skills. If you are developing in this repo, `make install-skills` runs it automatically.

The orchestrator writes telemetry directly to `~/.aet/telemetry/`; no manual ingestion step is required.

## Commands

### `retro`

Analyze what went wrong in the last loop and identify the systemic root cause.

**Procedure:**

1. **Retro debt check** — review action items from the most recent `docs/retros/*.md`.
   - Verified done → mark complete.
   - Not done → convert to a queue task or explicitly drop with reason.
   - Record the outcome in the current retro context.
2. Read the completed task's spec (rendered plan or task record) and the actual implementation (git diff).
3. Identify deviations: what did the agent do differently from the plan? What did you have to correct?
4. Ask: which layer allowed this? Options:
   - **Global rules** (`AGENTS.md`) — coding style, testing strategy, logging
   - **Commands** (`.agents/commands/*.md`) — prompts/procedures that were unclear or incomplete
   - **Reference docs** (`.agents/reference/*.md`) — missing or incorrect task-specific guidance
   - **Templates** (`.agents/templates/*.md`) — gaps in PRD/plan/retro structure
   - **On-demand context** (`docs/CONVENTIONS.md`, architecture notes) — outdated or AI-unreadable docs
5. Use `.agents/templates/retro-template.md` to produce a retro document.
6. Create `docs/retros/` if it doesn't exist. Save to `docs/retros/{date}-retro.md` or run `aet learnings append` to persist the learning.

### `system-evolve`

Update the layer that allowed the issue so it doesn't happen again.

**Procedure:**

1. Review the retro output to identify the target layer.
2. Propose a specific, minimal change to that layer:
   - If `AGENTS.md` — add/modify one rule or guardrail
   - If command — update the markdown workflow in `.agents/commands/`
   - If reference doc — add/clarify guidance in `.agents/reference/`
   - If template — add a missing section or example
3. Show the exact diff before applying.
4. Apply the change and commit it to source control.
5. Persist the learning by running `aet learnings append`:

   ```bash
   aet learnings append \
     --problem "Agent forgot to run tests before committing" \
     --layer "commands/implement.md" \
     --fix "Added explicit 'run tests' step to validation strategy in plan template" \
     --prevents "Untested code being committed" \
     --trigger "test factories" \
     --trigger "catch blocks"
   ```

   - `--trigger` is repeatable; omit it when no keywords apply.
   - `--recurrence N` is optional and must be a positive integer.

### `aet retro`

One-shot retro generation from telemetry. Run this after an `aet run` batch or any session where AET tooling misbehaved. It runs `aet mine-learnings --propose`, reads the current project's per-task JSONL telemetry from `~/.aet/telemetry/{project-slug}/` (ADR-012), and writes a retro that separates **project-level** findings (fix the codebase being built) from **AET-level** findings (fix the toolkit).

**Procedure:**

1. Ensure `aet mine-learnings` is on `PATH`.
2. Run `aet metrics --json` to collect quantitative evidence. If a previous `docs/retros/YYYY-MM-DD-aet-retro.md` exists, pass `--since <date of that retro>` to narrow the window. Cite the returned first-pass rate, rework count, and cost-per-merged-task values when proposing skill or workflow edits, alongside the qualitative patterns from `aet mine-learnings`.
3. Run `aet retro`.
4. Review `docs/retros/YYYY-MM-DD-aet-retro.md`.
5. Route project-level findings into the current project's queue.
6. Route AET-level findings through `system-evolve` and append a learning.

Metrics *inform* proposals; they do not trigger automatic edits. See `references/aet-retro.md` for full usage and flags.

### `aet mine-learnings`

Scan the telemetry archive for recurring patterns and output a ranked report.

**Procedure:**

1. Run `aet mine-learnings`.
2. The script scans the dated run directories under `~/.aet/telemetry/{project-slug}/`:
   - per-task JSONL execution logs
   - `last-run.json` completion summaries
   - narrative markdown reports (QA, review, CSO, verification)
3. It mines dependency issues, repeated loops, full-suite runs, stage failures, and review noise.
4. It prints a markdown report ranked by frequency with example snippets.
5. With `--archive-dir PATH`, point to a custom telemetry root (defaults to `~/.aet/telemetry/`).
6. With `--propose`, it prints suggested skill edits (for example, tighten `aet-setup` dependency checks or `aet-implement` validation guardrails). It **never** writes edits directly.

## Key Principles

- **Outer loop vs inner loop** — inner loop: chug through tickets. Outer loop: pause and improve the AI layer.
- **Treat the AI layer like code** — check changes into source control, review in PRs.
- **One fix, one layer** — don't rewrite everything. The smallest rule change that prevents recurrence.
- **Compounding quality** — `.agents/learnings.jsonl` makes the system smarter across sessions, not just within them.
- **High leverage** — improving one command can save dozens of engineer-hours going forward.
- **Escalation ladder** — when a learning recurs, escalate enforcement strength. See `references/escalation-ladder.md`.
