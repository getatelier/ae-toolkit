---
subject: system-distribution
---

# Distribute AE Toolkit as a System, Not Individual Skills

## Status

Accepted

## Context

AE Toolkit was originally framed as a modular skill suite: one directory per skill, one `.skill` zip per skill, and a "package-deliverable" rule requiring every skill to be self-contained. This model assumed users would install skills à la carte and that each skill should be usable alone.

That assumption does not match how the toolkit is actually built or used:

- The canonical pipeline chains `aet-plan` → `aet-validate-scope` → `aet-work` → `aet-implement` → `aet-qa` → `aet-review` → `aet-cso` → `aet-sync-docs` → `aet-ship`. Installing only one skill leaves the user with broken handoffs.
- `aet-work` depends on helper binaries (`aet-state`, `orchestrator`, etc.) that live inside `aet-work/bin/`, but the installer that puts them on `PATH` lives inside `aet-setup/bin/`.
- The build system already duplicates shared partials (`preamble.md`, `guardrails.md`, `stage-table.md`) into every `SKILL.md` to maintain the illusion of self-containment.
- `npx skills add <repo> --all` already installs the entire toolkit together by discovering every skill directory in the repository.

The individual `.skill` model created maintainability cost, version-skew risk, and a misleading user message: it suggested users could pick one skill and get a coherent experience, when most skills are incomplete without the rest of the pipeline.

## Decision

AE Toolkit is a single system installed together. We will:

1. Officially recommend `npx skills add https://github.com/thebrightnest/ae-toolkit --all` as the only install path.
2. Remove individual-skill install examples from README and other user-facing docs.
3. Treat `.skill` files as build artifacts for manual distribution, not as the primary distribution format.
4. Relax the package-deliverable rules so cross-cutting conventions can live in shared partials and toolkit-level docs instead of being duplicated into every skill.
5. Allow skills to reference each other and shared conventions by name, since the whole system is present at runtime.

Skills remain in individual directories with their own `SKILL.md`, `examples/`, and `references/`. We are changing the distribution narrative and authoring rules, not the directory layout.

## Consequences

- **Easier:** Maintainers no longer need to duplicate every cross-cutting rule across 21 skills. Shared partials become a single source of truth.
- **Easier:** The install story is simpler and honest about what users are getting.
- **Easier:** Skills can describe their real dependencies (e.g., "run `aet-validate-scope` next") without defensive self-containment.
- **More difficult:** A user who genuinely wants only one capability still receives the whole toolkit. We accept this trade-off because the toolkit is designed as a pipeline, not a library of independent utilities.
- **More difficult:** Skill files pasted individually into chat will not include toolkit-level context. We mitigate this by keeping essential trigger and behavior rules inside each `SKILL.md`.

## Alternatives Considered

- **Monolithic single `.skill` bundle.** Rejected for this narrative change. It would require restructuring the build and may not map cleanly to `npx skills`. Kept as a future option if the installer ecosystem evolves.
- **Layered bundles (`aet-core.skill` + satellites).** Rejected for now. It better matches actual coupling but adds complexity before we have validated the simpler "install all" narrative.
- **Status quo with dependency manifests.** Rejected. It would preserve the fragmentation and only add metadata overhead without solving duplication or version skew.
