"""Tests for the per-PRD performance rollup behind ``aet performance-report``."""

from __future__ import annotations

import json

import pytest

from aet import perf_report


def write_stage(archive, project, worktree, plan, **fields):
    """Append one stage record to a plan's JSONL in the archive layout."""
    run_dir = archive / project / worktree / "2026-09-01" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "stage",
        "run_id": "run-1",
        "task_id": plan,
        "stage": "implemented",
        "result": "success",
        "start_time": "2026-09-01T10:00:00Z",
        "end_time": "2026-09-01T10:10:00Z",
        "duration_seconds": 600.0,
        "token_count": 1000,
        "cost_estimate": 1.0,
        "attempt": 1,
    }
    record.update(fields)
    with (run_dir / f"{plan}.jsonl").open("a") as fh:
        fh.write(json.dumps(record) + "\n")


@pytest.fixture
def archive(tmp_path):
    return tmp_path / "telemetry"


@pytest.fixture
def prds(tmp_path):
    d = tmp_path / "prds"
    d.mkdir()
    return d


def test_project_dir_name_drops_the_worktree_label():
    """A report covers every worktree, so it reads the repository segment."""
    assert perf_report.project_dir_name("ae-toolkit/main") == "ae-toolkit"
    assert perf_report.project_dir_name("ae-toolkit/feature-x") == "ae-toolkit"
    assert perf_report.project_dir_name("plain-dir") == "plain-dir"


def test_reads_stages_across_worktrees(archive, prds):
    """Both worktrees of a project contribute unless one is named."""
    write_stage(archive, "proj", "main", "abc-01-one")
    write_stage(archive, "proj", "feature-x", "abc-02-two")

    every = perf_report.read_stages(archive, "proj")
    assert {s.worktree for s in every} == {"main", "feature-x"}

    narrowed = perf_report.read_stages(archive, "proj", worktree="main")
    assert [s.task_id for s in narrowed] == ["abc-01-one"]


def test_since_excludes_earlier_stages(archive):
    """The window filter compares ISO-8601 start times."""
    write_stage(archive, "proj", "main", "abc-01-one", start_time="2026-08-01T00:00:00Z")
    write_stage(archive, "proj", "main", "abc-02-two", start_time="2026-09-05T00:00:00Z")

    kept = perf_report.read_stages(archive, "proj", since="2026-09-01T00:00:00Z")
    assert [s.task_id for s in kept] == ["abc-02-two"]


def test_work_history_and_malformed_lines_are_skipped(archive):
    """A non-record file and a broken line never reach the rollup."""
    write_stage(archive, "proj", "main", "abc-01-one")
    run_dir = archive / "proj" / "main" / "2026-09-01" / "run-1"
    (run_dir / "work-history.jsonl").write_text(
        json.dumps({"type": "stage", "task_id": "zzz-99-ignored"}) + "\n"
    )
    with (run_dir / "abc-01-one.jsonl").open("a") as fh:
        fh.write("{not json\n")

    stages = perf_report.read_stages(archive, "proj")
    assert [s.task_id for s in stages] == ["abc-01-one"]


def test_missing_project_and_empty_window_both_raise(archive):
    """Nothing to report is an error the CLI turns into a non-zero exit."""
    with pytest.raises(perf_report.NoTelemetryError):
        perf_report.read_stages(archive, "absent")

    write_stage(archive, "proj", "main", "abc-01-one")
    with pytest.raises(perf_report.NoTelemetryError):
        perf_report.read_stages(archive, "proj", since="2099-01-01T00:00:00Z")


def test_prefix_belongs_to_the_prd_citing_the_most_slices(prds):
    """A PRD that merely depends on a prefix does not win it."""
    (prds / "owner.md").write_text("abc-01 abc-02 abc-03 build this")
    (prds / "dependent.md").write_text("depends on abc-01 only")

    owner, evidence = perf_report.derive_ownership(prds)
    assert owner["abc"] == "owner.md"
    assert evidence["abc"] == {"owner.md": 3, "dependent.md": 1}


def test_ownership_tie_breaks_on_the_prd_name(prds):
    """A tie resolves the same way on every run, so the report is stable."""
    (prds / "b-second.md").write_text("abc-01")
    (prds / "a-first.md").write_text("abc-02")

    owner, _ = perf_report.derive_ownership(prds)
    assert owner["abc"] == "b-second.md"


def test_missing_prd_dir_yields_no_ownership(tmp_path):
    """An absent directory is a valid state, not a crash."""
    assert perf_report.derive_ownership(tmp_path / "absent") == ({}, {})


def test_payload_groups_by_prd_and_flags_the_unattributed(archive, prds):
    """A plan whose prefix no PRD cites lands in the unattributed group."""
    (prds / "owner.md").write_text("abc-01 abc-02")
    write_stage(archive, "proj", "main", "abc-01-one")
    write_stage(archive, "proj", "main", "zzz-01-orphan")

    stages = perf_report.read_stages(archive, "proj")
    payload = perf_report.build_payload(stages, "proj", archive, prds)

    assert payload["attribution"]["group_by"] == perf_report.GROUP_BY_PRD
    groups = {g["group"] for g in payload["groups"]}
    assert groups == {"owner.md", perf_report.UNATTRIBUTED}
    assert payload["attribution"]["unattributed_prefixes"] == ["zzz"]


def test_attribution_table_covers_only_observed_prefixes(archive, prds):
    """The PRD corpus names prefixes this project never ran; those stay out."""
    (prds / "owner.md").write_text("abc-01 unrelated-01 alsomissing-02")
    write_stage(archive, "proj", "main", "abc-01-one")

    stages = perf_report.read_stages(archive, "proj")
    payload = perf_report.build_payload(stages, "proj", archive, prds)

    assert [e["prefix"] for e in payload["attribution"]["prefixes"]] == ["abc"]


def test_payload_falls_back_to_prefix_grouping(archive, prds):
    """With no PRD citing anything, plans group by their slice prefix."""
    write_stage(archive, "proj", "main", "abc-01-one")
    write_stage(archive, "proj", "main", "xyz-01-two")

    stages = perf_report.read_stages(archive, "proj")
    payload = perf_report.build_payload(stages, "proj", archive, prds)

    assert payload["attribution"]["group_by"] == perf_report.GROUP_BY_PREFIX
    assert {g["group"] for g in payload["groups"]} == {"abc-", "xyz-"}


def test_absent_cost_is_counted_as_a_gap_not_a_zero(archive, prds):
    """An unmeasured stage moves the coverage counter, never the total."""
    write_stage(archive, "proj", "main", "abc-01-one", cost_estimate=2.0)
    write_stage(archive, "proj", "main", "abc-01-one", cost_estimate=None)
    write_stage(archive, "proj", "main", "abc-01-one", cost_estimate=0.0)

    stages = perf_report.read_stages(archive, "proj")
    totals = perf_report.build_payload(stages, "proj", archive, prds)["totals"]

    assert totals["cost_usd"] == 2.0
    assert totals["stages"] == 3
    # The measured zero is measured; only the null is a gap.
    assert totals["stages_without_cost"] == 1


def test_failure_classes_and_worst_plan_are_derived(archive, prds):
    """The data-quality section reads the data, never a hand-written note."""
    write_stage(archive, "proj", "main", "abc-01-one", result="failure",
                failure_class="timeout", cost_estimate=None)
    write_stage(archive, "proj", "main", "abc-01-one", result="failure",
                failure_class="timeout", cost_estimate=None)
    write_stage(archive, "proj", "main", "abc-02-two", result="success")

    stages = perf_report.read_stages(archive, "proj")
    payload = perf_report.build_payload(stages, "proj", archive, prds)

    assert payload["failure_classes"] == [
        {"failure_class": "timeout", "stages": 2, "costless_stages": 2}
    ]
    assert payload["worst_failing_plan"] == {"plan": "abc-01-one", "failed_stages": 2}
    assert payload["totals"]["failed_stages"] == 2


def test_cost_share_sums_to_the_whole(archive, prds):
    """Every group's share is measured against the same total."""
    (prds / "a.md").write_text("abc-01")
    (prds / "b.md").write_text("xyz-01")
    write_stage(archive, "proj", "main", "abc-01-one", cost_estimate=3.0)
    write_stage(archive, "proj", "main", "xyz-01-two", cost_estimate=1.0)

    stages = perf_report.read_stages(archive, "proj")
    payload = perf_report.build_payload(stages, "proj", archive, prds)

    shares = {g["group"]: g["cost_share_pct"] for g in payload["groups"]}
    assert shares == {"a.md": 75.0, "b.md": 25.0}


def test_zero_total_cost_does_not_divide_by_zero(archive, prds):
    """A project with no cost data still renders."""
    write_stage(archive, "proj", "main", "abc-01-one", cost_estimate=None)

    stages = perf_report.read_stages(archive, "proj")
    payload = perf_report.build_payload(stages, "proj", archive, prds)

    assert payload["totals"]["cost_share_pct"] == 0.0
    assert perf_report.render_markdown(payload)


def test_markdown_renders_from_the_payload(archive, prds):
    """The two output forms come from one data set, so they cannot disagree."""
    (prds / "owner.md").write_text("abc-01")
    write_stage(archive, "proj", "main", "abc-01-one", cost_estimate=12.5)

    stages = perf_report.read_stages(archive, "proj")
    payload = perf_report.build_payload(stages, "proj", archive, prds)
    markdown = perf_report.render_markdown(payload)

    assert "# AET performance report — proj" in markdown
    assert "## Per PRD" in markdown
    assert "owner.md" in markdown
    assert "$12.50" in markdown


def test_prefix_grouping_omits_the_prd_attribution_table(archive, prds):
    """With no PRDs there is no ownership evidence to show."""
    write_stage(archive, "proj", "main", "abc-01-one")

    stages = perf_report.read_stages(archive, "proj")
    markdown = perf_report.render_markdown(
        perf_report.build_payload(stages, "proj", archive, prds)
    )

    assert "## Per slice prefix" in markdown
    assert "Owning PRD" not in markdown


def test_hours_formats_minutes_with_a_leading_zero():
    assert perf_report.hours(0) == "0h 00m"
    assert perf_report.hours(540) == "0h 09m"
    assert perf_report.hours(3660) == "1h 01m"
