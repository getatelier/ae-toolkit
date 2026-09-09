# Examples for aet-work

This directory contains usage examples for aet-work.

The skill supports git-refs task storage with optional projections:

- **git-refs backend** (default): stores queue state and ledger events under `refs/aet/*`.
- **GitHub Issues projection** (opt-in): mirrors tasks as GitHub issues and AET states as labels. Requires the `gh` CLI and a configured repository.

See [`../references/github-backend.md`](../references/github-backend.md) for the GitHub projection label contract, `gh` CLI requirements, and sync behavior.
