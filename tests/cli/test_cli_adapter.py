"""Tests for cli_adapter module."""


import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aet import cli_adapter, session_log_agy, session_log_claude
from aet.cli_adapter import (
    ADAPTERS,
    CLIAdapter,
    detect_host_adapter,
    resolve_cli_adapter,
)


class TestCLIAdapter(unittest.TestCase):
    def test_kimi_adapter(self):
        adapter = resolve_cli_adapter("kimi")
        self.assertEqual(adapter.name, "kimi")
        self.assertEqual(adapter.bin, "kimi")
        self.assertEqual(adapter.prompt_flag, "-p")
        self.assertIsNone(adapter.workdir_flag)
        self.assertIsNone(adapter.headless_flag)

    def test_kimi_build_cmd_no_headless_flag(self):
        """kimi rejects combining -p/--prompt with --yolo; use -p alone."""
        adapter = resolve_cli_adapter("kimi")
        cmd = adapter.build_cmd("run tests", headless=True)
        self.assertEqual(cmd, ["kimi", "-p", "run tests"])
        self.assertNotIn("--yolo", cmd)

    def test_claude_adapter(self):
        adapter = resolve_cli_adapter("claude")
        self.assertEqual(adapter.name, "claude")
        self.assertEqual(adapter.bin, "claude")
        self.assertEqual(adapter.prompt_flag, "-p")
        self.assertIsNone(adapter.workdir_flag)
        self.assertEqual(adapter.headless_flag, "--dangerously-skip-permissions")

    def test_agy_adapter(self):
        """R-1: Antigravity is a first-class adapter alongside kimi and claude."""
        adapter = resolve_cli_adapter("agy")
        self.assertEqual(adapter.name, "agy")
        self.assertEqual(adapter.bin, "agy")
        self.assertEqual(adapter.prompt_flag, "-p")
        self.assertIsNone(adapter.workdir_flag)
        self.assertEqual(adapter.headless_flag, "--dangerously-skip-permissions")
        self.assertEqual(adapter.usage_mode, "json-stream")
        self.assertEqual(adapter.stall_timeout, 7200.0)
        self.assertEqual(adapter.wall_backstop, 7200.0)

    def test_agy_build_cmd_requests_the_json_stream(self):
        """R-2: the terminal ``result`` event carries both the usage block and
        the conversation id, so a headless ``agy`` invocation must ask for it.

        Streamed rather than buffered: a buffered envelope prints only on
        completion, so an aborted session discards every token it produced.
        """
        adapter = resolve_cli_adapter("agy")
        cmd = adapter.build_cmd("run tests", headless=True)
        self.assertEqual(
            cmd,
            [
                "agy",
                "--dangerously-skip-permissions",
                "--output-format",
                "stream-json",
                "--model",
                "gemini-3.7-flash",
                "--effort",
                "high",
                "--print-timeout",
                "7200s",
                "-p",
                "run tests",
            ],
        )

    def test_agy_build_cmd_custom_model_and_effort(self):
        adapter = resolve_cli_adapter("agy")
        with patch.dict("os.environ", {"AET_AGY_MODEL": "gemini-3.1-pro", "AET_AGY_EFFORT": "low"}):
            cmd = adapter.build_cmd("run tests", headless=True)
            self.assertEqual(
                cmd,
                [
                    "agy",
                    "--dangerously-skip-permissions",
                    "--output-format",
                    "stream-json",
                    "--model",
                    "gemini-3.1-pro",
                    "--effort",
                    "low",
                    "--print-timeout",
                    "7200s",
                    "-p",
                    "run tests",
                ],
            )

    def test_agy_print_timeout_tracks_the_stall_timeout(self):
        """agy's own --print-timeout defaults to 5m0s and aborts the whole turn.

        Regression: seven of seven stage attempts died at a stage total of
        302-314s on 2026-08-27 while this adapter's stall_timeout was 7200s and
        never fired. The CLI deadline must not be tighter than the supervisor's,
        so it is derived from stall_timeout rather than written independently.
        """
        adapter = resolve_cli_adapter("agy")
        cmd = adapter.build_cmd("run tests", headless=True)
        self.assertIn("--print-timeout", cmd)
        passed = cmd[cmd.index("--print-timeout") + 1]
        self.assertEqual(passed, f"{int(adapter.stall_timeout)}s")
        # The bug was a CLI default 24x tighter than the supervisor's ceiling.
        self.assertGreaterEqual(int(passed.removesuffix("s")), adapter.stall_timeout)

    def test_build_cmd(self):
        adapter = CLIAdapter(
            name="test",
            bin="test",
            prompt_flag="-p",
            workdir_flag="--cwd",
            headless_flag="--headless",
        )
        cmd = adapter.build_cmd("run tests", workdir="/tmp/proj", headless=True)
        self.assertEqual(cmd, ["test", "--headless", "-p", "run tests", "--cwd", "/tmp/proj"])

    def test_build_cmd_no_workdir_flag(self):
        """When workdir_flag is None, cwd is omitted (handled by subprocess)."""
        adapter = CLIAdapter(
            name="test", bin="test", prompt_flag="-p", workdir_flag=None, headless_flag="--headless"
        )
        cmd = adapter.build_cmd("run tests", workdir="/tmp/proj", headless=True)
        self.assertEqual(cmd, ["test", "--headless", "-p", "run tests"])

    def test_build_cmd_no_headless_flag(self):
        adapter = CLIAdapter(
            name="test", bin="test", prompt_flag="-p", workdir_flag="", headless_flag=None
        )
        cmd = adapter.build_cmd("run tests", headless=True)
        self.assertEqual(cmd, ["test", "-p", "run tests"])


    def test_installed_cli_is_never_probed_on_path(self):
        """Resolution must not consult PATH: being installed is not being asked for.

        The regression this guards: on a box with several agent CLIs installed,
        a PATH probe silently handed every run to whichever adapter sorted
        first, so a Claude Code session dispatched its tasks to kimi.
        """
        with patch.object(cli_adapter, "shutil", create=True) as shutil_mock:
            with patch.object(cli_adapter, "detect_host_adapter", return_value=None):
                with patch.dict("os.environ", {}, clear=True):
                    with self.assertRaises(RuntimeError):
                        resolve_cli_adapter()
        shutil_mock.which.assert_not_called()

    def test_unsupported_cli_raises(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_cli_adapter("nonexistent")
        self.assertIn("nonexistent", str(ctx.exception))

    def test_claude_declares_json_envelope_usage_mode(self):
        """claude's headless usage data rides in its JSON output envelope."""
        adapter = resolve_cli_adapter("claude")
        self.assertEqual(adapter.usage_mode, "json-envelope")

    def test_kimi_declares_wire_file_usage_mode(self):
        """kimi usage is read post-exit from on-disk wire files; stdout
        carries only the resume hint (verified kimi 0.23.6, 2026-07-13)."""
        adapter = resolve_cli_adapter("kimi")
        self.assertEqual(adapter.usage_mode, "wire-file")

    def test_kimi_supervision_defaults_are_uniform_backstop(self):
        """kimi uses the same uniform supervision defaults as every adapter."""
        adapter = resolve_cli_adapter("kimi")
        self.assertEqual(adapter.stall_timeout, 7200.0)
        self.assertEqual(adapter.wall_backstop, 7200.0)

    def test_claude_stall_timeout_covers_a_whole_silent_session(self):
        """An adapter that emits nothing until exit has no sub-session silence
        interval, so its stall timeout must equal its wall backstop (ADR-053).

        ``json-envelope`` adds ``--output-format json``: one envelope at exit
        and no output before it. Any smaller stall timeout is a shorter wall
        clock wearing a stall detector's name, and kills healthy sessions.
        """
        adapter = resolve_cli_adapter("claude")
        self.assertEqual(adapter.usage_mode, "json-envelope")
        self.assertEqual(adapter.stall_timeout, adapter.wall_backstop)

    def test_no_adapter_stall_timeout_exceeds_its_wall_backstop(self):
        """``run_single`` enforces no wall clock of its own — only ``run_batch``
        does — so for ``aet run-one`` the stall timeout is the sole ceiling on a
        session and must never be looser than the declared backstop."""
        for name, adapter in ADAPTERS.items():
            with self.subTest(adapter=name):
                self.assertLessEqual(adapter.stall_timeout, adapter.wall_backstop)

    def test_wire_file_mode_appends_no_flags(self):
        """wire-file parsing needs no CLI flags — the tee captures the hint."""
        adapter = resolve_cli_adapter("kimi")
        cmd = adapter.build_cmd("run tests", headless=True)
        self.assertEqual(cmd, ["kimi", "-p", "run tests"])

    def test_usage_mode_flags_appended_when_headless(self):
        adapter = CLIAdapter(
            name="test",
            bin="test",
            prompt_flag="-p",
            workdir_flag=None,
            headless_flag="--headless",
            usage_mode="json-envelope",
        )
        cmd = adapter.build_cmd("run tests", headless=True)
        # Usage flags land before the prompt flag: some CLIs treat the token
        # after -p as the prompt value, so trailing flags are unsafe.
        self.assertEqual(
            cmd, ["test", "--headless", "--output-format", "json", "-p", "run tests"]
        )

    def test_usage_mode_flags_omitted_when_not_headless(self):
        adapter = CLIAdapter(
            name="test",
            bin="test",
            prompt_flag="-p",
            workdir_flag=None,
            headless_flag="--headless",
            usage_mode="json-envelope",
        )
        cmd = adapter.build_cmd("run tests", headless=False)
        self.assertEqual(cmd, ["test", "-p", "run tests"])

    def test_no_usage_mode_appends_nothing(self):
        adapter = CLIAdapter(
            name="test", bin="test", prompt_flag="-p", workdir_flag=None, headless_flag=None
        )
        self.assertIsNone(adapter.usage_mode)
        self.assertEqual(adapter.build_cmd("run tests", headless=True), ["test", "-p", "run tests"])


class TestResolveSessionRef(unittest.TestCase):
    """Adapter-resolved session references replace the orchestrator's kimi-only gate."""

    def _write_kimi_session(self, home: Path, session_id: str) -> Path:
        session_dir = home / "sessions" / "wd_proj_abc123" / session_id
        wire = session_dir / "agents" / "main" / "wire.jsonl"
        wire.parent.mkdir(parents=True, exist_ok=True)
        wire.write_text("", encoding="utf-8")
        return session_dir

    def _write_claude_transcript(
        self, home: Path, cwd: str, session_id: str, records: list[dict]
    ) -> Path:
        # Match the resolver: transcripts live under the resolved cwd slug.
        resolved_cwd = str(Path(cwd).resolve())
        transcript_dir = (
            home / ".claude" / "projects" / session_log_claude.cwd_slug(resolved_cwd)
        )
        transcript_dir.mkdir(parents=True, exist_ok=True)
        transcript = transcript_dir / f"{session_id}.jsonl"
        transcript.write_text(
            "\n".join(json.dumps(r) for r in records) + "\n",
            encoding="utf-8",
        )
        return transcript

    def test_kimi_session_reference_returns_session_id(self):
        """kimi resolution returns the session id from the resume hint."""
        output = "To resume this session: kimi -r session_stub1\n"
        adapter = resolve_cli_adapter("kimi")
        ref = adapter.resolve_session_ref(output)
        self.assertEqual(ref, "session_stub1")

    def test_claude_session_reference_resolved_from_envelope_session_id(self):
        """Claude resolves by session_id from the envelope confirmed against cwd."""
        envelope = (
            '[{"type":"system","subtype":"init","session_id":"s1","cwd":"/tmp/proj"},'
            '{"type":"result","subtype":"success","is_error":false,"session_id":"s1",'
            '"usage":{"input_tokens":2,"output_tokens":4}}]'
        )
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            adapter = resolve_cli_adapter("claude")
            self._write_claude_transcript(
                home,
                "/tmp/proj",
                "s1",
                [{"cwd": "/tmp/proj", "session_id": "s1"}],
            )
            with patch("pathlib.Path.home", return_value=home):
                ref = adapter.resolve_session_ref(envelope, workdir="/tmp/proj")
            self.assertEqual(ref, "s1")

    def test_claude_session_reference_resolved_from_single_object_envelope(self):
        """`--output-format json` emits one object, not a list — the shipped shape."""
        envelope = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": "s9",
                "result": "done",
                "usage": {"input_tokens": 2, "output_tokens": 4},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            adapter = resolve_cli_adapter("claude")
            self._write_claude_transcript(
                home, "/tmp/proj", "s9", [{"cwd": "/tmp/proj", "session_id": "s9"}]
            )
            with patch("pathlib.Path.home", return_value=home):
                ref = adapter.resolve_session_ref(envelope, workdir="/tmp/proj")
            self.assertEqual(ref, "s9")

    def test_claude_session_reference_survives_log_noise_before_envelope(self):
        """A captured tail carries CLI chatter ahead of the envelope."""
        envelope = json.dumps(
            {"type": "result", "subtype": "success", "session_id": "s9", "usage": {}}
        )
        noisy = "starting stage...\nwarming worktree\n" + envelope
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            adapter = resolve_cli_adapter("claude")
            self._write_claude_transcript(
                home, "/tmp/proj", "s9", [{"cwd": "/tmp/proj", "session_id": "s9"}]
            )
            with patch("pathlib.Path.home", return_value=home):
                ref = adapter.resolve_session_ref(noisy, workdir="/tmp/proj")
            self.assertEqual(ref, "s9")

    def test_claude_session_reference_null_when_cwd_mismatches(self):
        """A transcript at the expected path whose own cwd disagrees is not a match."""
        envelope = (
            '[{"type":"system","subtype":"init","session_id":"s1","cwd":"/tmp/proj"},'
            '{"type":"result","subtype":"success","is_error":false,"session_id":"s1",'
            '"usage":{"input_tokens":2,"output_tokens":4}}]'
        )
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            adapter = resolve_cli_adapter("claude")
            # Written at the slug the resolver will look under, but every record
            # inside claims a different cwd — the confirmation must reject it.
            self._write_claude_transcript(
                home,
                "/tmp/proj",
                "s1",
                [{"cwd": "/tmp/other", "session_id": "s1"}],
            )
            with patch("pathlib.Path.home", return_value=home):
                ref = adapter.resolve_session_ref(envelope, workdir="/tmp/proj")
            self.assertIsNone(ref)

    def test_claude_session_reference_null_when_transcript_missing(self):
        """A resolvable session_id with no transcript on disk yields no guess."""
        envelope = (
            '[{"type":"result","subtype":"success","is_error":false,'
            '"session_id":"s1","usage":{"input_tokens":2,"output_tokens":4}}]'
        )
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            adapter = resolve_cli_adapter("claude")
            with patch("pathlib.Path.home", return_value=home):
                ref = adapter.resolve_session_ref(envelope, workdir="/tmp/proj")
            self.assertIsNone(ref)

    def test_claude_session_reference_null_when_envelope_unparseable(self):
        adapter = resolve_cli_adapter("claude")
        ref = adapter.resolve_session_ref("not valid json", workdir="/tmp/proj")
        self.assertIsNone(ref)

    def test_claude_session_reference_resolves_through_symlinked_worktree(self):
        """cwd confirmation follows symlinks so linked worktrees don't resolve to null."""
        envelope = json.dumps(
            {"type": "result", "subtype": "success", "session_id": "s1", "usage": {}}
        )
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            real_dir = home / "real_proj"
            real_dir.mkdir()
            link_dir = home / "link_proj"
            link_dir.symlink_to(real_dir)
            adapter = resolve_cli_adapter("claude")
            # Claude runs in the resolved cwd and records that path on every
            # transcript line. The resolver is given the symlinked worktree.
            resolved_dir = str(real_dir.resolve())
            self._write_claude_transcript(
                home, resolved_dir, "s1", [{"cwd": resolved_dir, "session_id": "s1"}]
            )
            with patch("pathlib.Path.home", return_value=home):
                ref = adapter.resolve_session_ref(envelope, workdir=str(link_dir))
            self.assertEqual(ref, "s1")

    def _write_agy_transcript(self, home: Path, conversation_id: str) -> Path:
        transcript = session_log_agy.transcript_path_for(conversation_id, home=home)
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("", encoding="utf-8")
        return transcript

    def test_agy_session_reference(self):
        """R-3: the conversation id comes from the envelope and is confirmed
        against the transcript agy wrote for it."""
        conversation_id = "e9cd2e5f-a0e5-4f41-8ffc-ab2ee2d9b890"
        envelope = json.dumps(
            {
                "conversation_id": conversation_id,
                "status": "SUCCESS",
                "response": "done",
                "duration_seconds": 0.33,
                "num_turns": 1,
                "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._write_agy_transcript(
                home / ".gemini" / "antigravity-cli", conversation_id
            )
            adapter = resolve_cli_adapter("agy")
            with patch("pathlib.Path.home", return_value=home):
                ref = adapter.resolve_session_ref(envelope, workdir="/tmp/proj")
            self.assertEqual(ref, conversation_id)

    def test_agy_session_reference_survives_log_noise_before_envelope(self):
        conversation_id = "e9cd2e5f-a0e5-4f41-8ffc-ab2ee2d9b890"
        noisy = "ERROR: logging before google.Init: ...\n" + json.dumps(
            {"conversation_id": conversation_id, "usage": {}}
        )
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._write_agy_transcript(
                home / ".gemini" / "antigravity-cli", conversation_id
            )
            adapter = resolve_cli_adapter("agy")
            with patch("pathlib.Path.home", return_value=home):
                ref = adapter.resolve_session_ref(noisy, workdir="/tmp/proj")
            self.assertEqual(ref, conversation_id)

    def test_agy_session_reference_null_when_transcript_missing(self):
        """No transcript means no telemetry to point at — never a guessed id."""
        envelope = json.dumps({"conversation_id": "c-absent", "usage": {}})
        with tempfile.TemporaryDirectory() as tmp:
            adapter = resolve_cli_adapter("agy")
            with patch("pathlib.Path.home", return_value=Path(tmp)):
                ref = adapter.resolve_session_ref(envelope, workdir="/tmp/proj")
            self.assertIsNone(ref)

    def test_agy_session_reference_null_when_id_is_not_a_uuid(self):
        """A non-UUID id would point the reader at an attacker-shaped path."""
        conversation_id = "../../etc"
        envelope = '{"conversation_id":"%s"}' % conversation_id
        with tempfile.TemporaryDirectory() as tmp:
            adapter = resolve_cli_adapter("agy")
            with patch("pathlib.Path.home", return_value=Path(tmp)):
                self.assertIsNone(adapter.resolve_session_ref(envelope))

    def test_agy_session_reference_null_when_envelope_unparseable(self):
        adapter = resolve_cli_adapter("agy")
        self.assertIsNone(adapter.resolve_session_ref("plain text", workdir="/tmp"))

    def test_agy_session_reference_needs_no_workdir(self):
        """agy's transcript path is keyed by conversation id, not by cwd."""
        conversation_id = "e9cd2e5f-a0e5-4f41-8ffc-ab2ee2d9b890"
        envelope = json.dumps({"conversation_id": conversation_id, "usage": {}})
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._write_agy_transcript(
                home / ".gemini" / "antigravity-cli", conversation_id
            )
            adapter = resolve_cli_adapter("agy")
            with patch("pathlib.Path.home", return_value=home):
                self.assertEqual(
                    adapter.resolve_session_ref(envelope), conversation_id
                )

    def test_unknown_adapter_returns_none_session_reference(self):
        adapter = CLIAdapter(
            name="custom", bin="custom", prompt_flag="-p", workdir_flag=None, headless_flag=None
        )
        self.assertIsNone(adapter.resolve_session_ref("any output", workdir="/tmp/proj"))


if __name__ == "__main__":
    unittest.main()


class TestHostAdapterDetection(unittest.TestCase):
    """The adapter is the agent CLI that invoked ``aet``, read off the process tree."""

    def _fake_tree(self, chain):
        """Patch ancestry lookups to walk ``chain`` — a list of (pid, comm)."""
        table = {
            pid: (chain[i + 1][0] if i + 1 < len(chain) else 1, comm)
            for i, (pid, comm) in enumerate(chain)
        }

        def parent_and_comm(pid):
            return table.get(pid, (None, None))

        return patch.multiple(
            cli_adapter,
            _process_parent_and_comm=parent_and_comm,
            _process_argv0=lambda pid: None,
        )

    def test_detects_the_agent_cli_among_the_ancestors(self):
        """aet -> shell -> claude resolves claude, not the first installed CLI."""
        chain = [(100, "/bin/bash"), (200, "claude")]
        with patch.object(cli_adapter.os, "getppid", return_value=100):
            with self._fake_tree(chain):
                self.assertEqual(detect_host_adapter().name, "claude")

    def test_detection_reads_the_executable_basename_not_the_path(self):
        """An agent installed under a versioned path is still that agent."""
        chain = [(100, "/Users/x/.kimi-code/bin/kimi")]
        with patch.object(cli_adapter.os, "getppid", return_value=100):
            with self._fake_tree(chain):
                self.assertEqual(detect_host_adapter().name, "kimi")

    def test_argv0_identifies_a_script_run_by_an_interpreter(self):
        """``comm`` reports the interpreter; ``argv[0]`` still names the CLI."""
        with patch.object(cli_adapter.os, "getppid", return_value=100):
            with patch.multiple(
                cli_adapter,
                _process_parent_and_comm=lambda pid: (1, "/usr/bin/node"),
                _process_argv0=lambda pid: "/opt/agy/bin/agy",
            ):
                self.assertEqual(detect_host_adapter().name, "agy")

    def test_no_agent_ancestor_detects_nothing(self):
        """A plain terminal is not an agent session; detection must not guess."""
        chain = [(100, "/bin/bash"), (200, "login")]
        with patch.object(cli_adapter.os, "getppid", return_value=100):
            with self._fake_tree(chain):
                self.assertIsNone(detect_host_adapter())

    def test_walk_is_bounded_and_survives_a_cycle(self):
        """A self-parenting pid must end the walk, not spin it."""
        with patch.object(cli_adapter.os, "getppid", return_value=100):
            with patch.multiple(
                cli_adapter,
                _process_parent_and_comm=lambda pid: (100, "/bin/bash"),
                _process_argv0=lambda pid: None,
            ):
                self.assertIsNone(detect_host_adapter())

    def test_unreadable_process_table_detects_nothing(self):
        """A failed ``ps`` means "host unknown", never a crashed run."""
        with patch.object(cli_adapter.os, "getppid", return_value=100):
            with patch.multiple(
                cli_adapter,
                _process_parent_and_comm=lambda pid: (None, None),
                _process_argv0=lambda pid: None,
            ):
                self.assertIsNone(detect_host_adapter())


class TestResolutionPrecedence(unittest.TestCase):
    """Explicit statements outrank detection; detection outranks nothing at all."""

    def test_explicit_cli_bin_wins_over_the_host(self):
        with patch.object(cli_adapter, "detect_host_adapter") as detect:
            self.assertEqual(resolve_cli_adapter("kimi").name, "kimi")
        detect.assert_not_called()

    def test_env_bin_wins_over_the_host(self):
        with patch.dict("os.environ", {"AET_CLI_BIN": "agy"}):
            with patch.object(cli_adapter, "detect_host_adapter") as detect:
                self.assertEqual(resolve_cli_adapter().name, "agy")
            detect.assert_not_called()

    def test_host_is_used_when_nothing_is_stated(self):
        host = ADAPTERS["claude"]
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(cli_adapter, "detect_host_adapter", return_value=host):
                self.assertIs(resolve_cli_adapter(), host)

    def test_undetectable_host_raises_and_names_the_flag(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(cli_adapter, "detect_host_adapter", return_value=None):
                with self.assertRaises(RuntimeError) as ctx:
                    resolve_cli_adapter()
        message = str(ctx.exception)
        self.assertIn("--cli-bin", message)
        self.assertIn("AET_CLI_BIN", message)
        for name in ADAPTERS:
            self.assertIn(name, message)
