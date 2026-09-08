"""CLI adapter for spawning agent sessions."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aet import session_log_agy, session_log_claude
from aet import usage as usage_lib

# Flags each usage mode needs appended to a headless invocation. Modes absent
# from this map (e.g. kimi's "wire-file", read post-exit from on-disk session
# files) need no flags — the tee already captures what they parse from.
_USAGE_MODE_FLAGS: dict[str, tuple[str, ...]] = {
    "json-envelope": ("--output-format", "json"),
    # NDJSON: one message per line, terminal payload wrapped in a ``result``
    # event. Preferred over "json-envelope" where the CLI offers it — a buffered
    # envelope is emitted only on success, so an aborted session discards every
    # token it produced, while a stream leaves the partial work on stdout.
    "json-stream": ("--output-format", "stream-json"),
}


@dataclass(frozen=True)
class CLIAdapter:
    """Configuration for invoking an AI coding agent CLI.

    The orchestrator handles the working directory via ``subprocess.run(cwd=...)``,
    so ``workdir_flag`` is ``None`` for CLIs that do not expose a dedicated
    work-directory flag (e.g. kimi, claude). ``usage_mode`` names the CLI's
    machine-readable usage output mode (parsed by ``usage.parse_usage``), or
    ``None`` when the CLI emits no usage data.

    ``stall_timeout`` and ``wall_backstop`` are supervision defaults for this
    adapter: how long a headless session may show no liveness signal before
    the watchdog kills it, and the coarse wall-clock ceiling above that
    interval. With hybrid liveness these values are uniform across adapters
    because the stall timeout is a backstop for true death, not a proxy for
    per-CLI output cadence (ADR-053, superseded in part by the liveness
    redesign). They are adapter data, not configuration.
    """

    name: str
    bin: str
    prompt_flag: str
    workdir_flag: str | None
    headless_flag: str | None
    usage_mode: str | None = None
    stall_timeout: float = 7200.0
    wall_backstop: float = 7200.0

    def build_cmd(
        self,
        prompt: str,
        workdir: str | None = None,
        headless: bool = True,
    ) -> list[str]:
        """Build the CLI invocation list."""
        cmd = [self.bin]
        if headless and self.headless_flag is not None:
            cmd.append(self.headless_flag)
        if headless and self.usage_mode is not None:
            # Before the prompt flag: some CLIs consume the token after -p as
            # the prompt value, so trailing flags would break the invocation.
            cmd.extend(_USAGE_MODE_FLAGS.get(self.usage_mode, ()))
        if self.name == "agy":
            model = os.environ.get("AET_AGY_MODEL", "gemini-3.7-flash")
            effort = os.environ.get("AET_AGY_EFFORT", "high")
            if model:
                cmd.extend(["--model", model])
            if effort:
                cmd.extend(["--effort", effort])
            # agy's own --print-timeout defaults to 5m0s, and print mode aborts
            # the whole turn when it expires — losing every token produced, since
            # the JSON envelope is emitted only at the end. On 2026-08-27 that
            # killed seven of seven stage attempts at a stage total of 302-314s
            # while this adapter's stall_timeout (7200s) never came close.
            #
            # Derived from stall_timeout rather than written as its own number:
            # a CLI deadline 24x tighter than the supervisor's is the whole bug,
            # so the two must not be independently settable.
            cmd.extend(["--print-timeout", f"{int(self.stall_timeout)}s"])
        if self.prompt_flag:
            cmd.extend([self.prompt_flag, prompt])
        else:
            cmd.append(prompt)
        if workdir and self.workdir_flag:
            cmd.extend([self.workdir_flag, workdir])
        return cmd

    def resolve_session_ref(
        self, output: str, workdir: str | None = None
    ) -> str | None:
        """Return an identifier for this adapter's session log, or ``None``.

        The identifier is adapter-defined: a session id for both kimi and
        Claude, or conversation id for Antigravity. It is intentionally not
        a filesystem path — paths go stale when an archive moves; the
        identifier plus the documented resolution rule in
        ``docs/telemetry-guide.md`` survives relocation (ADR-031).

        An unresolvable session returns ``None``; the orchestrator turns that
        into zero observed ``test_run`` records and a null
        ``session_identifier`` on the stage record.
        """
        if self.name == "kimi":
            return usage_lib.resolve_kimi_session_id_from_output(output)
        if self.name == "claude":
            return _resolve_claude_session_id(output, workdir)
        if self.name == "agy":
            return _resolve_agy_session_id(output)
        return None


ADAPTERS: dict[str, CLIAdapter] = {
    "kimi": CLIAdapter(
        name="kimi",
        bin="kimi",
        prompt_flag="-p",
        workdir_flag=None,
        headless_flag=None,
        # Usage lives in ~/.kimi-code session wire files (verified 0.23.6),
        # read post-exit via the resume hint in captured stdout.
        usage_mode="wire-file",
        # Hybrid liveness uses process-tree activity and run-log writes, so the
        # stall timeout is the same uniform backstop for every adapter.
        stall_timeout=7200.0,
        wall_backstop=7200.0,
    ),
    "claude": CLIAdapter(
        name="claude",
        bin="claude",
        prompt_flag="-p",
        workdir_flag=None,
        headless_flag="--dangerously-skip-permissions",
        usage_mode="json-envelope",
        # Hybrid liveness uses process-tree activity and run-log writes, so the
        # stall timeout is the same uniform backstop for every adapter.
        stall_timeout=7200.0,
        wall_backstop=7200.0,
    ),
    "agy": CLIAdapter(
        name="agy",
        bin="agy",
        prompt_flag="-p",
        workdir_flag=None,
        headless_flag="--dangerously-skip-permissions",
        # Streamed rather than buffered: the 2026-08-27 run lost ~6.8M tokens of
        # work because a buffered envelope prints nothing when print mode aborts.
        # The stream's terminal ``result`` event carries the same fields, so
        # usage parsing and session resolution are unchanged (verified 1.1.22).
        usage_mode="json-stream",
        stall_timeout=7200.0,
        wall_backstop=7200.0,
    ),
}


# How far up the process tree to look for the agent CLI that launched ``aet``.
# The observed chain is short (``aet`` -> shell -> agent), but an agent may put
# a wrapper or two in between; the bound keeps a pathological tree from turning
# detection into a long walk.
_ANCESTRY_MAX_DEPTH = 12


def _process_parent_and_comm(pid: int) -> tuple[int | None, str | None]:
    """Return ``(ppid, executable)`` for ``pid``, or ``(None, None)``.

    ``ppid`` is requested first because it is an unambiguous integer token; the
    remainder of the line is the executable, which may itself contain spaces.
    """
    try:
        proc = subprocess.run(
            ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        # Any failure to query the process table means "host unknown", never a
        # failed run: detection is an inference about the caller, not work.
        return None, None
    line = proc.stdout.strip()
    if not line:
        return None, None
    parts = line.split(maxsplit=1)
    try:
        ppid = int(parts[0])
    except ValueError:
        return None, None
    comm = parts[1].strip() if len(parts) > 1 else None
    return ppid, comm


def _process_argv0(pid: int) -> str | None:
    """Return ``argv[0]`` for ``pid``, or ``None``.

    A CLI shipped as a script keeps its own name in ``argv[0]`` while ``comm``
    reports the interpreter that executes it (e.g. ``node``), so this is the
    second place a host agent can identify itself.
    """
    try:
        proc = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    line = proc.stdout.strip()
    if not line:
        return None
    return line.split()[0]


def _adapter_for_executable(executable: str | None) -> CLIAdapter | None:
    """Return the adapter whose ``bin`` is the basename of ``executable``."""
    if not executable:
        return None
    name = os.path.basename(executable)
    for adapter in ADAPTERS.values():
        if name == adapter.bin:
            return adapter
    return None


def detect_host_adapter() -> CLIAdapter | None:
    """Return the adapter for the agent CLI running this process, or ``None``.

    The agent session that invoked ``aet`` is an ancestor of it, so the process
    tree names the answer outright. This is deliberately not read from the
    environment: agent CLIs are forked from one another and inherit each other's
    marker variables, so an environment probe reproduces the very bug it would
    be there to fix — an agent being told it is some other agent. A process
    cannot misreport which binary it is executing.

    Detection is a last resort, below ``--cli-bin`` and ``AET_CLI_BIN``: a
    caller that states the adapter is always believed.
    """
    pid: int | None = os.getppid()
    seen: set[int] = set()
    for _ in range(_ANCESTRY_MAX_DEPTH):
        if pid is None or pid <= 1 or pid in seen:
            return None
        seen.add(pid)
        ppid, comm = _process_parent_and_comm(pid)
        adapter = _adapter_for_executable(comm) or _adapter_for_executable(
            _process_argv0(pid)
        )
        if adapter is not None:
            return adapter
        pid = ppid
    return None


def resolve_cli_adapter(cli_bin: str | None = None) -> CLIAdapter:
    """Resolve the CLI adapter from an explicit bin, the environment, or the host.

    There is no fallback to whichever supported CLI happens to be installed.
    Presence on ``PATH`` says a CLI *could* run the work, never that it *should*:
    on a machine with several agent CLIs installed, a scan silently hands the
    run to whichever one sorts first, which is how a Claude Code session ends up
    dispatching its tasks to a different agent. When nothing states the adapter
    and no host agent can be detected, that is a question for the caller, so it
    is raised rather than guessed.
    """
    if cli_bin:
        for adapter in ADAPTERS.values():
            if adapter.bin == cli_bin or cli_bin.endswith(adapter.bin):
                return adapter
        raise ValueError(f"Unsupported CLI: {cli_bin}")

    env_bin = os.environ.get("AET_CLI_BIN")
    if env_bin:
        return resolve_cli_adapter(env_bin)

    host = detect_host_adapter()
    if host is not None:
        return host

    supported = ", ".join(ADAPTERS)
    raise RuntimeError(
        "Could not determine which agent CLI to run: no --cli-bin was given, "
        "AET_CLI_BIN is unset, and no supported agent CLI was found among this "
        f"process's ancestors. Pass --cli-bin (one of: {supported}) or set "
        "AET_CLI_BIN."
    )


def _resolve_claude_session_id(output: str, workdir: str | None) -> str | None:
    """Resolve a Claude session id from the JSON envelope.

    The envelope's ``session_id`` is the identifier; the transcript's own
    ``cwd`` record confirms the match. A missing workdir, unparseable envelope,
    missing transcript, or cwd mismatch all resolve to ``None`` — never a
    guessed identifier (ADR-031).
    """
    if not output or not workdir:
        return None
    session_id = _extract_claude_session_id(output)
    if session_id is None:
        return None
    # Claude writes transcripts under the cwd slug. A symlinked worktree
    # (e.g. ``.worktrees/foo`` -> real path) must resolve to the real cwd
    # before slugging, or the transcript lookup misses.
    resolved_workdir = str(Path(workdir).resolve())
    candidate = session_log_claude.transcript_path_for(resolved_workdir, session_id)
    try:
        with candidate.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if len(line) > usage_lib._MAX_WIRE_LINE_CHARS:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and _cwd_matches(
                    record.get("cwd"), workdir
                ):
                    return session_id
    except OSError:
        pass
    return None


def _cwd_matches(recorded_cwd: Any, workdir: str) -> bool:
    """Return True when ``recorded_cwd`` resolves to the same path as ``workdir``.

    Symlinked worktrees (e.g. ``.worktrees/foo`` pointing elsewhere) must not
    silently fail the cwd confirmation because the CLI logged the real path.
    """
    if not isinstance(recorded_cwd, str):
        return False
    try:
        return Path(recorded_cwd).resolve() == Path(workdir).resolve()
    except OSError:
        return False


def _extract_claude_session_id(output: str) -> str | None:
    """Extract the session id from Claude's JSON envelope, or ``None``."""
    text = output
    if len(text) > usage_lib.TAIL_SCAN_BYTES:
        text = text[-usage_lib.TAIL_SCAN_BYTES:]
    stripped = text.strip()
    if stripped:
        try:
            doc = json.loads(stripped)
        except ValueError:
            doc = None
        if isinstance(doc, list):
            for element in reversed(doc):
                if isinstance(element, dict):
                    sid = element.get("session_id")
                    if isinstance(sid, str) and sid:
                        return sid
        elif isinstance(doc, dict):
            sid = doc.get("session_id")
            if isinstance(sid, str) and sid:
                return sid
    result = usage_lib._find_result_element(text)
    if isinstance(result, dict):
        sid = result.get("session_id")
        if isinstance(sid, str) and sid:
            return sid
    return None


def _resolve_agy_session_id(output: str) -> str | None:
    """Resolve an Antigravity conversation id from the JSON envelope.

    The envelope's ``conversation_id`` is the identifier; confirmed by checking
    that the transcript exists on disk.
    """
    if not output:
        return None
    conv_id = usage_lib.resolve_agy_conversation_id_from_output(output)
    if conv_id is None or not session_log_agy.is_conversation_id(conv_id):
        return None
    transcript_path = session_log_agy.transcript_path_for(conv_id)
    if transcript_path.is_file():
        return conv_id
    return None
