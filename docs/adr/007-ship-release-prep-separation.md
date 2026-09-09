---
subject: release-prep-separation
---

# Separate Release Preparation from Merge Gating

## Status

Accepted

## Context

`aet-ship` has historically described itself as handling "changelog generation" alongside pre-merge validation and PR creation. This created ambiguity:

- Users conflated commit-level message conventions (bisectable commits) with project-level release documentation (CHANGELOG.md, PRODUCT.md)
- Multiple features can be merged without an immediate release, making release docs a distinct lifecycle phase
- The toolkit's own `CONVENTIONS.md` anticipated a "future skill" for release versioning

## Decision

Create `aet-release-prep` as a standalone skill that owns release documentation. `aet-ship` retains pre-merge gating only.

| Concern                                             | Owner              |
| --------------------------------------------------- | ------------------ |
| Bisectable commits, PR creation, merge verification | `aet-ship`         |
| CHANGELOG.md, PRODUCT.md, version bump suggestions  | `aet-release-prep` |

Release-prep runs after ship, when maintainers decide to cut a release.

## Consequences

- **Clearer mental model:** Each skill has a single responsibility
- `aet-ship` no longer needs to know about project-level documentation formats
- `aet-release-prep` can adapt to different project stacks (package.json, VERSION file, or git tags)
- A new skill directory, script, and documentation must be maintained

## Alternatives Considered

- **Merge into `aet-ship`:** Rejected. Release documentation is not always needed after every merge, and the skill would become too broad.
- **Keep as external skill:** Rejected. Release preparation is a core part of the agentic engineering lifecycle and belongs in the toolkit.
