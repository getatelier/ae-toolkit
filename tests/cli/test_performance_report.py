"""Tests for the ``aet performance-report`` command surface."""

from __future__ import annotations

import json
from pathlib import Path

from aet.cli.performance_report import app
from tests.cli._helpers import run_typer

STAGE = {
    "type": "stage",
    "run_id": "run-1",
    "task_id": "abc-01-one",
    "stage": "implemented",
    "result": "success",
    "start_time": "2026-09-01T10:00:00Z",
    "end_time": "2026-09-01T10:10:00Z",
    "duration_seconds": 600.0,
    "token_count": 1000,
    "cost_estimate": 4.25,
    "attempt": 1,
}


def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "telemetry"
    run_dir = archive / "proj" / "main" / "2026-09-01" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "abc-01-one.jsonl").write_text(json.dumps(STAGE) + "\n")
    return archive


def _prds(tmp_path: Path) -> Path:
    prds = tmp_path / "prds"
    prds.mkdir()
    (prds / "owner.md").write_text("abc-01 is in scope")
    return prds


def test_prints_markdown_to_stdout(tmp_path: Path, monkeypatch) -> None:
    """Run with no output path, the report goes to stdout."""
    monkeypatch.setenv("AET_TELEMETRY_ARCHIVE_DIR", str(_archive(tmp_path)))
    result = run_typer(app, ["--project", "proj", "--prds", str(_prds(tmp_path))])

    assert result.exit_code == 0
    assert "# AET performance report — proj" in result.stdout
    assert "owner.md" in result.stdout
    assert "$4.25" in result.stdout


def test_writes_both_output_files(tmp_path: Path, monkeypatch) -> None:
    """The markdown and the JSON come from one payload."""
    monkeypatch.setenv("AET_TELEMETRY_ARCHIVE_DIR", str(_archive(tmp_path)))
    out = tmp_path / "report.md"
    json_out = tmp_path / "report.json"

    result = run_typer(app, [
        "--project", "proj",
        "--prds", str(_prds(tmp_path)),
        "--out", str(out),
        "--json", str(json_out),
    ])

    assert result.exit_code == 0
    payload = json.loads(json_out.read_text())
    assert payload["totals"]["cost_usd"] == 4.25
    assert payload["meta"]["project"] == "proj"
    assert f"${payload['totals']['cost_usd']:,.2f}" in out.read_text()


def test_json_only_keeps_stdout_clean(tmp_path: Path, monkeypatch) -> None:
    """With --json alone the markdown is not printed, so piping stays usable."""
    monkeypatch.setenv("AET_TELEMETRY_ARCHIVE_DIR", str(_archive(tmp_path)))
    json_out = tmp_path / "report.json"

    result = run_typer(app, [
        "--project", "proj", "--prds", str(_prds(tmp_path)), "--json", str(json_out),
    ])

    assert result.exit_code == 0
    assert "# AET performance report" not in result.stdout


def test_absent_project_exits_non_zero(tmp_path: Path, monkeypatch) -> None:
    """Nothing to report is a failure the caller can detect."""
    monkeypatch.setenv("AET_TELEMETRY_ARCHIVE_DIR", str(_archive(tmp_path)))
    result = run_typer(app, ["--project", "absent"])

    assert result.exit_code == 1
    assert "no telemetry directory" in result.output


def test_worktree_narrows_the_scope(tmp_path: Path, monkeypatch) -> None:
    """One worktree label reports only that worktree's stages."""
    archive = _archive(tmp_path)
    other = archive / "proj" / "feature-x" / "2026-09-01" / "run-2"
    other.mkdir(parents=True)
    (other / "xyz-01-two.jsonl").write_text(
        json.dumps({**STAGE, "task_id": "xyz-01-two", "cost_estimate": 9.0}) + "\n"
    )
    monkeypatch.setenv("AET_TELEMETRY_ARCHIVE_DIR", str(archive))
    json_out = tmp_path / "report.json"

    run_typer(app, [
        "--project", "proj", "--worktree", "feature-x", "--json", str(json_out),
    ])

    payload = json.loads(json_out.read_text())
    assert payload["totals"]["cost_usd"] == 9.0
    assert payload["meta"]["worktrees_seen"] == ["feature-x"]
