---
subject: runtime-dependency-policy
---

# Runtime Dependency Policy

## Status

Accepted. Supersedes the `AGENTS.md` decision log entry "Dev-only Python dependencies" and its claim that "Runtime code remains dependency-free."

## Context

The `AGENTS.md` decision log has stated that the toolkit has "Dev-only Python dependencies" and that "Runtime code remains dependency-free." That was accurate when `aet` was a thin wrapper around shell commands and standard-library modules, but it is no longer sustainable:

- `aet-work/lib/plan_parser.py` hand-rolls YAML frontmatter parsing.
- `aet-work/lib/queue.py` and `aet-work/lib/worktree.py` hand-roll file locking and stale-lock recovery.
- The CLI is 19 separate argparse binaries wired together by exec dispatch.
- The panel server is built on raw `BaseHTTPRequestHandler`.

Each of these is a small, well-understood problem for which a maintained library exists (PyYAML, `filelock`, Typer/Click, a small HTTP framework). Re-rolling them has produced real bugs and review friction. The extraction PRD therefore requires replacing hand-rolled formats, protocols, and UI machinery with dependencies.

At the same time, the toolkit's glue code — the logic that decides which subcommand to run, how to read plans, how to archive telemetry — should remain standard-library Python. Dependencies should be pull, not push.

## Decision

The runtime dependency policy is:

1. **Standard library for glue.** Orchestration, plan parsing wrappers, archive logic, and subprocess dispatch use only the Python standard library unless a compelling case is made in its own plan.
2. **Dependencies for formats, protocols, and UI.** Libraries may be adopted for: structured data formats (e.g., YAML, TOML), concurrency/locking primitives, network protocols, and CLI or HTTP user interfaces.
3. **One dependency per plan.** Each new runtime dependency gets its own plan and security review, following the vgr-04 precedent.
4. **No dependency becomes a runtime requirement accidentally.** A dependency is only introduced after the plan that owns it is approved; it is recorded in `pyproject.toml` dependencies, not hidden in a script.
5. The "Dev-only Python dependencies" / "Runtime code remains dependency-free" entries in `AGENTS.md` are superseded by this ADR.

This policy applies to the `aet` package and its tools, not to dev-only test or lint tooling.

## Consequences

- **Easier:** The toolkit stops maintaining brittle reimplementations of solved problems.
- **Easier:** Security and correctness reviews can focus on dependency choice and integration rather than parsing/locking edge cases.
- **More difficult:** Each dependency adds supply-chain surface area and must be reviewed.
- **More difficult:** Contributors must write a plan before adding a new dependency, which slows down ad-hoc imports.

## Alternatives Considered

- **Allow dependencies only in dev/test tooling.** Rejected. That is the status quo and is the root cause of the hand-rolled machinery the extraction is replacing.
- **Adopt a blanket "approved dependency list" up front.** Rejected. The specific dependencies (Typer vs. Click, which HTTP framework, etc.) are intentionally left to later plans so each choice gets proper review.
- **Make dependencies optional with fallback implementations.** Rejected. It would double the code paths and keep the hand-rolled versions alive as second-class citizens.
