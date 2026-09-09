---
subject: version-from-git-tag
---

# The Version Derives From the Git Tag

## Status

Accepted. Applies the ADR-037 runtime dependency policy to build-time
versioning.

## Context

`pyproject.toml:7` declares `version = "1.3.0"`. The `v1.4.0` tag was cut from
that commit:

```
$ git show v1.4.0:pyproject.toml | grep '^version'
version = "1.3.0"
```

So every v1.4.0 install reports `aet 1.3.0`. This is not cosmetic in effect: the
2026-07-22 bug reporter could not state which version they were running, which
is the first question any maintainer asks, and it made two genuine defects
harder to attribute.

The version exists in two places — `pyproject.toml` and the git tag — reconciled
by a human remembering to edit one before creating the other. `aet release-prep`
computes `nextVersion` (`src/aet/cli/release_prep.py:216`) but nothing writes it
back; no code in `src/aet/` mutates the pyproject version. There is no gate, so
the only feedback is a user reporting a wrong number after release.

The obvious fix is a release-time check that fails when tag and version diverge.
That was the initial proposal here and it is a detector for a condition that
should not be representable. It leaves two sources of truth and adds a third
thing to maintain — the check itself — to catch a human step that remains
manual. The next release still depends on someone remembering; the gate only
shortens the feedback loop from "a user reports it" to "the release fails."

The build backend is already `hatchling` (`pyproject.toml:1-3`). Its companion
plugin `hatch-vcs` derives the package version from the git tag at build time,
so the two cannot disagree. ADR-037 states the policy directly: dependencies are
adopted for solved problems, and "the toolkit stops maintaining brittle
reimplementations of solved problems."

## Decision

**The git tag is the single source of truth for the version.**

1. `hatch-vcs` is added to `[build-system].requires`, and
   `[project].version` is replaced by `dynamic = ["version"]` with the
   `hatch-vcs` source configured. The static version string is deleted.

2. `aet --version` continues to read `importlib.metadata.version("aet")`
   (`src/aet/cli/main.py:178-180`) — unchanged code, now reporting a value that
   is derived from the tag rather than hand-maintained.

3. Cutting a release is `git tag`. There is no version to bump, so there is no
   bump to forget and no gate needed to catch forgetting it.

4. `aet release-prep` keeps reporting the suggested next version. Its output
   becomes advice for choosing the tag rather than an instruction to edit a
   file.

5. Between tags, the derived version carries a development suffix
   (e.g. `1.4.0.dev3+g5b2db1a`). This is desirable: a bug report from an
   unreleased checkout is now self-identifying.

## Consequences

- **Easier:** The reported version cannot disagree with the tag. The defect
  class is removed rather than detected.
- **Easier:** One fewer manual release step, and one fewer gate to maintain.
- **Easier:** Development builds identify their exact commit in bug reports.
- **More difficult:** Building requires git metadata. Source builds from a
  tarball without `.git` need the fallback version that `hatch-vcs` writes into
  the sdist; this must be verified, not assumed.
- **More difficult:** Contributors lose the ability to read the version out of
  `pyproject.toml`. `aet --version` or `hatch version` replaces that.
- **Risk:** The installer clones with tags present (`scripts/install.sh` uses a
  full `git clone`, then `checkout <tag>`), so tag-derived versioning works on
  the install path. A future move to `--depth 1` without `--tags` would silently
  degrade the version. Noted here so the constraint is discoverable.

## Alternatives Considered

- **Add a release gate that fails on tag/version mismatch** — rejected, and this
  was the initially chosen option. It detects the drift rather than preventing
  it, preserves two sources of truth, and adds a check to maintain in order to
  police a step that stays manual. It is strictly more machinery for strictly
  less guarantee than deriving the value.

- **Have `aet release-prep` write the bump** — rejected: turns a reporting
  command into a mutating one, and a wrong automatic bump is a worse failure
  than a caught mismatch. It also still leaves the tag as a separate step that
  can disagree.

- **Just fix the number to 1.4.0** — rejected: it recurs at v1.5.0. Necessary as
  part of this change only in the sense that the static field is deleted.

- **`setuptools-scm`** — equivalent capability, rejected only because the build
  backend is `hatchling`; `hatch-vcs` is the same idea without changing
  backends.
