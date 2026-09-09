---
subject: directory-layout
---

# Directory Layout Change

## Status

Accepted. Amends ADR-016 "Distribute AE Toolkit as a System, Not Individual Skills" paragraph 6 of the Decision section ("We are changing the distribution narrative and authoring rules, not the directory layout"). Explicitly reverses the `docs/prds/roadmap-p2-aet-binary-prd.md` Non-Goal "No merging of binaries into one Python program; exec dispatch only."

## Context

ADR-016 accepted system-level distribution but explicitly preserved the existing directory layout: skills stayed next to docs and scripts at the repository root, and tool code stayed inside skill directories. That caveat was reasonable at the time, but it is now in conflict with two later decisions:

1. [docs/prds/aet-package-extraction-prd.md](../prds/aet-package-extraction-prd.md) requires extracting all tool Python code into `src/aet/`, moving skill directories to `skills/`, and eventually consolidating the 19 argparse binaries into one Python program (R-2, R-5, R-8).
2. The merged `docs/prds/roadmap-p2-aet-binary-prd.md` Non-Goals declared "No merging of binaries into one Python program; exec dispatch only." That declaration matched the exec-dispatch design of the time, but it directly contradicts R-8 of the extraction PRD.

The extraction PRD cannot proceed unless the layout caveat and the binary-merge non-goal are formally reversed. This ADR records that reversal.

## Decision

1. The repository layout changes to:
   - `src/aet/` — the versioned Python package containing all tool code.
   - `skills/` — skill directories, each containing only Markdown content and static assets (no executable code).
   - `tests/` — test suite, reorganized to mirror the package layout.
   - `scripts/` — repo-maintenance scripts (audience split decided separately in A5).
   - `docs/`, `.agents/`, and repository root files unchanged in role.
2. ADR-016's assertion that "We are changing the distribution narrative and authoring rules, not the directory layout" is amended: the directory layout *is* changing.
3. The roadmap-p2 non-goal "No merging of binaries into one Python program; exec dispatch only" is reversed: consolidating the 19 argparse binaries into one Python program is an explicit goal (R-8).
4. The exec-based multicall dispatcher is recognized as a migration compatibility layer, not a permanent architecture. It will be removed once the consolidated CLI is proven to preserve behavior.
5. Skills remain content-only directories with their own `SKILL.md`, `examples/`, and `references/`.

## Consequences

- **Easier:** Tool code, skill content, and tests each have a single, obvious home.
- **Easier:** The skill-structure validator can enforce "no executable code in skills" as a simple rule.
- **Easier:** The consolidated CLI can be type-hinted and tested as a normal Python application.
- **More difficult:** Every skill path reference in `Makefile`, `scripts/`, tests, and docs must be updated during the move.
- **More difficult:** The `npx skills add ... --all` discovery path must be verified against the new `skills/` location before the move is considered complete.

## Alternatives Considered

- **Edit ADR-016 in place.** Rejected. ADRs are immutable once accepted; amendments are recorded by new ADRs referencing the old.
- **Leave the layout caveat in place and work around it.** Rejected. It would make the extraction PRD's layout goals contradict an accepted ADR.
- **Keep exec dispatch permanently and put the package under `aet-work/`.** Rejected. It would perpetuate the fragmented binary model that the extraction PRD identifies as a source of bugs and review friction.
