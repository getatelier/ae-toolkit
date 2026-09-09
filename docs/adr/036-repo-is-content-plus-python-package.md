---
subject: repo-is-content-plus-python-package
---

# Repository Is Content Plus Python Package

## Status

Accepted. Supersedes the `AGENTS.md` decision log entry "Markdown-only repo."

## Context

`AGENTS.md` has described the repository as "Markdown-only" — no `package.json`, no runtime `requirements.txt`, and quality tools installed only via pre-commit or the system package manager. That decision was correct when the toolkit was pure skill content, but it no longer matches the work underway in
[docs/prds/aet-package-extraction-prd.md](../prds/aet-package-extraction-prd.md):

- The `aet` CLI is real Python code spread across `aet-work/bin/`, `aet-work/lib/`, `aet-ship/bin/`, `aet-evolve/bin/`, `aet-setup/bin/`, and `aet-setup/lib/`.
- It is held together by `sys.path` hacks and an exec-based multicall dispatcher.
- Tests live in a root `tests/` directory and import code through those hacks.
- Extracting that code into an installable package is the stated goal of Track A.

Calling the repo "markdown-only" therefore creates a documentation↔code reality gap. The repo is content *and* a Python tool, and the decision record must say so before the extraction lands.

## Decision

The AE Toolkit repository contains both skill content and a versioned Python package:

1. Tool code lives under `src/aet/` in a standard Python src layout.
2. Skill content lives under `skills/` (see ADR-038).
3. Documentation, ADRs, and repo-maintenance scripts remain at the repository root.
4. The package is installable with `pip install -e .` and exposes the `aet` console entry point.
5. The "Markdown-only repo" entry in `AGENTS.md` is superseded by this ADR.

This does not change the content format of skills (Markdown with YAML frontmatter) or the documentation-first culture of the repository.

## Consequences

- **Easier:** The repository structure matches reality, so contributors do not have to ignore an official decision to write or import Python code.
- **Easier:** Normal Python tooling — editable installs, pytest imports, packaging standards — works without `sys.path` workarounds.
- **More difficult:** The repo now has a build/packaging surface (`pyproject.toml`) that must be maintained.
- **More difficult:** Tool code changes can introduce runtime dependency and security questions that pure content changes do not (see ADR-037).

## Alternatives Considered

- **Keep "markdown-only" and move all Python code out of the repo.** Rejected. The toolkit *is* the pipeline of `aet` commands; splitting the code into a separate repository would fragment the source of truth and break the skill↔tool co-evolution that makes the pipeline work.
- **Describe the repo as "content-first" instead of content + package.** Rejected. "Content-first" is vague; it does not authorize the src layout or editable install that the extraction requires.
- **Wait until after extraction to record the decision.** Rejected. ADRs are supposed to record decisions *before* code moves (see ADR-002 planning-implementation lockout). Recording the decision afterwards would make the ADR a post-hoc rationalization.
