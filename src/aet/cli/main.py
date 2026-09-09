"""aet — single Typer app entry point for the AE Toolkit.

All subcommands register directly on the ``app`` object below. The supported
invocations are the installed console script (``aet``) and
``python -m aet.cli.main``; both guarantee an interpreter that can import the
package, so no module-level bootstrap guard is required.
"""

from __future__ import annotations

# ruff: noqa: E402
import importlib
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import click
import typer
import typer._click.exceptions as _typer_click_exc
import typer.core as typer_core

# Ensure local src directory takes precedence over site-packages when run directly.
_src_dir = str(Path(__file__).resolve().parent.parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# Import subcommand modules. Each module exposes an ``app`` attribute that is a
# ``typer.Typer()`` instance registered under a top-level name below.
# isort: off
from aet.cli import (
    help_index,
    aet_state,
    backlog,
    breaker as breaker_cli,
    configure_backend,
    context,
    desk,
    docs,
    epic,
    gate,
    handoff,
    harness_guard,
    hooks,
    learnings,
    metrics,
    mine_learnings,
    next as next_module,
    panel,
    plan,
    plans,
    reconcile,
    release_prep,
    report,
    retro,
    setup,
    ship,
    size,
    sprint,
    status,
    sync,
    validate_workflows,
)
# isort: on
from aet import breaker, telemetry
from aet.backends.factory import (
    LegacyConfigError,
    LegacyTaskBackendError,
    QueueOutsideRepositoryError,
    create_backend,
)
from aet.cli_adapter import resolve_cli_adapter
from aet.ledger import LedgerCorruptionError
from aet.liveness import is_run_alive
from aet.plan_parser import extract_plan_spec, resolve_plan_arg
from aet.project_id import resolve_repo_root
from aet.queue import QueueIntegrityError

# Cache populated on first usage error; keys are full command path tuples.
_EXAMPLE_MAP: dict[tuple[str, ...], str] | None = None


def _example_for_path(path: tuple[str, ...]) -> str | None:
    """Return the cached runnable example for a command *path*, if any."""
    global _EXAMPLE_MAP
    if _EXAMPLE_MAP is None:
        _EXAMPLE_MAP = {
            leaf.path: leaf.example for leaf in help_index.walk_leaf_commands(app)
        }
    return _EXAMPLE_MAP.get(path)


_DID_YOU_MEAN_RE = re.compile(r"Did you mean '([^']+)'")


def _command_path_tuple(ctx: click.Context) -> tuple[str, ...]:
    """Return the command path as a tuple, normalizing the program name to ``aet``."""
    names: list[str] = []
    current: click.Context | None = ctx
    while current is not None:
        if current.info_name:
            names.append(current.info_name)
        current = current.parent
    names.reverse()
    # The first name is the runtime program name (aet, python -m ..., root in tests);
    # normalize it to the canonical "aet" prefix used by the help index.
    return ("aet",) + tuple(names[1:])


def _example_for_usage_error(exc: _typer_click_exc.UsageError) -> str | None:
    """Return a runnable example for a missing-argument or unknown-command error."""
    ctx = exc.ctx
    if ctx is None:
        return None
    path = _command_path_tuple(ctx)
    if isinstance(exc, _typer_click_exc.MissingParameter):
        return _example_for_path(path)
    message = exc.format_message()
    if message.startswith("No such command"):
        match = _DID_YOU_MEAN_RE.search(message)
        if match:
            return _example_for_path(path + (match.group(1),))
    return None


def _print_usage_error(exc: _typer_click_exc.UsageError) -> None:
    """Print a Click usage error followed by a runnable example when available."""
    exc.show()
    example = _example_for_usage_error(exc)
    if example:
        click.echo(f"Example: {example}", err=True)


class AETGroup(typer_core.TyperGroup):
    """Top-level group that teaches correct invocations on usage errors."""

    def main(
        self,
        args: Any = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        # We always run the inner Click main in non-standalone mode so we can
        # intercept usage errors and append teaching examples.  The caller's
        # requested ``standalone_mode`` then decides whether we return the code
        # or exit the process.
        try:
            result = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        except _typer_click_exc.UsageError as exc:
            _print_usage_error(exc)
            if standalone_mode:
                sys.exit(exc.exit_code)
            return exc.exit_code
        except typer.Exit as exc:
            if standalone_mode:
                sys.exit(exc.exit_code)
            return exc.exit_code
        except typer.Abort:
            if standalone_mode:
                sys.exit(1)
            return 1
        # In non-standalone mode Click returns explicit exit codes instead of
        # raising, so mirror Typer's normal standalone behaviour when requested.
        if isinstance(result, int) and result != 0:
            if standalone_mode:
                sys.exit(result)
            return result
        return result


app = typer.Typer(
    cls=AETGroup,
    help="Agentic Engineering Toolkit CLI",
    no_args_is_help=False,
    invoke_without_command=True,
    add_help_option=False,
    add_completion=False,
)

# Noun-scoped command groups.
app.add_typer(aet_state.app, name="state", help="Queue mutations and stage transitions.")
app.add_typer(backlog.app, name="backlog", help="Backlog curation commands.")
app.add_typer(breaker_cli.app, name="breaker", help="Circuit breaker inspection and reset.")
app.add_typer(desk.app, name="desk", help="Review cockpit for awaiting_merge tasks.")
app.add_typer(docs.app, name="docs", help="Documentation linting and syncing.")
app.add_typer(epic.app, name="epic", help="Active epic declaration and inspection.")
app.add_typer(gate.app, name="gate", help="Fail-closed verdict writer and review board renderer.")
app.add_typer(handoff.app, name="handoff", help="Run-scoped handoff note commands.")
app.add_typer(hooks.app, name="hooks", help="Git hook installation and management.")
app.add_typer(learnings.app, name="learnings", help="Append-only learning journal commands.")
app.add_typer(plan.app, name="plan", help="Plan-quality commands.")
app.add_typer(plans.app, name="plans", help="Bulk plan operations and corpus linting.")
app.add_typer(sync.app, name="queue", help="Work queue sync and related operations.")
app.add_typer(setup.app, name="setup", help="Setup and bootstrap commands.")
app.add_typer(ship.app, name="ship", help="Pre-merge gate, PR creation, and post-merge closure.")
app.add_typer(size.app, name="size", help="Delivered-size measurement and reporting.")
app.add_typer(sprint.app, name="sprint", help="Sprint queue management.")

# Top-level single-word commands.
app.add_typer(configure_backend.app, name="configure")
app.add_typer(context.app, name="context")
app.add_typer(harness_guard.app, name="harness-guard")
app.add_typer(metrics.app, name="metrics")
app.add_typer(mine_learnings.app, name="mine-learnings")
app.add_typer(next_module.app, name="next")
app.add_typer(panel.app, name="panel")
app.add_typer(reconcile.app, name="reconcile")
app.add_typer(release_prep.app, name="release-prep")
app.add_typer(report.app, name="report")
app.add_typer(retro.app, name="retro")
app.add_typer(status.app, name="status")
app.add_typer(validate_workflows.app, name="validate-workflows")


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version as get_version

        typer.echo(f"aet {get_version('aet')}")
        raise typer.Exit()


def _help_callback(value: bool) -> None:
    if value:
        from aet.cli.help_index import render_help_index

        render_help_index(app)
        raise typer.Exit()


@app.callback()
def _main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
    help: bool = typer.Option(  # noqa: A002  # click's conventional option name
        False,
        "--help",
        "-h",
        help="Show this help message and exit.",
        is_eager=True,
        callback=_help_callback,
    ),
) -> None:
    """Top-level callback; handles --version and --help."""
    if ctx.invoked_subcommand is None:
        from aet.cli.help_index import render_help_index

        render_help_index(app)
        # Preserve the historical exit code for a bare ``aet`` invocation; only
        # an explicit ``--help`` exits 0.
        raise typer.Exit(2)


# ---------------------------------------------------------------------------
# Orchestrator launch helpers (run / run-one)
# ---------------------------------------------------------------------------


def _generate_run_id() -> str:
    """Return a short, collision-resistant run identifier."""
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(8))
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return f"run-{timestamp}-{suffix}"


def _runs_dir() -> Path:
    """Return the canonical detached-run metadata directory."""
    return Path.cwd() / ".agents" / "runs"


def _run_dir(run_id: str) -> Path:
    """Return the per-run metadata directory."""
    return _runs_dir() / run_id


def _run_log_file(run_id: str) -> Path:
    """Return the log file path for ``run_id``."""
    return _run_dir(run_id) / "output.log"


def _wait_for_run(run_id: str) -> int:
    """Wait silently for ``run_id`` to finish and return its exit code.

    Returns the stored returncode if one already exists. Otherwise waits for
    the orchestrator pid to disappear, then allows a short grace period for the
    returncode file to be written. If the pid file is absent or unparseable and
    no returncode exists, exits non-zero with a diagnostic.
    """
    rdir = _run_dir(run_id)
    pid_file = rdir / "pid"
    rc_file = rdir / "returncode"

    if not rdir.is_dir():
        typer.echo(f"error: unknown run id '{run_id}'", err=True)
        raise typer.Exit(1)

    if rc_file.is_file():
        return int(rc_file.read_text(encoding="utf-8").strip() or "0")

    pid: int | None = None
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = None

    if pid is None:
        typer.echo(
            f"error: run '{run_id}' has no process and no returncode", err=True
        )
        raise typer.Exit(1)

    while True:
        if rc_file.is_file():
            return int(rc_file.read_text(encoding="utf-8").strip() or "0")
        if not is_run_alive(rdir):
            for _ in range(20):
                if rc_file.is_file():
                    return int(rc_file.read_text(encoding="utf-8").strip() or "0")
                time.sleep(0.1)
            typer.echo(
                f"error: run '{run_id}' exited without writing a returncode",
                err=True,
            )
            raise typer.Exit(1)
        time.sleep(0.1)


def _follow_run(run_id: str) -> None:
    """Attach to ``run_id`` and exit with its final status without echoing output."""
    exit_code = _wait_for_run(run_id)
    _print_completion_report(run_id, exit_code)
    raise typer.Exit(exit_code)


def _stage_records_for_run(run_id: str) -> list[dict[str, Any]]:
    """Read all ``stage`` telemetry records for ``run_id``, oldest first.

    The orchestrator writes the telemetry run directory into the local run
    metadata so the follower can locate it without shelling out to git.
    """
    telemetry_path_file = _run_dir(run_id) / "telemetry_dir"
    try:
        run_dir = Path(telemetry_path_file.read_text(encoding="utf-8").strip())
    except OSError:
        return []
    if not run_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in run_dir.glob("*.jsonl"):
        for record in telemetry.read_jsonl(path):
            if record.get("type") == "stage" and record.get("run_id") == run_id:
                records.append(record)
    records.sort(key=lambda r: r.get("start_time", ""))
    return records


def _format_duration(seconds: float) -> str:
    """Format a duration for the completion report."""
    if seconds < 0.01:
        return "0.0s"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


def _completion_report_lines(run_id: str, exit_code: int) -> list[str]:
    """Build a bounded completion report, one line per stage plus a result line."""
    lines = [f"Run report: {run_id}"]
    overall = "success" if exit_code == 0 else "failure"
    lines.append(f"Result: {overall} (exit {exit_code})")

    stage_records = _stage_records_for_run(run_id)
    if stage_records:
        lines.append("Stages:")
    for record in stage_records:
        names = record.get("actual_stages") or [record.get("stage", "unknown")]
        name = " → ".join(names)
        status = record.get("result", "unknown")
        duration = _format_duration(float(record.get("duration_seconds", 0) or 0))
        code = record.get("exit_code", "?")
        lines.append(f"  {name}: {status} ({duration}, exit {code})")

    if exit_code != 0:
        failing = next(
            (r for r in stage_records if r.get("exit_code", 0) != 0), None
        )
        excerpt = failing.get("output_excerpt") if failing else None
        if excerpt:
            cap = telemetry.COMPLETION_REPORT_EXCERPT_LINES
            excerpt_lines = excerpt.splitlines()
            if len(excerpt_lines) > cap:
                excerpt_lines = excerpt_lines[-cap:]
            lines.append(f"--- Output excerpt (last {cap} lines) ---")
            lines.extend(excerpt_lines)
            lines.append("---")

    return lines


def _print_completion_report(run_id: str, exit_code: int) -> None:
    """Print the bounded completion report for a finished run."""
    for line in _completion_report_lines(run_id, exit_code):
        typer.echo(line)


def _ensure_aet_importable() -> None:
    """Bootstrap PYTHONPATH for repo checkouts when ``aet`` is not installed."""
    try:
        importlib.import_module("aet")
        return
    except ImportError:
        pass

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    src_dir = repo_root / "src"
    if (src_dir / "aet" / "__init__.py").is_file():
        current = os.environ.get("PYTHONPATH", "")
        if current:
            os.environ["PYTHONPATH"] = f"{src_dir}{os.pathsep}{current}"
        else:
            os.environ["PYTHONPATH"] = str(src_dir)


def _ensure_git_is_noninteractive() -> None:
    """Stop git from waiting on a prompt nobody can answer.

    Every git call the toolkit makes is a subprocess of this process, so the
    environment set here reaches all of them — including the ones that talk to a
    remote (``fetch``, ``push``, ``ls-remote``). Without it, an SSH remote with
    no key loaded and no TTY leaves git blocked on a passphrase or host-key
    prompt until something above the toolkit gives up. Observed as a 180s hang
    on `aet state transition` and `aet gate submit` in an agent container, where
    the deadline that eventually fired belonged to the harness, not to us.

    Two rules keep this from changing anything for an operator at a terminal:

    1. ``GIT_TERMINAL_PROMPT`` is always set, because it has no config
       equivalent to override and a value of ``0`` only turns a prompt into an
       error. Both use ``setdefault``, so an explicit value from the caller wins.
    2. ``GIT_SSH_COMMAND`` is set **only when stdin is not a TTY**. With a
       terminal attached there is someone to answer, and forcing ``BatchMode``
       would break an ordinary passphrase or host-key confirmation. With no
       terminal there is nobody, so the only thing ``BatchMode`` can change is
       how long the failure takes.

    The ``core.sshCommand`` check is what makes rule 2 safe to apply. The
    environment variable outranks that config key, so setting it unconditionally
    would silently discard a custom ssh invocation — a deploy key on a CI runner
    is the case that matters. Reading the key costs one subprocess, and only on
    the non-TTY path that is currently the one hanging.
    """
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")

    if sys.stdin.isatty() or "GIT_SSH_COMMAND" in os.environ:
        return

    try:
        configured = subprocess.run(
            ["git", "config", "--get", "core.sshCommand"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return
    if configured.returncode == 0 and configured.stdout.strip():
        return

    os.environ["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=5"


def _orchestrator_path() -> Path:
    """Return the path to the orchestrator module."""
    return Path(__file__).resolve().parent / "orchestrator.py"


def _build_orchestrator_flags(
    on_failure: str | None,
    task_timeout: int | None,
    cli_bin: str | None,
    base: str | None,
    max_jobs: int = 4,
    skip_intake: bool = False,
) -> list[str]:
    """Build the forwarded flag list for the orchestrator.

    ``--isolation`` is supplied internally at its default (``standard``);
    ``--max-jobs`` defaults to 4 and is caller-tunable only for ``aet run``.

    ``--cli-bin`` is always forwarded, resolved here when the caller did not
    state one. The orchestrator is spawned detached (``start_new_session``) and
    is reparented as soon as this process exits, so by the time it would resolve
    an adapter for itself the agent session that started the run is no longer
    among its ancestors and host detection cannot see it. Resolving in the
    session and pinning the answer also puts the failure in front of the caller
    instead of in a detached log they have no reason to open.
    """
    flags = ["--max-jobs", str(max_jobs), "--isolation", "standard"]
    if on_failure is not None:
        flags.extend(["--on-failure", on_failure])
    if task_timeout is not None:
        flags.extend(["--task-timeout", str(task_timeout)])
    # An explicit value is forwarded verbatim; the orchestrator resolves it the
    # same way this process would, and the caller's literal argument stays
    # visible in the spawned argv.
    flags.extend(
        ["--cli-bin", cli_bin if cli_bin is not None else resolve_cli_adapter().bin]
    )
    if base is not None:
        flags.extend(["--base", base])
    if skip_intake:
        flags.append("--skip-intake")
    return flags


def _validate_preflight(
    *,
    plan_file: str | None = None,
    cli_bin: str | None = None,
    queue_file: str = ".agents/aet-queue",
    skip_intake: bool = False,
) -> None:
    """Validate preconditions synchronously before spawning orchestrator.

    Checks:
    1. Systemic circuit breaker is not tripped in refs/aet/breaker.
    2. Agent CLI binary resolves and is found on PATH or executable.
    3. Work queue backend can be loaded (batch mode).
    4. Target plan file exists, has valid frontmatter, and extracts a spec (run-one).
    """
    repo_root = resolve_repo_root(Path.cwd()) or Path.cwd()

    # 1. Systemic circuit breaker check
    breaker_store = breaker.BreakerStore(repo_root)
    systemic_tally = breaker_store.load()
    if breaker.systemic_tripped(systemic_tally):
        report = breaker.systemic_report(systemic_tally)
        typer.echo(f"⛔ {report}", err=True)
        raise typer.Exit(1)

    # 2. Agent CLI binary resolution
    try:
        adapter = resolve_cli_adapter(cli_bin)
        target_bin = cli_bin if cli_bin is not None else adapter.bin
        resolved_path = shutil.which(target_bin)
        if not resolved_path and not (
            os.path.isfile(target_bin) and os.access(target_bin, os.X_OK)
        ):
            typer.echo(
                f"⛔ Agent CLI binary '{target_bin}' not found on PATH or executable.",
                err=True,
            )
            raise typer.Exit(1)
    except (RuntimeError, ValueError) as exc:
        typer.echo(f"⛔ {exc}", err=True)
        raise typer.Exit(1)

    # 3. Work queue check (batch mode)
    if plan_file is None:
        try:
            history_file = str(Path(queue_file).with_name("work-history.jsonl"))
            config_path = str(Path(queue_file).with_name("aet-config.json"))
            backend = create_backend(
                config_path=config_path,
                queue_file=queue_file,
                history_file=history_file,
            )
            backend.fetch()
            backend.load()
        except (
            QueueIntegrityError,
            LegacyTaskBackendError,
            LegacyConfigError,
            QueueOutsideRepositoryError,
            LedgerCorruptionError,
        ) as exc:
            typer.echo(f"⛔ {exc}", err=True)
            raise typer.Exit(1)
        except Exception as exc:
            typer.echo(f"⛔ Work queue validation failed: {exc}", err=True)
            raise typer.Exit(1)

    # 4. Target plan file check (run-one)
    if plan_file is not None:
        plan_path = Path(plan_file)
        if not plan_path.is_file():
            typer.echo(f"⛔ Plan file not found: {plan_file}", err=True)
            raise typer.Exit(1)
        spec = extract_plan_spec(plan_path)
        if (
            spec is None
            or not spec.get("title")
            or not spec.get("frontmatter", {}).get("id")
        ):
            typer.echo(
                f"⛔ Invalid plan spec in {plan_file}: missing title or frontmatter id",
                err=True,
            )
            raise typer.Exit(1)


def _spawn_detached(argv: list[str], run_id: str) -> int:
    """Spawn the orchestrator detached and print the run ID."""
    rdir = _run_dir(run_id)
    rdir.mkdir(parents=True, exist_ok=True)
    log_file = _run_log_file(run_id)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["AET_RUN_ID"] = run_id

    with open(log_file, "a", buffering=1, encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, str(_orchestrator_path()), *argv],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
            cwd=os.getcwd(),
        )

        # Startup handshake: check child process vitality past launch window
        time.sleep(0.1)
        ret = proc.poll()
        if ret is not None:
            log.flush()
            err_output = ""
            if log_file.is_file():
                try:
                    err_output = log_file.read_text(encoding="utf-8").strip()
                except OSError:
                    pass
            if err_output:
                typer.echo(err_output, err=True)
            else:
                typer.echo(
                    f"⛔ Orchestrator process failed immediately on startup (exit code {ret}).",
                    err=True,
                )
            raise typer.Exit(ret if ret != 0 else 1)

        (rdir / "pid").write_text(str(proc.pid), encoding="utf-8")

    typer.echo(f"🚀 Started run {run_id}")
    typer.echo(f"   Log: {log_file}")
    typer.echo(f"   Report: aet run --follow {run_id}")
    return 0


@app.command()
def run(
    follow: str | None = typer.Option(None, "--follow", help="Follow an existing run id."),
    on_failure: str | None = typer.Option(None, "--on-failure", help="triage|continue|halt"),
    task_timeout: int | None = typer.Option(None, "--task-timeout", help="Per-task timeout (s)."),
    cli_bin: str | None = typer.Option(
        None,
        "--cli-bin",
        help=(
            "Agent CLI binary path. Defaults to the agent CLI that invoked aet; "
            "required when no agent CLI is detected."
        ),
    ),
    base: str | None = typer.Option(None, "--base", help="Override the worktree base branch/ref."),
    max_jobs: int = typer.Option(
        4, "--max-jobs", help="Max parallel tasks (batch mode)."
    ),
) -> None:
    """Run the orchestrator in batch mode."""
    if follow is not None:
        _follow_run(follow)
        return

    _validate_preflight(cli_bin=cli_bin, queue_file=".agents/aet-queue")

    run_id = _generate_run_id()
    flags = _build_orchestrator_flags(
        on_failure, task_timeout, cli_bin, base, max_jobs=max_jobs
    )
    flags.extend(["--run-id", run_id, "--log-file", str(_run_log_file(run_id))])
    argv = ["--queue-file", ".agents/aet-queue", *flags]
    raise typer.Exit(_spawn_detached(argv, run_id))


@app.command("run-one")
def run_one(
    plan_file: str = typer.Argument(
        ..., help="Plan file path or task ID to run."
    ),
    follow: str | None = typer.Option(None, "--follow", help="Follow an existing run id."),
    on_failure: str | None = typer.Option(None, "--on-failure", help="triage|continue|halt"),
    task_timeout: int | None = typer.Option(None, "--task-timeout", help="Per-task timeout (s)."),
    cli_bin: str | None = typer.Option(
        None,
        "--cli-bin",
        help=(
            "Agent CLI binary path. Defaults to the agent CLI that invoked aet; "
            "required when no agent CLI is detected."
        ),
    ),
    base: str | None = typer.Option(None, "--base", help="Override the worktree base branch/ref."),
    skip_intake: bool = typer.Option(
        False,
        "--skip-intake",
        help="Run a plan that fails intake validation; the bypass is recorded.",
    ),
) -> None:
    """Run the orchestrator for a single plan."""
    if follow is not None:
        _follow_run(follow)
        return

    try:
        resolved = resolve_plan_arg(plan_file)
    except ValueError as exc:
        typer.echo(f"⛔ {exc}", err=True)
        raise typer.Exit(1) from exc

    _validate_preflight(
        plan_file=resolved,
        cli_bin=cli_bin,
        skip_intake=skip_intake,
    )

    run_id = _generate_run_id()
    flags = _build_orchestrator_flags(
        on_failure, task_timeout, cli_bin, base, skip_intake=skip_intake
    )
    flags.extend(["--run-id", run_id, "--log-file", str(_run_log_file(run_id))])
    argv = ["--plan-file", resolved, *flags]
    _spawn_detached(argv, run_id)
    exit_code = _wait_for_run(run_id)
    _print_completion_report(run_id, exit_code)
    raise typer.Exit(exit_code)


def main() -> int:
    _ensure_aet_importable()
    _ensure_git_is_noninteractive()
    try:
        app()
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 0
    except QueueOutsideRepositoryError as exc:
        # A named refusal, not a traceback: the operator chose a backend that
        # cannot store anything at the path they pointed it at.
        typer.echo(f"⛔ {exc}", err=True)
        return 1
    except (LegacyTaskBackendError, LegacyConfigError) as exc:
        # A config the operator has to edit, reached by read-only commands as
        # readily as by mutating ones. The message names its own remedy; a
        # traceback buries it behind frames from the resolution path.
        typer.echo(f"⛔ {exc}", err=True)
        return 1
    except LedgerCorruptionError as exc:
        # The message carries the offending lines and the repair path. A
        # traceback is technically loud but buries both, and this is the one
        # failure whose remedy the operator has to read.
        typer.echo(f"⛔ ledger integrity failure\n{exc}", err=True)
        return 1
    return 0


# Runs under ``python -m aet.cli.main``, which is a supported invocation
# (``Makefile`` validate targets, and several subprocess tests). Without this
# the module is imported, nothing dispatches, and the process exits 0 — turning
# every ``-m`` caller into a silent no-op. The direct-script mode is what this
# module dropped: there is no shebang and no interpreter bootstrap, so an
# interpreter that cannot import ``aet`` now fails loudly at import.
if __name__ == "__main__":
    sys.exit(main())
