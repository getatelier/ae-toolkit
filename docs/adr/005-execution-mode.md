---
subject: execution-mode
---

# Execution Mode Interaction Model

## Status

Accepted

## Context

The AE Toolkit has an ad-hoc mechanism for unattended execution: the `AET_ORCHESTRATOR=1` environment variable, set by the `aet-work` orchestrator template. This variable signals to skills that they are running in a background loop and should skip interactive approval gates.

Problems with the current approach:

1. **Tool-specific name** — `AET_ORCHESTRATOR` ties the mechanism to `aet-work`. A CI system or future orchestrator would need its own variable.
2. **Boolean semantics** — A boolean flag (`1` / unset) does not express what mode the system is in, only that an orchestrator is present.
3. **Inconsistent handling** — Skills with approval gates do not have a documented, convention-driven way to detect and respond to unattended mode. Some may hang indefinitely waiting for user input.
4. **No guidance for skill authors** — New skills that introduce approval gates have no reference for how to behave in unattended contexts.

## Decision

Introduce a formal execution-mode system using the environment variable `AET_EXECUTION_MODE`.

### Contract

```
AET_EXECUTION_MODE
  - unset or "interactive"  → Default. Hard gates enforced.
  - "unattended"            → Orchestrator/background mode. Gates bypassed with logging.
```

### Gate Bypass Protocol (Unattended Mode)

When a skill detects `AET_EXECUTION_MODE=unattended` at an approval checkpoint:

1. **List scope** — Still enumerate intended files and magnitude (audit trail).
2. **Log bypass** — Print exactly: `🤖 Unattended mode (AET_EXECUTION_MODE=unattended) — skipping interactive approval. Proceeding with: ~N files, ~M lines changed.`
3. **Continue** — Proceed to the next step; do not ask the user.

### Gates That Must Still Stop in Unattended Mode

The following categories halt execution even in unattended mode:

- **ATOMIC OVERSIZED tasks** — No human available to approve scope override. Hard stop with non-zero exit code.
- **Critical security findings** (`aet-cso` Critical/High) — Unattended mode must not auto-approve security risks.
- **Merge verification failures** (`aet-ship`, `post-ship-verify`) — Mechanical check; failures are hard stops.

### Skill Author Obligation

Any skill containing an interactive approval gate ("Approve to proceed?", "Hard gate") must:

1. Check `AET_EXECUTION_MODE` before presenting the gate.
2. In unattended mode, log the bypass and continue.
3. Document the gate behavior in the skill's instructions.

The `scripts/validate-skills.sh` linter enforces this: skills with approval gates that do not mention `AET_EXECUTION_MODE` are flagged.

## Consequences

- **Easier:** `aet-work run` can spawn subagents that execute end-to-end without hanging on approval prompts.
- **Easier:** The mechanism generalizes to any CLI runtime (Kimi, Claude, Aider, CI systems) without tool-specific hacks.
- **Easier:** Skill authors have a clear, documented convention to follow.
- **Harder:** Skill authors must remember to check `AET_EXECUTION_MODE` when adding new approval gates. The validator mitigates this.
- **Harder:** Any process that spawns an agent CLI must forward `AET_EXECUTION_MODE` to sub-sub-agents.

## Interactive-Only Exemption

Some skills are **never invoked in unattended mode** by design. For example,
`aet-bug-report` is an interactive debugging skill; there is no `aet-work` or CI
pipeline that runs it headlessly.

Skills documented as interactive-only may omit `AET_EXECUTION_MODE` handling. To
avoid the `validate-skills.sh` linter flagging these skills, authors should use
`"Hard gate"` or `"Approval gate"` phrasing instead of the literal string
`"Approve to proceed?"` (which the validator specifically checks for).

When adding an interactive-only gate, update this ADR and the Skill Writing Guide
to document the exemption.

## Alternatives Considered

1. **Keep `AET_ORCHESTRATOR=1`** — Rejected. Too specific to `aet-work`; does not generalize to CI or other orchestrators. Poor semantic clarity.
2. **Add a `--mode unattended` CLI flag** — Rejected for now. Depends on CLI-level support (Kimi `--yolo`, Claude `--print`, etc.) which varies across runtimes. Env var is the lowest-common-denominator that works everywhere. May be revisited if CLI convergence improves.
3. **Remove all gates in unattended mode** — Rejected. Would silently bypass security and architecture checks, creating unacceptable risk.
