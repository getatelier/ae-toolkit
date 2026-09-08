"""Unit tests for the content-addressed provenance ledger."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from aet import ledger as ledger_module
from aet.ledger import (
    Ledger,
    LedgerCorruptionError,
    LedgerRootError,
    resolve_ledger_path,
    verify,
)


def _ledger(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "ledger.jsonl")


def test_deterministic_event_ids(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    event1 = ledger.write_event(
        source="sprint-add",
        task="slc-01",
        kind="cut",
        ref="abc123",
        ref_kind="plan-hash",
    )
    event2 = ledger.write_event(
        source="sprint-add",
        task="slc-01",
        kind="cut",
        ref="abc123",
        ref_kind="plan-hash",
    )
    assert event1["id"] == event2["id"]


def test_duplicate_write_is_no_op(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.write_event(
        source="sprint-add",
        task="slc-01",
        kind="cut",
        ref="abc123",
        ref_kind="plan-hash",
    )
    ledger.write_event(
        source="sprint-add",
        task="slc-01",
        kind="cut",
        ref="abc123",
        ref_kind="plan-hash",
    )

    lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    stored = json.loads(lines[0])
    assert stored["kind"] == "cut"


def test_missing_occurred_at_rejected_when_no_ref(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(ValueError, match="explicit caller-supplied occurred_at"):
        ledger.write_event(
            source="aet-state",
            task="slc-01",
            kind="land",
        )


def test_ingest_backfill_source_rejected(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(ValueError, match="reserved source rejected"):
        ledger.write_event(
            source="ingest-backfill",
            task="slc-01",
            kind="cut",
            ref="abc123",
            ref_kind="plan-hash",
        )


def test_occurred_at_differs_from_created_at(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    event = ledger.write_event(
        source="aet-state",
        task="slc-01",
        kind="land",
        occurred_at="2026-01-01T00:00:00Z",
    )
    assert event["occurred_at"] == "2026-01-01T00:00:00Z"
    assert event["created_at"] != event["occurred_at"]
    assert event["created_at"].startswith("2026-")


def test_ref_kind_required_when_ref_supplied(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(ValueError, match="ref_kind is required"):
        ledger.write_event(
            source="sprint-add",
            task="slc-01",
            kind="cut",
            ref="abc123",
        )


def test_unknown_kind_rejected(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(ValueError, match="unknown event kind"):
        ledger.write_event(
            source="sprint-add",
            task="slc-01",
            kind="claim",
        )


def test_read_events_filters(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.write_event(
        source="sprint-add",
        task="slc-01",
        kind="cut",
        ref="abc",
        ref_kind="plan-hash",
    )
    ledger.write_event(
        source="aet-state",
        task="slc-01",
        kind="land",
        occurred_at="2026-01-01T00:00:00Z",
    )
    ledger.write_event(
        source="sprint-add",
        task="slc-02",
        kind="cut",
        ref="def",
        ref_kind="plan-hash",
    )

    assert len(ledger.read_events()) == 3
    assert len(ledger.read_events(task="slc-01")) == 2
    assert len(ledger.read_events(kind="land")) == 1
    assert len(ledger.read_events(source="sprint-add")) == 2
    assert len(ledger.read_events(task="slc-02", kind="cut")) == 1


# --- Integrity: corruption is loud, and a failed load never narrows the file ---


def _one_event(ledger: Ledger) -> dict:
    return ledger.write_event(
        source="sprint-add",
        task="slc-01",
        kind="cut",
        ref="abc123",
        ref_kind="plan-hash",
    )


def test_edited_body_is_rejected_not_silently_reindexed(tmp_path: Path) -> None:
    """A hand-edited body no longer matches its id, and the load says so.

    The failure mode is *not* "the event goes missing": the loader indexes on
    the stored id, so an edited event used to be trusted verbatim while the
    next writer computed the true id, found nothing, and appended a duplicate.
    """
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    _one_event(ledger)

    event = json.loads(path.read_text().strip())
    event["task"] = "slc-99"
    path.write_text(json.dumps(event) + "\n")

    with pytest.raises(LedgerCorruptionError) as excinfo:
        Ledger(path)
    assert "does not match event body" in str(excinfo.value)


def test_malformed_line_is_rejected_not_dropped(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    _one_event(ledger)
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"id": "truncated"\n')

    with pytest.raises(LedgerCorruptionError) as excinfo:
        Ledger(path)
    assert "not valid JSON" in str(excinfo.value)


def test_corrupt_line_survives_a_refused_write(tmp_path: Path) -> None:
    """A refused load must not be followed by a write that erases history.

    The old loader skipped unparseable lines and the old writer rewrote the
    whole file from that reduced index, so one bad line deleted itself — and
    any event the loader had also skipped — on the next append.
    """
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    _one_event(ledger)
    with open(path, "a", encoding="utf-8") as f:
        f.write("{ not json at all\n")
    before = path.read_bytes()

    with pytest.raises(LedgerCorruptionError):
        Ledger(path).write_event(
            source="aet-state",
            task="slc-02",
            kind="land",
            occurred_at="2026-01-01T00:00:00Z",
        )

    assert path.read_bytes() == before


def test_write_appends_without_rewriting_prior_lines(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    _one_event(ledger)
    first = path.read_bytes()

    ledger.write_event(
        source="aet-state",
        task="slc-01",
        kind="land",
        occurred_at="2026-01-01T00:00:00Z",
    )

    assert path.read_bytes().startswith(first)


def test_missing_trailing_newline_does_not_fuse_events(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    _one_event(ledger)
    path.write_bytes(path.read_bytes().rstrip(b"\n"))

    ledger = Ledger(path)
    ledger.write_event(
        source="aet-state",
        task="slc-01",
        kind="land",
        occurred_at="2026-01-01T00:00:00Z",
    )

    assert len(path.read_text().strip().splitlines()) == 2
    assert len(Ledger(path).read_events()) == 2


def test_non_string_id_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    event = _one_event(ledger)
    event["id"] = 17
    path.write_text(json.dumps(event) + "\n")

    with pytest.raises(LedgerCorruptionError) as excinfo:
        Ledger(path)
    assert "non-string 'id'" in str(excinfo.value)


def test_identical_duplicate_line_is_tolerated(tmp_path: Path) -> None:
    """Byte-identical repeats carry no information loss, so they are not errors."""
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    _one_event(ledger)
    line = path.read_text().strip()
    path.write_text(line + "\n" + line + "\n")

    assert len(Ledger(path).read_events()) == 1


def test_conflicting_duplicate_id_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    event = _one_event(ledger)
    conflicting = {**event, "payload": {"tampered": True}}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(conflicting) + "\n")

    with pytest.raises(LedgerCorruptionError) as excinfo:
        Ledger(path)
    assert "duplicate id" in str(excinfo.value)


def test_payload_edits_are_outside_the_content_address(tmp_path: Path) -> None:
    """The id covers the identity tuple only — payload integrity is not claimed.

    Widening the address to the payload would change every existing id and
    break the idempotence that makes duplicate writes no-ops (ADR-055). This
    test pins the boundary so the guarantee is not overclaimed elsewhere.
    """
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    event = _one_event(ledger)
    event["payload"] = {"edited": True}
    path.write_text(json.dumps(event) + "\n")

    assert Ledger(path).read_events()[0]["payload"] == {"edited": True}


def test_unreadable_ledger_propagates_instead_of_reading_as_empty(tmp_path: Path) -> None:
    """An I/O failure must never present as an empty ledger.

    The old loader swallowed OSError and returned no events, so the next write
    replaced live history with a single-event file.
    """
    if os.geteuid() == 0:
        pytest.skip("root bypasses the permission bit this test relies on")
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    _one_event(ledger)
    before = path.read_bytes()
    path.chmod(0o000)
    try:
        with pytest.raises(OSError):
            Ledger(path)
    finally:
        path.chmod(0o600)
    assert path.read_bytes() == before


def test_verify_reports_every_problem_without_raising(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    _one_event(ledger)
    with open(path, "a", encoding="utf-8") as f:
        f.write("{ not json\n")
        f.write('{"id": "deadbeef", "source": "s", "task": "t", "kind": "cut"}\n')

    problems = verify(path)
    assert len(problems) == 2
    assert any("not valid JSON" in p for p in problems)
    assert any("does not match event body" in p for p in problems)


def test_verify_is_empty_for_a_clean_ledger(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    _one_event(Ledger(path))
    assert verify(path) == []


def test_verify_is_empty_for_a_missing_ledger(tmp_path: Path) -> None:
    assert verify(tmp_path / "absent.jsonl") == []


# --- Path resolution: one canonical ledger location per repo ---


@pytest.mark.real_ledger_resolution
def test_resolve_ledger_path_defaults_to_repo_root(monkeypatch, tmp_path: Path) -> None:
    """With no env overrides, the ledger resolves to repo-root/.agents/ledger.jsonl."""
    monkeypatch.delenv("AET_LEDGER_PATH", raising=False)
    monkeypatch.delenv("AET_REPO_ROOT", raising=False)

    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    repo_root = Path(result.stdout.strip())

    assert resolve_ledger_path() == repo_root / ".agents" / "ledger.jsonl"


@pytest.mark.real_ledger_resolution
def test_resolve_ledger_path_ignores_aet_repo_root(monkeypatch, tmp_path: Path) -> None:
    """AET_REPO_ROOT must not redirect the ledger to another checkout."""
    monkeypatch.delenv("AET_LEDGER_PATH", raising=False)
    monkeypatch.setenv("AET_REPO_ROOT", str(tmp_path))

    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    repo_root = Path(result.stdout.strip())

    assert resolve_ledger_path() == repo_root / ".agents" / "ledger.jsonl"


@pytest.mark.real_ledger_resolution
def test_resolve_ledger_path_respects_aet_ledger_path(monkeypatch, tmp_path: Path) -> None:
    """AET_LEDGER_PATH wins over repo-root derivation."""
    custom = tmp_path / "custom-ledger.jsonl"
    monkeypatch.setenv("AET_LEDGER_PATH", str(custom))

    assert resolve_ledger_path() == custom


def _stub_rev_parse(monkeypatch, stdout: str) -> None:
    """Make every subprocess.run in aet.ledger answer rev-parse with ``stdout``."""

    class _Result:
        returncode = 0

        def __init__(self, out: str) -> None:
            self.stdout = out
            self.stderr = ""

    monkeypatch.setattr(ledger_module.subprocess, "run", lambda *a, **k: _Result(stdout))


@pytest.mark.real_ledger_resolution
def test_resolve_ledger_path_rejects_nonexistent_root(monkeypatch, tmp_path: Path) -> None:
    """A rev-parse answer that is not a real directory fails loudly, not silently.

    Regression: a stubbed git returned a commit sha here, and the writer created
    ``<sha>/.agents/ledger.jsonl`` under the cwd as a side effect.
    """
    monkeypatch.delenv("AET_LEDGER_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _stub_rev_parse(monkeypatch, "abc123def456\n")

    with pytest.raises(LedgerRootError, match="not an existing directory"):
        resolve_ledger_path()

    assert not (tmp_path / "abc123def456").exists()


@pytest.mark.real_ledger_resolution
def test_resolve_ledger_path_rejects_empty_root(monkeypatch, tmp_path: Path) -> None:
    """Empty rev-parse output must not silently resolve to the cwd."""
    monkeypatch.delenv("AET_LEDGER_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _stub_rev_parse(monkeypatch, "\n")

    with pytest.raises(LedgerRootError, match="printed nothing"):
        resolve_ledger_path()


@pytest.mark.real_ledger_resolution
def test_resolve_ledger_path_falls_back_to_cwd_without_git(monkeypatch, tmp_path: Path) -> None:
    """A missing git binary still falls back to the cwd; only bad output raises."""
    monkeypatch.delenv("AET_LEDGER_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    def _no_git(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(ledger_module.subprocess, "run", _no_git)

    expected = Path(tmp_path).resolve() / ".agents" / "ledger.jsonl"
    assert resolve_ledger_path() == expected
