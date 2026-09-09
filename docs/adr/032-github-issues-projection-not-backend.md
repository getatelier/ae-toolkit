---
subject: projection-axis
supersedes: [14]
---

# GitHub Issues Is a Projection, Not a Backend

## Status

Accepted. Supersedes ADR-014 (Optional GitHub Issues Adapter for the Work Queue).

## Context

ADR-014 offered GitHub Issues as an optional *backend adapter* while keeping JSON as the canonical default. It described a "GitHub backend" that mirrored tasks as issues and AET states as labels, with the local JSON queue continuing to hold scheduling state.

When the forge-projection work was grounded, three facts made that framing untenable:

1. **`task_backend: "github"` never stored state in GitHub.** Its `load` and `save` methods read and wrote the local JSON queue file. Selecting "GitHub" only attached label side-effects to transitions; the ledger stayed on disk.
2. **`task_backend: "both"` was unimplemented.** The configuration value that would have expressed "git-refs ledger *and* GitHub Issues" raised `NotImplementedError`, so users could not ask for the actually desired shape.
3. **Storage and visibility are different axes.** Whether the ledger lives in JSON, git-refs, or another durable store is independent of whether a forge such as GitHub Issues receives a one-way mirror of state.

Treating GitHub Issues as a backend therefore described a capability that did not exist, while hiding the real capability — a projection — behind a storage-shaped config value.

## Decision

Projections are an axis **orthogonal to storage**. No configuration value may name a forge as a source of truth.

1. **`task_backend` selects only storage.** Valid values name durable storage implementations (e.g., `json`, `git-refs`). Values such as `github` or `both` are removed.
2. **A projection is a one-way mirror.** It receives state changes from the single state writer and updates an external surface (issue labels, issue state). It never writes back into AET state. A forge is never read for *state*; reading human-declared *intent* (for example, an `aet:sprint` label that gates sprint intake) is a distinct, permitted operation. The source-of-truth fence is unchanged.
3. **Projection config lives under a separate `projections` key.** The config shape is a list so additional forge types can be added without touching storage configuration.
4. **GitHub Issues is the first projection type.** It is optional, opt-in, and creates/updates issues keyed by plan id.
5. **AET remains the only writer to GitHub Issues.** Issues are created and mutated only by the projection dispatcher; humans do not file, relabel, or close them by hand as part of the workflow.

## Consequences

- **Easier:** The config surface matches reality. A team can run `git-refs` storage and a GitHub Issues projection simultaneously, which was the intended shape all along.
- **Easier:** The standing fence "no forge as source of truth" becomes structural rather than cultural.
- **Easier:** New forge types (e.g., Azure DevOps work items) can be added as new projection implementations without touching storage backends.
- **Harder:** Existing configs that selected `task_backend: "github"` must be updated. This is acceptable because that value never stored anything in GitHub; there is no data to migrate.
- **Harder:** The projection surface needs its own failure semantics. See ADR-033.

## Relation to ADR-014

ADR-014 correctly identified the need for team visibility in GitHub Issues while preserving infra-agnostic defaults. What it framed as an optional *backend adapter* is reframed here as an optional *projection*. The JSON-queue default, the plan-file content model, and the single-writer invariant remain unchanged; only the config axis and the direction of data flow are clarified.

## Alternatives Considered

1. **Keep `task_backend: "github"` and implement real GitHub storage.** Rejected: it would make a forge authoritative, violate infra-agnosticism, and add network/forge dependencies to the storage path.
2. **Keep `task_backend: "github"` as a deprecated alias for the projection.** Rejected: it preserves a misleading storage-shaped name and weakens the structural fence.
3. **Use a boolean `github_issues: true` flag instead of a `projections` list.** Rejected: it collapses the axis back to one forge and complicates adding a second projection type later.
