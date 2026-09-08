# PRD: Fix aet-work `run` Runtime Detection to Use Current Agent

> **Status: Superseded.** The self-report mechanism specified here — the skill asking the executing agent to name its own CLI — was AI-remembered state and regressed: on 2026-09-08 a Claude Code session was still dispatching its tasks to `kimi`. Detection is now code-enforced in `resolve_cli_adapter` (`src/aet/cli_adapter.py`), which reads the agent CLI off the process ancestry and errors rather than probing `PATH`. The goals below still hold; the Proposed Detection section does not, and `aet-work` carries no detection logic at all. See commit `adb1404f`.

## Overview

The `aet-work run` command generates an orchestrator script that spawns a fresh OS process for each queued task. The script must invoke the same agent CLI that is currently running `aet-work` — otherwise the spawned tasks run on a different agent than the one the user chose.

Currently, the runtime detection checks whether `kimi` or `claude` binaries exist in `PATH`, giving hard-coded priority to `kimi`. This breaks whenever a developer has multiple agent CLIs installed but is using a different one to run the skill. For example, running `aet-work run` through Claude Code on a machine that also has Kimi installed generates a script that calls `kimi` instead of `claude`.

This PRD fixes the detection logic by having the **currently executing agent identify itself** rather than guessing from env vars or installed binaries.

## Goals

1. `aet-work run` detects the agent that is currently executing the skill
2. The generated orchestrator script invokes the detected agent CLI for every task
3. Detection is future-proof: any new agent CLI is supported automatically without updating the skill
4. `make validate` and `make package` pass

## Non-Goals

- No new orchestrator features (parallel execution, dry-run, etc.)
- No changes to queue JSON schema, worktree logic, or task execution flow
- No changes to `init-queue`, `status`, `next`, `cleanup`, or `drift-check`
- No auto-installation or validation of the detected CLI beyond a basic `command -v` check

## User Stories

- As a developer with both Claude Code and Kimi Code installed, I want `aet-work run` to spawn sub-tasks on the same agent I am using, so I don't get unexpected behavior from a different CLI.
- As a Claude Code user, I want `aet-work run` to use `claude` even when `kimi` is also on my machine.
- As a toolkit maintainer, I want the runtime detection to be obvious and easy to extend for new agents without re-prioritizing a list.

## Acceptance Criteria

- [ ] `aet-work/SKILL.md` `run` command runtime detection is rewritten to detect the **current** agent
- [ ] Detection asks the currently running agent to identify its own CLI command; no env vars, no PATH scanning, no priority list, no override knob
- [ ] `aet-work/references/context-isolation.md` is updated to document the self-detection behavior
- [ ] `aet-work/references/orchestrator-template.sh` comment or template is updated if the substitution variables change
- [ ] `make validate` passes
- [ ] `make package` regenerates `.skill` files
- [ ] Manual verification: running `aet-work run` from Kimi produces a script with `CLI_BIN="kimi"`; running from Claude Code produces `CLI_BIN="claude"`

## Technical Notes

### Current Broken Detection

```
1. **Runtime detection:**
   - Check `KIMI_CLI_VERSION` env var → current runtime is Kimi Code → use `kimi`
   - Check `CLAUDE_CODE` env var → current runtime is Claude Code → use `claude`
   - If none matched: emit error explaining that the current agent runtime could not be identified and list the supported env vars
```

### Proposed Detection

Replace all external detection with a single self-reporting step:

> **"You are the AI coding agent currently executing this skill. State the CLI command (e.g. `kimi`, `claude`, `cursor`) that the orchestrator script should use to spawn a fresh process of yourself. Also state the flags this CLI accepts for: (a) passing a prompt/message, (b) setting the working directory, and (c) any recommended non-interactive flags."**

The agent knows what it is. Kimi knows it is Kimi and that the command is `kimi --print --yolo -p <prompt> --work-dir <dir>`. Claude knows it is Claude and that the command is `claude --print <prompt> --add-dir <dir>`. No env vars, no PATH scanning, no hard-coded table.

The skill captures this self-report and substitutes it into the orchestrator template. This is future-proof: a new agent CLI works immediately without any changes to the skill.

**Why this works:**

- The agent executing the skill is the same agent that will be spawned for sub-tasks
- It knows its own invocation semantics better than any heuristic
- It removes all maintenance burden of keeping a detection table up to date

### Files to Change

| File                                           | Change                                                                         |
| ---------------------------------------------- | ------------------------------------------------------------------------------ |
| `aet-work/SKILL.md`                            | Rewrite the `run` → "Runtime detection" procedure (lines ~79–83)               |
| `aet-work/references/context-isolation.md`     | Update "Runtime Capability Reference" section to mention self-detection        |
| `aet-work/references/orchestrator-template.sh` | No structural changes; header comment already says "filled in by aet-work run" |

## Open Questions

1. Should the orchestrator template include a comment documenting the self-reported CLI configuration for debugging?

---

_Stage: prd-approved_
_Next step: run `aet-validate-scope`_
