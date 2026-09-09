"""Tests for src/aet/cli/gate.py — the fail-closed gate verdict writer."""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aet import verifier
from aet.boundary import BoundaryResult
from aet.identity import IdentityResult

_REPO_ROOT = Path(__file__).parents[2]
_GATE_BIN = _REPO_ROOT / "src" / "aet" / "cli" / "gate.py"
_AET_BIN = _REPO_ROOT / "src" / "aet" / "cli" / "main.py"

_gate_spec = importlib.util.spec_from_loader(
    "gate_bin", importlib.machinery.SourceFileLoader("gate_bin", str(_GATE_BIN))
)
gate = importlib.util.module_from_spec(_gate_spec)
sys.modules["gate_bin"] = gate
_gate_spec.loader.exec_module(gate)


def _qa_payload(**overrides) -> dict:
    record = {
        "task_id": "ewl-01-gate-submit-cli",
        "stage": "qa-complete",
        "skill": "aet-qa",
        "verdict": "pass",
        "summary": "All checks passed",
        "generated_at": "2026-07-13T00:00:00Z",
        "tree_hash": "t0",
        "test_command": "pytest tests/ -q",
        "tests_total": 10,
        "tests_passed": 10,
        "tests_failed": 0,
    }
    record.update(overrides)
    return record


def _review_payload(**overrides) -> dict:
    record = {
        "task_id": "t2r-08-boundary-contract-lens",
        "stage": "reviewed",
        "skill": "aet-review",
        "verdict": "pass",
        "summary": "Review passed",
        "generated_at": "2026-08-10T00:00:00Z",
        "tree_hash": "t0",
        "findings": [],
    }
    record.update(overrides)
    return record


class TestGateSubmit(unittest.TestCase):
    """gate submit validates and writes verdicts through the public CLI."""

    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = gate.main(argv)
        return rc, stdout.getvalue(), stderr.getvalue()

    @staticmethod
    def _write_payload(tmp: Path, record: dict) -> Path:
        payload = tmp / "payload.json"
        payload.write_text(json.dumps(record), encoding="utf-8")
        return payload

    def test_submit_writes_valid_verdict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "verdicts" / "qa.json"
            payload = self._write_payload(tmp, _qa_payload())
            with patch.dict(os.environ, {"AET_EVIDENCE_PATH": str(dest)}, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "pass",
                        "--evidence",
                        str(payload),
                    ]
                )
            self.assertEqual(rc, 0, err)
            self.assertTrue(dest.is_file(), "verdict file was not written")
            written = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(written["verdict"], "pass")
            self.assertEqual(written["task_id"], "ewl-01-gate-submit-cli")

    def test_missing_verdict_flag_exits_nonzero(self):
        rc, _out, err = self._run(
            ["submit", "--stage", "qa", "--evidence", "payload.json"]
        )
        self.assertEqual(rc, 2)
        self.assertIn("--verdict", err)

    def test_missing_evidence_flag_uses_builder_mode(self):
        """Without --evidence the command enters builder mode and validates inputs."""
        with patch.dict(os.environ, {"AET_TASK_ID": "ewl-01-gate-submit-cli"}, clear=False):
            rc, _out, err = self._run(["submit", "--stage", "qa", "--verdict", "pass"])
        self.assertEqual(rc, 1)
        self.assertIn("cannot build 'qa' verdict", err)

    def test_evidence_file_not_found_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.json"
            rc, _out, err = self._run(
                [
                    "submit",
                    "--stage",
                    "qa",
                    "--verdict",
                    "pass",
                    "--evidence",
                    str(missing),
                ]
            )
        self.assertEqual(rc, 1)
        self.assertIn("not found", err)

    def test_schema_invalid_payload_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            payload = self._write_payload(tmp, {"task_id": "t", "verdict": "pass"})
            rc, _out, err = self._run(
                [
                    "submit",
                    "--stage",
                    "qa",
                    "--verdict",
                    "pass",
                    "--evidence",
                    str(payload),
                ]
            )
        self.assertEqual(rc, 1)
        self.assertIn("invalid", err)

    def test_malformed_json_payload_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            payload = tmp / "payload.json"
            payload.write_text("{not json", encoding="utf-8")
            rc, _out, err = self._run(
                [
                    "submit",
                    "--stage",
                    "qa",
                    "--verdict",
                    "pass",
                    "--evidence",
                    str(payload),
                ]
            )
        self.assertEqual(rc, 1)
        self.assertIn("not valid JSON", err)

    def test_non_object_payload_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            payload = tmp / "payload.json"
            payload.write_text('["qa", "pass"]', encoding="utf-8")
            rc, _out, err = self._run(
                [
                    "submit",
                    "--stage",
                    "qa",
                    "--verdict",
                    "pass",
                    "--evidence",
                    str(payload),
                ]
            )
        self.assertEqual(rc, 1)
        self.assertIn("JSON object", err)

    def test_unknown_stage_exits_nonzero(self):
        rc, _out, err = self._run(
            ["submit", "--stage", "nope", "--verdict", "pass", "--evidence", "x.json"]
        )
        self.assertEqual(rc, 1)
        self.assertIn("unknown stage", err)

    def test_verdict_mismatch_exits_nonzero(self):
        """--verdict must match the payload's verdict field (no silent override)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "qa.json"
            payload = self._write_payload(tmp, _qa_payload(verdict="fail"))
            with patch.dict(os.environ, {"AET_EVIDENCE_PATH": str(dest)}, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "pass",
                        "--evidence",
                        str(payload),
                    ]
                )
            self.assertEqual(rc, 1)
            self.assertIn("does not match", err)
            self.assertFalse(dest.exists(), "mismatched verdict must not be written")

    def test_submit_stamps_tree_hash_when_absent(self):
        """Payloads following the skill writer contract (no tree_hash) are accepted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "qa.json"
            record = _qa_payload()
            del record["tree_hash"]
            payload = self._write_payload(tmp, record)
            with patch.dict(os.environ, {"AET_EVIDENCE_PATH": str(dest)}, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "pass",
                        "--evidence",
                        str(payload),
                    ]
                )
            self.assertEqual(rc, 0, err)
            self.assertTrue(dest.is_file(), "verdict file was not written")
            written = json.loads(dest.read_text(encoding="utf-8"))
            self.assertIn("tree_hash", written)
            self.assertNotEqual(written["tree_hash"], "")

    def test_submit_stamps_the_worktree_not_the_main_checkout(self):
        """A task session attests to the tree the work is in (AET_WORKTREE)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "qa.json"
            main_checkout = tmp / "main"
            worktree = tmp / "wt"
            for repo, content in ((main_checkout, "main"), (worktree, "worktree")):
                repo.mkdir()
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
                (repo / "file.txt").write_text(content, encoding="utf-8")

            record = _qa_payload()
            del record["tree_hash"]
            payload = self._write_payload(tmp, record)
            env = {
                "AET_EVIDENCE_PATH": str(dest),
                "AET_REPO_ROOT": str(main_checkout),
                "AET_WORKTREE": str(worktree),
            }
            with patch.dict(os.environ, env, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "pass",
                        "--evidence",
                        str(payload),
                    ]
                )

            self.assertEqual(rc, 0, err)
            written = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(
                written["tree_hash"], verifier.working_tree_hash(str(worktree))
            )
            self.assertNotEqual(
                written["tree_hash"], verifier.working_tree_hash(str(main_checkout))
            )

    def test_submit_preserves_explicit_tree_hash(self):
        """An explicit tree_hash supplied by the caller is not overwritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "qa.json"
            payload = self._write_payload(tmp, _qa_payload(tree_hash="abc123"))
            with patch.dict(os.environ, {"AET_EVIDENCE_PATH": str(dest)}, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "pass",
                        "--evidence",
                        str(payload),
                    ]
                )
            self.assertEqual(rc, 0, err)
            written = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(written["tree_hash"], "abc123")


class TestGateSubmitBuilder(unittest.TestCase):
    """`gate submit` can build verdict payloads from CLI options."""

    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = gate.main(argv)
        return rc, stdout.getvalue(), stderr.getvalue()

    def _write_pytest_report(self, tmp: Path, total=10, passed=9, failed=1) -> Path:
        report = tmp / "pytest-report.json"
        report.write_text(
            json.dumps(
                {
                    "summary": {
                        "total": total,
                        "passed": passed,
                        "failed": failed,
                    }
                }
            ),
            encoding="utf-8",
        )
        return report

    def test_submit_builds_qa_payload_from_pytest(self):
        """--from-pytest produces a valid qa verdict record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "qa.json"
            report = self._write_pytest_report(tmp, total=12, passed=12, failed=0)
            env = {
                "AET_EVIDENCE_PATH": str(dest),
                "AET_TASK_ID": "twe-01",
                "AET_REPO_ROOT": str(tmp),
            }
            with patch.dict(os.environ, env, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "pass",
                        "--from-pytest",
                        str(report),
                        "--summary",
                        "All tests passed",
                    ]
                )
            self.assertEqual(rc, 0, err)
            written = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(written["task_id"], "twe-01")
            self.assertEqual(written["stage"], "qa-complete")
            self.assertEqual(written["skill"], "aet-qa")
            self.assertEqual(written["verdict"], "pass")
            self.assertEqual(written["summary"], "All tests passed")
            self.assertEqual(written["tests_total"], 12)
            self.assertEqual(written["tests_passed"], 12)
            self.assertEqual(written["tests_failed"], 0)
            self.assertIn("test_command", written)

    def test_submit_qa_payload_includes_failed_test_nodeids(self):
        """--from-pytest extracts the list of failed test nodeids for gap analysis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "qa.json"
            report = tmp / "pytest-report.json"
            report.write_text(
                json.dumps(
                    {
                        "summary": {"total": 3, "passed": 1, "failed": 2},
                        "tests": [
                            {"nodeid": "tests/test_foo.py::test_pass", "outcome": "passed"},
                            {"nodeid": "tests/test_foo.py::test_fail", "outcome": "failed"},
                            {"nodeid": "tests/test_bar.py::test_fail", "outcome": "failed"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            env = {
                "AET_EVIDENCE_PATH": str(dest),
                "AET_TASK_ID": "twe-01",
                "AET_REPO_ROOT": str(tmp),
            }
            with patch.dict(os.environ, env, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "fail",
                        "--from-pytest",
                        str(report),
                        "--summary",
                        "Two tests failed",
                    ]
                )
            self.assertEqual(rc, 0, err)
            written = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(
                written["failed_tests"],
                [
                    "tests/test_foo.py::test_fail",
                    "tests/test_bar.py::test_fail",
                ],
            )

    def test_submit_builds_sync_docs_payload_from_divergence(self):
        """--divergence populates the sync-docs verdict record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "sync-docs.json"
            divergence_file = tmp / "divergence.md"
            divergence_file.write_text("PRD task list is out of date", encoding="utf-8")
            env = {
                "AET_EVIDENCE_PATH": str(dest),
                "AET_TASK_ID": "twe-02",
                "AET_REPO_ROOT": str(tmp),
            }
            with patch.dict(os.environ, env, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "sync-docs",
                        "--verdict",
                        "fail",
                        "--summary",
                        "Docs diverged from implementation",
                        "--divergence",
                        str(divergence_file),
                        "--divergence",
                        "inline divergence note",
                    ]
                )
            self.assertEqual(rc, 0, err)
            written = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(written["task_id"], "twe-02")
            self.assertEqual(written["stage"], "synced")
            self.assertEqual(written["skill"], "aet-sync-docs")
            self.assertEqual(written["verdict"], "fail")
            self.assertEqual(written["divergences"], [
                "PRD task list is out of date",
                "inline divergence note",
            ])

    def test_submit_builder_requires_task_id(self):
        """Builder mode fails closed when task_id cannot be determined."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            report = self._write_pytest_report(tmp)
            with patch.dict(os.environ, {"AET_REPO_ROOT": str(tmp)}, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "pass",
                        "--from-pytest",
                        str(report),
                    ]
                )
            self.assertEqual(rc, 1, err)
            self.assertIn("task_id", err.lower())

    def test_submit_emits_ledger_verdict_event(self):
        """A successful submit writes a verdict event to the ledger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            agents_dir = tmp / ".agents"
            agents_dir.mkdir()
            dest = tmp / "qa.json"
            report = self._write_pytest_report(tmp)
            env = {
                "AET_EVIDENCE_PATH": str(dest),
                "AET_TASK_ID": "twe-03",
                "AET_REPO_ROOT": str(tmp),
                "AET_LEDGER_PATH": str(agents_dir / "ledger.jsonl"),
            }
            with patch.dict(os.environ, env, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "pass",
                        "--from-pytest",
                        str(report),
                        "--summary",
                        "ok",
                    ]
                )
            self.assertEqual(rc, 0, err)
            ledger_path = agents_dir / "ledger.jsonl"
            self.assertTrue(ledger_path.exists(), "ledger file was not created")
            events = [
                json.loads(line)
                for line in ledger_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            verdict_events = [e for e in events if e.get("kind") == "verdict"]
            self.assertEqual(len(verdict_events), 1)
            self.assertEqual(verdict_events[0]["source"], "aet-gate")
            self.assertEqual(verdict_events[0]["task"], "twe-03")
            self.assertEqual(verdict_events[0]["payload"]["verdict"], "pass")


class TestBoundaryLens(unittest.TestCase):
    """The boundary-contract lens blocks review submits when both sides changed."""

    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = gate.main(argv)
        return rc, stdout.getvalue(), stderr.getvalue()

    def _tripped_result(self, pairs):
        shape_paths = [s for s, _c in pairs]
        consumer_paths = [c for _s, c in pairs]
        return BoundaryResult(
            tripped=True,
            reason="shape-consumer pair(s) changed without agreement test",
            shape_paths=shape_paths,
            consumer_paths=consumer_paths,
            agreement_tests=[],
            pairs=pairs,
        )

    def _clear_result(self):
        return BoundaryResult(
            tripped=False,
            reason="change set does not touch both shape and consumer sides",
            shape_paths=[],
            consumer_paths=[],
            agreement_tests=[],
            pairs=[],
        )

    def test_review_pass_refused_when_lens_trips_in_evidence_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "review.json"
            payload = tmp / "payload.json"
            payload.write_text(json.dumps(_review_payload()), encoding="utf-8")
            changed = ["src/serializers/user.py", "src/components/user.tsx"]
            pairs = [("src/serializers/user.py", "src/components/user.tsx")]
            with patch.object(
                gate.change_scope, "changed_paths", return_value=changed
            ), patch.object(
                gate.boundary, "check", return_value=self._tripped_result(pairs)
            ), patch.dict(os.environ, {"AET_EVIDENCE_PATH": str(dest)}, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "review",
                        "--verdict",
                        "pass",
                        "--evidence",
                        str(payload),
                    ]
                )
            self.assertEqual(rc, 1, err)
            self.assertIn("boundary-contract lens tripped", err)
            self.assertFalse(dest.exists(), "tripped lens must not write verdict")

    def test_review_pass_accepted_when_agreement_test_exists_in_builder_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            agents_dir = tmp / ".agents"
            agents_dir.mkdir()
            dest = tmp / "review.json"
            clear = self._clear_result()
            identity_clear = IdentityResult(
                tripped=False,
                reason="no identity conflation detected",
                findings=[],
                declaration_valid=True,
                declaration_errors=[],
            )
            with patch.object(gate.change_scope, "changed_paths", return_value=["src/utils/helpers.py"]), patch.object(
                gate.boundary, "check", return_value=clear
            ), patch.object(
                gate.identity, "check", return_value=identity_clear
            ), patch.dict(
                os.environ,
                {
                    "AET_EVIDENCE_PATH": str(dest),
                    "AET_TASK_ID": "t2r-08",
                    "AET_REPO_ROOT": str(tmp),
                    "AET_LEDGER_PATH": str(agents_dir / "ledger.jsonl"),
                },
                clear=True,
            ):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "review",
                        "--verdict",
                        "pass",
                        "--summary",
                        "Review passed",
                    ]
                )
            self.assertEqual(rc, 0, err)
            self.assertTrue(dest.is_file())
            written = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(written["verdict"], "pass")
            self.assertTrue(
                any(f.get("lens") == "boundary-contract" for f in written.get("findings", [])),
                written.get("findings"),
            )

    def test_review_pass_accepted_when_diff_touches_only_one_side(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "review.json"
            payload = tmp / "payload.json"
            payload.write_text(json.dumps(_review_payload()), encoding="utf-8")
            clear = BoundaryResult(
                tripped=False,
                reason="change set does not touch both shape and consumer sides",
                shape_paths=["src/serializers/user.py"],
                consumer_paths=[],
                agreement_tests=[],
                pairs=[],
            )
            identity_clear = IdentityResult(
                tripped=False,
                reason="no identity conflation detected",
                findings=[],
                declaration_valid=True,
                declaration_errors=[],
            )
            with patch.object(
                gate.change_scope, "changed_paths", return_value=["src/serializers/user.py"]
            ), patch.object(gate.boundary, "check", return_value=clear), patch.object(
                gate.identity, "check", return_value=identity_clear
            ), patch.dict(
                os.environ, {"AET_EVIDENCE_PATH": str(dest)}, clear=True
            ):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "review",
                        "--verdict",
                        "pass",
                        "--evidence",
                        str(payload),
                    ]
                )
            self.assertEqual(rc, 0, err)
            self.assertTrue(dest.is_file())

    def test_lens_does_not_run_for_non_review_stages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "qa.json"
            payload = tmp / "payload.json"
            payload.write_text(json.dumps(_qa_payload()), encoding="utf-8")
            changed = ["src/serializers/user.py", "src/components/user.tsx"]
            pairs = [("src/serializers/user.py", "src/components/user.tsx")]
            with patch.object(
                gate.change_scope, "changed_paths", return_value=changed
            ), patch.object(
                gate.boundary, "check", return_value=self._tripped_result(pairs)
            ), patch.dict(os.environ, {"AET_EVIDENCE_PATH": str(dest)}, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "pass",
                        "--evidence",
                        str(payload),
                    ]
                )
            self.assertEqual(rc, 0, err)
            self.assertTrue(dest.is_file())

    def test_review_ledger_event_records_lens_outcome(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            agents_dir = tmp / ".agents"
            agents_dir.mkdir()
            dest = tmp / "review.json"
            clear = self._clear_result()
            identity_clear = IdentityResult(
                tripped=False,
                reason="no identity conflation detected",
                findings=[],
                declaration_valid=True,
                declaration_errors=[],
            )
            with patch.object(gate.change_scope, "changed_paths", return_value=["src/utils/helpers.py"]), patch.object(
                gate.boundary, "check", return_value=clear
            ), patch.object(
                gate.identity, "check", return_value=identity_clear
            ), patch.dict(
                os.environ,
                {
                    "AET_EVIDENCE_PATH": str(dest),
                    "AET_TASK_ID": "t2r-08",
                    "AET_REPO_ROOT": str(tmp),
                    "AET_LEDGER_PATH": str(agents_dir / "ledger.jsonl"),
                },
                clear=True,
            ):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "review",
                        "--verdict",
                        "pass",
                        "--summary",
                        "Review passed",
                    ]
                )
            self.assertEqual(rc, 0, err)
            ledger_path = agents_dir / "ledger.jsonl"
            self.assertTrue(ledger_path.exists(), "ledger file was not created")
            events = [
                json.loads(line)
                for line in ledger_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            verdict_events = [e for e in events if e.get("kind") == "verdict"]
            self.assertEqual(len(verdict_events), 1)
            payload = verdict_events[0]["payload"]
            self.assertIn("boundary_contract_lens", payload)
            self.assertEqual(payload["boundary_contract_lens"]["tripped"], False)


class TestIdentityLens(unittest.TestCase):
    """The identity-conflation lens blocks review submits without a declaration."""

    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = gate.main(argv)
        return rc, stdout.getvalue(), stderr.getvalue()

    def _tripped_result(self, findings=None, declaration_valid=False):
        return IdentityResult(
            tripped=True,
            reason="identity conflation detected but plan declaration is missing",
            findings=findings or [{"entity": "project", "identifiers": ["projectId", "projectPath"]}],
            declaration_valid=declaration_valid,
            declaration_errors=["identity conflation detected but plan declaration is missing"],
        )

    def _clear_result(self):
        return IdentityResult(
            tripped=False,
            reason="no identity conflation detected",
            findings=[],
            declaration_valid=True,
            declaration_errors=[],
        )

    def _review_payload(self, **overrides):
        record = {
            "task_id": "t2r-09-identity-conflation-lens",
            "stage": "reviewed",
            "skill": "aet-review",
            "verdict": "pass",
            "summary": "Review passed",
            "generated_at": "2026-08-10T00:00:00Z",
            "tree_hash": "t0",
            "findings": [],
        }
        record.update(overrides)
        return record

    def test_review_pass_refused_when_identity_lens_trips_in_evidence_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "review.json"
            payload = tmp / "payload.json"
            payload.write_text(json.dumps(self._review_payload()), encoding="utf-8")
            with patch.object(
                gate.change_scope, "changed_paths", return_value=["src/api.py"]
            ), patch.object(
                gate.boundary, "check", return_value=BoundaryResult(
                    tripped=False,
                    reason="no changed paths to analyze",
                    shape_paths=[],
                    consumer_paths=[],
                    agreement_tests=[],
                    pairs=[],
                )
            ), patch.object(
                gate.identity, "check", return_value=self._tripped_result()
            ), patch.dict(os.environ, {"AET_EVIDENCE_PATH": str(dest)}, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "review",
                        "--verdict",
                        "pass",
                        "--evidence",
                        str(payload),
                    ]
                )
            self.assertEqual(rc, 1, err)
            self.assertIn("identity-conflation lens tripped", err)
            self.assertFalse(dest.exists(), "tripped lens must not write verdict")

    def test_review_pass_accepted_when_identity_declaration_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "review.json"
            clear = self._clear_result()
            with patch.object(gate.change_scope, "changed_paths", return_value=["src/utils/helpers.py"]), patch.object(
                gate.boundary, "check", return_value=BoundaryResult(
                    tripped=False,
                    reason="change set does not touch both shape and consumer sides",
                    shape_paths=[],
                    consumer_paths=[],
                    agreement_tests=[],
                    pairs=[],
                )
            ), patch.object(gate.identity, "check", return_value=clear), patch.dict(
                os.environ,
                {"AET_EVIDENCE_PATH": str(dest), "AET_TASK_ID": "t2r-09", "AET_REPO_ROOT": str(tmp)},
                clear=True,
            ):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "review",
                        "--verdict",
                        "pass",
                        "--summary",
                        "Review passed",
                    ]
                )
            self.assertEqual(rc, 0, err)
            self.assertTrue(dest.is_file())
            written = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(written["verdict"], "pass")
            lens_findings = [f for f in written.get("findings", []) if f.get("lens") == "identity-conflation"]
            self.assertEqual(len(lens_findings), 1)
            self.assertFalse(lens_findings[0]["tripped"])

    def test_lens_does_not_run_for_non_review_stages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "qa.json"
            payload = tmp / "payload.json"
            payload.write_text(json.dumps(_qa_payload()), encoding="utf-8")
            with patch.object(
                gate.change_scope, "changed_paths", return_value=["src/api.py"]
            ), patch.object(
                gate.identity, "check", return_value=self._tripped_result()
            ), patch.dict(os.environ, {"AET_EVIDENCE_PATH": str(dest)}, clear=True):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "qa",
                        "--verdict",
                        "pass",
                        "--evidence",
                        str(payload),
                    ]
                )
            self.assertEqual(rc, 0, err)
            self.assertTrue(dest.is_file())

    def test_review_ledger_event_records_identity_lens_outcome(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            agents_dir = tmp / ".agents"
            agents_dir.mkdir()
            dest = tmp / "review.json"
            clear = self._clear_result()
            with patch.object(gate.change_scope, "changed_paths", return_value=["src/utils/helpers.py"]), patch.object(
                gate.boundary, "check", return_value=BoundaryResult(
                    tripped=False,
                    reason="change set does not touch both shape and consumer sides",
                    shape_paths=[],
                    consumer_paths=[],
                    agreement_tests=[],
                    pairs=[],
                )
            ), patch.object(gate.identity, "check", return_value=clear), patch.dict(
                os.environ,
                {
                    "AET_EVIDENCE_PATH": str(dest),
                    "AET_TASK_ID": "t2r-09",
                    "AET_REPO_ROOT": str(tmp),
                    "AET_LEDGER_PATH": str(agents_dir / "ledger.jsonl"),
                },
                clear=True,
            ):
                rc, _out, err = self._run(
                    [
                        "submit",
                        "--stage",
                        "review",
                        "--verdict",
                        "pass",
                        "--summary",
                        "Review passed",
                    ]
                )
            self.assertEqual(rc, 0, err)
            ledger_path = agents_dir / "ledger.jsonl"
            self.assertTrue(ledger_path.exists(), "ledger file was not created")
            events = [
                json.loads(line)
                for line in ledger_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            verdict_events = [e for e in events if e.get("kind") == "verdict"]
            self.assertEqual(len(verdict_events), 1)
            payload = verdict_events[0]["payload"]
            self.assertIn("identity_conflation_lens", payload)
            self.assertEqual(payload["identity_conflation_lens"]["tripped"], False)


class TestGateDispatcherRouting(unittest.TestCase):
    """`aet gate submit` reaches src/aet/cli/gate.py through the dispatcher."""

    def test_gate_submit_routed_through_aet_dispatcher(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "qa.json"
            payload = tmp / "payload.json"
            payload.write_text(json.dumps(_qa_payload()), encoding="utf-8")
            env = {
                "PATH": os.environ["PATH"],
                "AET_EVIDENCE_PATH": str(dest),
                "AET_BIN_DIR": str(tmp / "aet-bin"),
                "AET_TELEMETRY_ARCHIVE_DIR": str(tmp / "telemetry"),
                "PYTHONPATH": str(_REPO_ROOT / "src"),
                # The env is built explicitly, so conftest's _isolate_ledger
                # cannot reach this child: a monkeypatched module attribute does
                # not cross a process boundary, and an env var not listed here is
                # not inherited. Without this the child discovers the real
                # repository and appends to its provenance ledger.
                "AET_LEDGER_PATH": str(tmp / "ledger.jsonl"),
            }
            # The queue path `gate submit` builds is relative, so it anchors on
            # the child's cwd. Running the child in the real checkout resolves
            # its git-refs backend and fetches `refs/aet/*` from its remote —
            # conftest's _no_real_remote guard patches a module attribute and
            # cannot cross a process boundary. A remote-less tmpdir repository
            # anchors the queue somewhere harmless.
            child_repo = tmp / "child-repo"
            (child_repo / ".agents").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(child_repo)], check=True)
            result = subprocess.run(
                [
                    sys.executable,
                    str(_AET_BIN),
                    "gate",
                    "submit",
                    "--stage",
                    "qa",
                    "--verdict",
                    "pass",
                    "--evidence",
                    str(payload),
                ],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(child_repo),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(dest.is_file(), result.stderr)
            written = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(written["verdict"], "pass")
