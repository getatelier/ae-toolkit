---
subject: remove-skill-artifacts
---

# Remove `.skill` Artifacts and Packaging Build Step

## Status

Accepted

## Context

ADR-016 established that AE Toolkit should be distributed and used as a single system, not as independent skills. It demoted `.skill` zip files from the primary distribution format to "build artifacts for manual distribution." Since then, the following has become clear:

- The documented and recommended install path — `npx skills add https://github.com/thebrightnest/ae-toolkit --all` — discovers skill directories directly in the repository. It never consumes `.skill` files.
- No manual distribution channel, CDN, or release process uses the `.skill` artifacts.
- The `make package` target only produced `.skill` zip files. Its shared-partials assembly step required `SKILL.md.template` files, and none exist in the repository, so that step was a no-op.
- The `.skill` files were binary build artifacts committed to git. Every `make package` run rewrote zip metadata, producing meaningless diffs on all 21 archives and creating merge-conflict surface area.
- A reproducibility check (`scripts/check-reproducible-package.sh`) existed solely to combat zip timestamp churn.

Keeping the packaging machinery alive for a hypothetical future use case violates the project's preference for minimal, actually-used tooling.

## Decision

Remove the `.skill` packaging pipeline entirely:

1. Delete all `.skill` files from the repository and add `*.skill` to `.gitignore`.
2. Remove the `make package`, `make clean`, and `make check-reproducible` targets from the `Makefile`.
3. Remove `scripts/check-reproducible-package.sh`, `scripts/build-skills.py`, and the `scripts/partials/` directory.
4. Update user-facing docs (`README.md`, `AGENTS.md`, `docs/CONVENTIONS.md`, `PRODUCT.md`) to describe directory-based installation only.
5. Update `docs/upgrades/0.9.0-to-0.9.1.md` to remove the individual-skill install example.

Skills remain individual directories with their own `SKILL.md`, `examples/`, and `references/`. Only the zip packaging and unused shared-source build scaffolding are removed.

## Consequences

- **Easier:** No more binary artifact churn in git diffs or merge conflicts caused by zip metadata.
- **Easier:** One less mandatory step after editing a skill; `make validate` is the only quality gate.
- **Easier:** The install story is unambiguous: install the whole toolkit from the repo.
- **More difficult:** A user who wants a single skill must still install the whole toolkit. This is the same trade-off accepted in ADR-016.
- **More difficult:** If a future distribution channel genuinely needs `.skill` files, the build step must be reintroduced from scratch rather than revived from dead code.

## Alternatives Considered

- **Keep `.skill` files as untracked build artifacts.** Rejected. They were still not consumed by the primary install path, and generating them on demand served no real workflow.
- **Keep the shared-partials build system without zipping.** Rejected. No templates exist, so the build system was dead code. Reintroduce it only if and when shared partials are actually adopted.
- **Status quo.** Rejected. The `.skill` artifacts created measurable maintenance cost (git noise, reproducibility check, mandatory post-edit packaging) with no offsetting benefit.

## Supersedes

- ADR-016 "Distribute AE Toolkit as a System, Not Individual Skills" — the system-install narrative is retained; the `.skill` artifact exception is removed.
