---
subject: installer-bootstrap
---

# The Installer Is a Bootstrap, Not a Program

## Status

Accepted. Refines `docs/prds/uv-one-line-installer-prd.md` R-1, R-2, R-6, R-8
without changing the user-facing contract of the one-liner.

## Context

`scripts/install.sh` is 257 lines of bash that must run under whatever shell the
`curl … | bash` one-liner lands in. On macOS that is GNU bash 3.2.57, frozen
since 2007. The script does far more than bootstrap:

- ~90 lines of hand-rolled flag parsing (`while`/`case`/`shift`)
- agent validation and skills-directory resolution
- array marshalling of arguments destined for a Python program
- symlink creation, staleness detection, and collision handling
- summary reporting

Only the first stages *need* to be shell: acquiring `uv`, cloning the repo, and
creating the venv all necessarily precede the existence of an importable `aet`.
Everything after `uv pip install` runs on a known-good interpreter with the
package available.

Meanwhile the logic being duplicated in bash already exists in Python:
`src/aet/cli/setup.py` implements `_resolve_target_dirs()`, the agent→directory
mapping, and `_link_skill()`. `install.sh` calls out to `aet setup skills` for
the actual linking — but marshals its arguments in bash first. That marshalling
is the entire cause of the 2026-07-22 install failure:

```bash
local skills_args=()
…
AET_REPO_ROOT="$REPO_DIR" "$AET_BIN" setup skills "${skills_args[@]}"
```

With no flags the array is empty, and bash ≤ 4.3 treats expanding an empty array
under `set -u` as an unbound-variable error. The documented no-flag one-liner —
the exact command in the README — is the one configuration that fails. The same
defect sits at line 193 in the `--dry-run` branch.

The conventional fix is the `${arr[@]+"${arr[@]}"}` guard. It is correct and it
is two lines. It is also a patch on an instance: `scripts/validate-skills.sh`
expands `"${SKILL_DIRS[@]}"` at three sites under `set -euo pipefail` and is
safe today only because `skills/` is never empty. bash 3.2 has a long tail of
adjacent footguns (`mapfile`, `read -a`, associative arrays, `${var^^}`), and
every line of install-time logic written in bash is future surface for them.

ADR-037 already sets the relevant policy: standard library for glue,
dependencies and existing implementations for solved problems — "the toolkit
stops maintaining brittle reimplementations."

## Decision

**`scripts/install.sh` does only what must happen before Python is available.
Everything else is a Python subcommand.**

1. **The bash boundary is `uv pip install`.** The script bootstraps `uv`,
   resolves the tag, clones or updates the repo, creates the venv, and installs
   the package. Then it hands off.

2. **No argument marshalling in shell.** The script forwards `"$@"` to the
   installed CLI rather than parsing flags into arrays and reconstructing them.
   Flag parsing, validation, and defaults live in Typer, which already does it.
   The array that caused the outage stops existing — it is not guarded, it is
   removed.

3. **Post-bootstrap work is `aet setup`.** Skills linking is already
   `aet setup skills`. Symlink creation moves to `aet setup link` (ADR-041), and
   post-install verification becomes `aet setup verify`.

4. **The installer verifies its own outcome.** After linking, `aet setup verify`
   resolves what `aet` actually runs on `PATH` and reports when it is not the
   copy just installed — the PATH-shadowing case, where an install succeeds and
   changes nothing the user will experience. It reports; it does not edit `PATH`,
   shell profiles, or other installations. It is also a standalone diagnostic a
   user can run later.

5. **The remaining shell is held to a portability floor.** What stays is
   exercised under `/bin/bash` explicitly, so the version under test is the one
   macOS users have rather than whichever bash leads `PATH`.
   `scripts/validate-skills.sh` gets the `${arr[@]+…}` guard, because it is not
   on the installer path and does not justify a rewrite.

The user-facing contract is unchanged: the same one-liner, the same flags, the
same idempotence, the same `--dry-run`.

## Consequences

- **Easier:** Install logic becomes testable with the existing pytest suite, in
  the same language as the rest of the toolkit, instead of via subprocess
  assertions against shell.
- **Easier:** Flag handling, `--help`, and validation come from Typer for free
  and stay consistent with every other `aet` command.
- **Easier:** `aet setup verify` gives users and support a single command that
  answers "is my install actually the one running?"
- **Easier:** Net deletion — roughly 130 lines of bash removed, ~70 lines of
  Python added, with the bash-3.2 exposure of the remainder cut to bootstrap.
- **More difficult:** One extra process hop between bootstrap and setup. The
  failure mode is a clear non-zero exit from a Python program rather than a
  shell error, which is an improvement in diagnosis.
- **More difficult:** A failure *before* the hand-off still surfaces as a shell
  error, so the bootstrap section must keep its explicit `error()` messages.
- **Risk:** `--dry-run` must be honored on both sides of the boundary. Covered
  by requirement and test rather than convention.

## Alternatives Considered

- **Add the `${skills_args[@]+"${skills_args[@]}"}` guard and stop** — rejected
  as the *durable* answer, though it is the correct emergency patch. It fixes
  two lines and leaves ~90 lines of hand-rolled bash arg parsing and the whole
  bash-3.2 footgun surface in the highest-stakes, least-tested code path the
  project ships. `validate-skills.sh` demonstrates the class recurring already.
  Available as a hotfix if a release is needed before this lands.

- **Rewrite the installer in POSIX `sh`** — rejected: portability by
  subtraction. It removes arrays by removing the feature rather than the need,
  and still leaves install logic in a language with no test story here.

- **Require bash 4+ via the shebang** — rejected: macOS ships 3.2 permanently,
  and the documented invocation pipes into `bash`, so the shebang is not even
  consulted.

- **Move the bootstrap into Python too** (a `pipx`/`uvx` one-liner) — rejected
  for now: it trades a controlled shell bootstrap for a dependency on the user
  already having a specific Python tool, which is the problem the installer
  exists to solve. Revisit if `uv` becomes assumable.

- **Have the installer fix PATH shadowing** (reorder `PATH`, uninstall the other
  copy, edit the shell profile) — rejected: `cli-04` already rejected editing
  shell profiles as "the wrong kind of magic," and removing a package the user
  installed elsewhere is outside an installer's remit. Report, don't reach.
