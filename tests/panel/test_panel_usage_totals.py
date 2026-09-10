"""Tests for the panel's cost and token totals.

The aggregate logic lives in ``src/aet/panel/index.html``. These tests extract
the marked helper block verbatim and execute it under node, so the assertions
run against the code the browser runs rather than a Python restatement of it.
Node is already a build dependency of this repo (``make lint`` / ``make
format``), so its absence is a failure, not a skip.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

if not shutil.which("node"):
    pytest.skip("node is required to evaluate index.html JS helpers", allow_module_level=True)

PANEL_HTML = Path(__file__).parents[2] / "src" / "aet" / "panel" / "index.html"
MARK_START = "// USAGE-HELPERS-START"
MARK_END = "// USAGE-HELPERS-END"

MEASURED = {"cost_estimate": 1.5, "token_count": 2000}
UNMEASURED = {"cost_estimate": None, "token_count": None}


def _helpers_source() -> str:
    """Return the usage helper block from index.html."""
    text = PANEL_HTML.read_text(encoding="utf-8")
    return text[text.index(MARK_START) : text.index(MARK_END)]


def _evaluate(expression: str, records: list[dict]) -> object:
    """Evaluate ``expression`` against ``records`` (bound as ``recs``) in node."""
    script = (
        _helpers_source()
        + f"\nconst recs = {json.dumps(records)};\n"
        + f"console.log(JSON.stringify({expression}));\n"
    )
    proc = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        pytest.fail(f"node evaluation failed: {proc.stderr}")
    return json.loads(proc.stdout)


def test_total_sums_the_measured_records():
    """Every record carrying a number contributes, and coverage is complete."""
    assert _evaluate('sumUsage(recs, "cost_estimate")', [MEASURED, MEASURED]) == {
        "total": 3.0,
        "counted": 2,
        "missing": 0,
    }


def test_unmeasured_records_are_reported_not_counted_as_zero():
    """A null figure moves the coverage count, never the total."""
    assert _evaluate(
        'sumUsage(recs, "token_count")', [MEASURED, UNMEASURED, MEASURED]
    ) == {"total": 4000, "counted": 2, "missing": 1}


def test_nothing_measured_is_null_not_zero():
    """No measurement means no figure, so the card renders a dash (ADR-031)."""
    assert _evaluate('sumUsage(recs, "cost_estimate")', [UNMEASURED, UNMEASURED]) == {
        "total": None,
        "counted": 0,
        "missing": 2,
    }


def test_empty_input_is_null():
    """An empty filter result states no figure rather than a zero total."""
    assert _evaluate('sumUsage(recs, "cost_estimate")', []) == {
        "total": None,
        "counted": 0,
        "missing": 0,
    }


def test_missing_field_is_not_a_measurement():
    """A record without the field at all is unmeasured, like an explicit null."""
    assert _evaluate('sumUsage(recs, "cost_estimate")', [{"token_count": 5}]) == {
        "total": None,
        "counted": 0,
        "missing": 1,
    }


def test_non_numeric_values_are_rejected():
    """A string or a NaN is not a measurement and never enters the total."""
    records = [MEASURED, {"cost_estimate": "1.5"}, {"cost_estimate": True}]
    assert _evaluate('sumUsage(recs, "cost_estimate")', records) == {
        "total": 1.5,
        "counted": 1,
        "missing": 2,
    }
