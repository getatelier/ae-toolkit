# PRD: CLI Discovery Cost

## Overview

Agents using the `aet` CLI spend multiple sequential turns discovering *which*
command to run before they can run anything. The entry point `aet --help` lists
35 implementation-module groups and no leaf commands, so reaching an executable
invocation costs a three-hop walk (`aet --help` → `aet <group> --help` →
`aet <group> <verb> --help`), measured at **8.2 KB across 3 sequential turns**.
The information the agent needs — the leaf command and its required argument —
exists at every hop but is never presented at the first one.

This PRD reduces the cost of the *discovery* path. It does not add
documentation; the toolkit already has three overlapping surfaces (`--help`,
the generated `docs/CLI.md`, and skill prose). It restructures the cheapest,
most-reflexive surface so one hop answers the question, and it prevents the
hand-copied-CLI-reference failure mode from returning.

## Goals

- Reduce intent-to-invocation from 3 hops to 1 hop for every leaf command.
- Cut the byte cost of the discovery path, measured before and after.
- Remove non-informational bytes (Rich box-drawing) from non-interactive output.
- Make the error path teach the correct invocation instead of only naming the
  violated constraint.
- Prevent regression of the generated-or-absent principle (R-10 of
  `docs/prds/structural-review-tier-2-prd.md`) in `skills/`.

## Non-Goals

- **Merging or reducing the number of skills.** Skill count is not the cause;
  skill `description` fields are what intent-routing matches against, so
  collapsing them would degrade routing. Considered and rejected.
- **Embedding CLI reference material into SKILL.md files.** This contradicts
  R-10 and re-creates the drift class that `t2r-11-generated-cli-reference`
  removed. Considered and rejected.
- **Stripping command semantics out of skill prose.** Fail semantics and
  when-to-use guidance that `--help` does not carry stay in skills. The single
  exception is the one hand-copied option table the audit found (see Technical
  Notes), which is removed under R-4.
- **Changing any command's behavior, arguments, or defaults.** This PRD changes
  how the command tree is *presented*, never what it does.
- **Plain-text rendering for non-help output** (`status`, `desk`, `gate review`,
  `report`). Deferred — see Deferred Work.
- **Enriching help text with the semantics currently living in skill prose.**
  Deferred — see Deferred Work.
- **Turn-count telemetry.** AET has no per-turn or per-tool-call telemetry
  (`content/backlog/cfg-01-session-efficiency.md`), and this PRD does not add it.

## Requirements

- **R-1**: `aet --help` emits a single-hop index of every leaf command in the
  Typer tree, organized into sections by workflow task rather than by implementation module,
  each with its one-line description and required arguments. Leaf commands are
  organized into presentation **sections** by workflow task.
- **R-2**: Help and error output renders as plain text, with no box-drawing
  characters, when stdout is not a TTY. Interactive TTY output is unchanged.
- **R-3**: Argument and unknown-command errors name at least one canonical,
  runnable invocation of the intended command, in addition to the violated
  constraint.
- **R-4**: `aet docs lint` fails when a file under `skills/` hand-copies CLI
  syntax — an `## Options` heading, or a verbatim type/default marker emitted by
  `docs/CLI.md` or `aet --help` — enforcing the generated-or-absent principle.

## User Stories

- As an agent resolving "promote this plan to the sprint", I want the first
  help call to name `sprint add` and its required argument, so that I issue one
  tool call instead of three (satisfies: R-1)
- As an agent running any `aet` command non-interactively, I want output free of
  decorative characters, so that the tokens I spend carry information
  (satisfies: R-2)
- As an agent that just got an argument error, I want the error to show a
  working invocation, so that my next call succeeds rather than triggering
  another help lookup (satisfies: R-3)
- As a maintainer, I want a lint that rejects hand-copied flag tables in skill
  prose, so that the cleanup already performed by `t2r-11` cannot silently
  regress (satisfies: R-4)

## Acceptance Criteria

Measurement is **static** — byte counts and structural hop counts derived from
the command tree. No claim depends on runtime telemetry, which does not exist
at turn granularity.

- [ ] `aet --help` lists every leaf command reachable in the Typer tree; the
      count matches the tree walk with zero omissions (satisfies: R-1)
- [ ] Reaching any leaf command's name and required arguments requires exactly
      **1** invocation, down from 3, verified by construction against the tree
      (satisfies: R-1)
- [ ] The before/after byte cost of the three-hop discovery path is recorded in
      the plan's validation output; baseline is **8,244 bytes / 3 invocations**
      (satisfies: R-1)
- [ ] `aet --help` piped to a non-TTY contains no `│`, `─`, `╭`, `╮`, `╰`, `╯`
      characters (satisfies: R-2)
- [ ] The TTY rendering path is not modified, verified by inspection of the diff.
      The suite asserts the non-TTY branch only: `CliRunner` output is byte-identical
      to a pipe (verified: box characters present in both, 3,565 chars / 4,307 bytes),
      so no CliRunner test can evidence the TTY branch, and a pty-based test was
      rejected as flaky for the value it adds (satisfies: R-2)
- [ ] `aet sprint add` with no argument prints a runnable example invocation
      alongside the missing-argument error (satisfies: R-3)
- [ ] An unknown subcommand error retains its existing "Did you mean" suggestion
      and adds a runnable example (satisfies: R-3)
- [ ] `aet docs lint` fails on a fixture skill file containing `[default:` or an
      option-type signature, and passes on the current `skills/` tree unchanged
      (satisfies: R-4)
- [ ] No command's arguments, options, defaults, or exit codes change

## Technical Notes

**Reuse.** `src/aet/cli/docs.py` already walks the Typer tree to generate
`docs/CLI.md` (`_walk_commands`, `_format_command`, `generate_cli_reference`).
R-1 needs the same walk rendered to stdout with a task grouping, not a new
traversal. The grouping is the only genuinely new artifact.

**Proposed sections** for R-1, covering all 35 top-level entries. "Section" is
deliberately not "group": ADR-039 already uses *group* for a noun-scoped command
group (`aet gate review`), and reusing the word for a presentation concept is the
exact drift that ADR reject shapes to prevent.

| Section | Commands |
|---|---|
| Plan work | `plan`, `plans`, `sprint`, `backlog`, `docs` |
| Run work | `run`, `run-one`, `next`, `status`, `state`, `queue` |
| Ship work | `ship`, `gate`, `desk`, `size` |
| Inspect & learn | `report`, `metrics`, `retro`, `mine-learnings`, `learnings`, `handoff`, `context` |
| Set up & maintain | `setup`, `configure`, `hooks`, `harness-guard`, `panel`, `reconcile`, `validate-workflows`, `release-prep` |

Sections are presentation-only. They do not rename commands or alter the ADR-039
`aet <noun> <verb>` taxonomy, and no command moves between Typer groups in the
code. The section map is a static map in code: it is presentation config with one
consumer, and per-command metadata would spread it across 35 modules for no gain.

**Audit finding behind the Non-Goals.** A first scan of `skills/` for Typer and
`docs/CLI.md` markers (`[default:`, `*str*`, `--flag <str>`) returned 0 matches —
the `t2r-11-generated-cli-reference` cleanup removed those. A second scan for
*hand-written* option tables found **one surviving violation**:
`skills/aet-evolve/references/aet-retro.md` carries a `## Options` section
hand-copying six `aet retro` and `aet metrics` flags with their defaults. It is
currently accurate, which is exactly why it is dangerous: nothing keeps it that
way.

Everything else in the ~25 skill files matching `--flag` is one of: a third-party
flag (`git`, `pytest`, `gh`) outside the `aet` tree, or semantics absent from
`--help` — e.g. `skills/aet-work/references/queue-commands.md`, "`--follow`
does **not** tail or stream the run log; it waits silently". Both stay. R-4 is
therefore one removal plus a durable guard.

**Lint mechanism.** ADR-040 fixes the rule grammar at exactly four substring-based
types with no regex, so R-4 must be expressed as literal markers. The load-bearing
one is the heading `## Options` (1 occurrence in `skills/`, the violation above).
Verbatim-paste markers `*str*`, `*boolean*`, `*int*`, `*path*`, `<str>`, `<int>`
and `[default:` are all currently 0 and guard against copying from `docs/CLI.md`
or `aet --help`. The literal `(default:` prefix is **not** usable — it has 7 occurrences,
4 of them legitimate prose about environment variables and tier defaults.

ADR-040 also draws a boundary: `scripts/skills-lint` checks that documentation
matches the CLI surface; `aet docs lint` checks governance invariants. R-4 belongs
to the latter because it never consults the command tree — it is a content policy,
not a fidelity check. `aet docs lint` already supports `must_not_contain` (10
existing rules), so this needs new rules, not new rule types.

**Backward compatibility.** AET carries no backward-compat obligation. `aet
--help` output is replaced outright rather than shipped alongside the old form.

## Deferred Work

Parked as standalone documents so they do not block R-trace coverage:

- **Plain-text rendering for all non-TTY output** — extends R-2 beyond help to
  `status`, `desk`, `gate review`, `report`. Larger token win, but requires
  auditing existing tests that may assert on current formatting.
- **Enriching help at the source** — the audit finding shows skills compensate
  for thin help by hand-writing fail semantics and enum meanings. Moving that
  into Typer help/epilogs would make one hop not just *reachable* but
  *sufficient*. This is the deeper fix R-1 only partially addresses, and it
  touches every command.

## Open Questions

Both questions raised at draft were settled during scope validation:

- **Section map: static map in code**, not per-command metadata. It is presentation
  config with a single consumer; metadata would scatter it across 35 modules.
- **`aet --help` shows required arguments inline**, options excluded. Inline
  arguments remove the second hop for argument-taking commands, which is the
  requirement's whole point, at a bounded cost of roughly 1 KB across ~72 commands —
  still far below the 8,244-byte baseline.

---

## Divergence Summary

*Recorded: 2026-08-22 — Branch: cdc-03-cli-syntax-lint*

### Changed from plan

- (none)

### Added (unplanned)

- `scripts/skills-lint`: treat `--help` as a valid flag for any `aet` command, with a new `tests/fixtures/skills-lint/help.md` fixture. This prevents the skills-lint rule that validates command invocations from rejecting the `--help` references now used in place of the removed option table.

### Deferred

- Task 4 (merge branch to main and verify integration): handled by the next pipeline stage, `aet-ship`.

---

*Stage: synced*
*Next step: run `aet-ship`*
