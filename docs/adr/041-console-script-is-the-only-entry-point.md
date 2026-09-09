---
subject: console-script-entry-point
---

# The Console Script Is the Only Entry Point

## Status

Accepted. Reverses the on-invocation self-repair decision locked in
`docs/plans/cli-04-aet-install-self-repair.md` (2026-07-11). Supersedes R-8 of
`docs/prds/uv-one-line-installer-prd.md`.

## Context

The toolkit currently has **three** mechanisms answering the same question —
how does `aet` get onto `PATH` and run under an interpreter that can import it?

1. `scripts/install.sh` `link_aet_binary()` — symlinks `<bin-dir>/aet` at the
   venv console script.
2. `_ensure_path_link()` + `aet install` (`src/aet/cli/main.py`) — the CLI
   rewriting its own symlink, on every non-`install` subcommand.
3. The module-level bootstrap guard (`main.py:35-49`) — re-execing into a
   discovered venv when the running interpreter cannot import `aet`.

Every defect in `docs/bugs/2026-07-22-fresh-install-v140-installer-and-path-link-failures.md`
is one of these colliding with another:

- Mechanism 2 overwrites mechanism 1's correct link with
  `site-packages/aet/cli/main.py`, because `_running_script()` returns
  `Path(__file__)` — a module, not an entry point.
- Mechanism 3 exists to make the resulting bad link work anyway: it re-execs
  into a venv so a directly-invoked `main.py` can import its own package. It is
  a compensator for mechanism 2's wrong target.
- On a packaged install mechanism 3 cannot succeed — from
  `site-packages/aet/cli/main.py` its candidate roots resolve inside
  `venv/lib/pythonX.Y/`, where no `.venv/bin/python` or `bin/python` exists — so
  it falls through to the import at line 58 and raises `ModuleNotFoundError`.
  It only appears to work in a source checkout, where walking four parents up
  from `src/aet/cli/main.py` lands on the repo root and finds `.venv/bin/python`.
  That layout coincidence is why this shipped.

The decision being reversed was correct when it was made. `cli-04` locked
"the invoked copy wins" when `aet` was a **source-checkout script** at
`aet-work/bin/aet`. There, `Path(__file__)` genuinely was the entry point, the
tie-break between checkouts was meaningful, and `_is_worktree_copy()` was the
guard that kept ephemeral copies from claiming the link. `uvi-02` changed
deployment to a **packaged console script** in a venv and invalidated that
premise without revisiting what rested on it.

Two facts establish that narrowing mechanism 2 again is the wrong move:

1. **The knowledge existed and was applied too narrowly.** R-8 of
   `uv-one-line-installer-prd.md` states that `aet install` "links
   `Path(__file__)` inside the installed package, which only resolves correctly
   for the editable dev path and would produce a broken link from a
   non-editable venv" — and concluded only that the installer must not *call*
   `aet install`. The same code runs from the app callback on every subcommand.
   The mitigation addressed one caller and left the mechanism.

2. **This is the second corruption incident.** `.agents/learnings.jsonl`
   (2026-07-15) records a pipeline stage inside the `vgr-04` worktree
   re-pointing the global `~/.local/bin/aet` at an ephemeral worktree copy,
   which dangled on cleanup. That entry's own proposed fix was "the installer
   should refuse to re-point global symlinks when invoked from inside a
   `.worktrees/` path" — i.e. narrow the mechanism. `cli-04` did exactly that.
   The mechanism survived and produced the 2026-07-22 incident. A third
   narrowing is the same move a third time.

Nothing depends on the direct-script invocation mode that mechanism 3 serves.
The Makefile uses `python -m aet.cli.main` (`Makefile:100-101`), `scripts/skills-lint`
imports `from aet.cli.main import app`, and `[project.scripts]` declares
`aet = "aet.cli:main"`. The only artifact that invokes `main.py` as a bare file
is the symlink mechanism 2 wrongly creates.

## Decision

**A console script installed by the packaging system is the only supported way
to invoke `aet`.** Everything that exists to work around not having one is
deleted.

1. **On-invocation self-repair is removed.** `_ensure_path_link()`,
   `_running_script()`, and the callback call site are deleted. No `aet`
   subcommand mutates `<bin-dir>/aet` as a side effect of running.

2. **The direct-script invocation mode is removed.** The `#!/usr/bin/env python3`
   shebang, the `if __name__ == "__main__"` block, and the module-level
   bootstrap guard (`main.py:35-49`) are deleted. Supported invocations are the
   `aet` console script and `python -m aet.cli.main`; both guarantee an
   interpreter that can import the package, so the guard has nothing to guard.

3. **Linking is an explicit command, not a side effect.** `aet install` is
   replaced by `aet setup link`, which targets the running environment's console
   script (`Path(sys.executable).parent / "aet"`) and never `__file__`. It keeps
   the existing semantics: repair an AET-managed symlink, refuse a non-symlink
   collision, print the `export PATH=` line when the bin dir is off `PATH`.

4. **A link pointing elsewhere is not evidence of staleness.** It is the
   expected state when a machine has more than one `aet`. Deciding it is wrong
   and silently correcting it is the behavior being removed. Detection moves to
   `aet setup verify` (ADR-042), which reports and does not mutate.

5. **`_is_worktree_copy()` is retained**, with `aet setup link` as its only
   caller. R-9 of `uv-one-line-installer-prd.md` requires the installer never
   link from a `.worktrees/` path, and the 2026-07-15 incident is why.

## Consequences

- **Easier:** A working install stays working. Running the tool can no longer
  break the tool.
- **Easier:** Multiple `aet` installations coexist instead of fighting over one
  symlink.
- **Easier:** One writer for the link, in a command the user explicitly runs.
- **Easier:** `main.py` loses its import-time side effects — no `os.execv` at
  module scope, which also removes a surprise for anything importing the app.
- **Easier:** Net deletion. Three mechanisms become one.
- **More difficult:** A user who deletes or dangles the link must run
  `aet setup link` (or re-run the installer) instead of having it silently
  restored. This is the cost `cli-04` paid to avoid; it is accepted here because
  the automatic restore was restoring a broken target.
- **Risk:** Users on a self-repairing build hold a link pointing at
  `site-packages/…/main.py`. Re-running the installer repoints it. Release notes
  must say so.
- **Risk:** Any user or script invoking `main.py` by file path breaks. Audited:
  no such caller exists in the repo. Called out in release notes regardless.

## Alternatives Considered

- **Fix `_running_script()` and keep self-repair** — rejected: corrects the
  target but preserves "invoked copy wins," so a second `aet` still hijacks the
  link merely by running, and mechanism 3 must stay to compensate.

- **Keep self-repair, narrowed to dangling links only** — rejected, and this was
  the closest call. It fixes both observed incidents and preserves `cli-04`'s
  intent. Rejected because it is the third consecutive narrowing of a mechanism
  with two corruption incidents behind it, and because the benefit it buys — a
  restore the user can trigger with one command — does not justify an implicit
  filesystem write on every invocation of every subcommand.

- **Keep the bootstrap guard as defense in depth** — rejected: it cannot succeed
  on a packaged install (its candidate roots do not exist there), it works in a
  source checkout only by directory-layout coincidence, and its only beneficiary
  is the invocation mode this ADR removes. Retaining it would preserve the
  illusion that direct-script invocation is supported.

- **Have `install.sh` call `aet install`** — rejected by R-8 for producing a
  broken link from a non-editable venv. Decision 3 fixes the target, which would
  make it viable; ADR-042 adopts it deliberately for a different reason.

- **Ship a wrapper script instead of a symlink** (the workaround in the user's
  report) — rejected as the default: it works precisely because
  `_ensure_path_link()` skips non-symlink collisions, i.e. it is a defense
  against the behavior this ADR deletes. With self-repair gone, a symlink is the
  simpler artifact and keeps `readlink` diagnostics meaningful.
