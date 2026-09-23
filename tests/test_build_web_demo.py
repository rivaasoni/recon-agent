"""Tests for the static web demo data build.

The pure functions are unit-tested. The full build needs the analytics schema
(built by dbt), so that test runs against the real warehouse when it exists
and skips otherwise — the same pattern as the fixture-drift test.
"""

import json
from datetime import date
from decimal import Decimal

import duckdb
import pytest

from recon.config import settings as real_settings
from recon.pipeline.build_web_demo import MAX_RESULT_CHARS, build_trace, json_safe


# ---------------------------------------------------------------------------
# json_safe: database values -> plain JSON
# ---------------------------------------------------------------------------
def test_dates_become_iso_strings():
    assert json_safe(date(2026, 8, 12)) == "2026-08-12"


def test_decimals_become_numbers():
    assert json_safe(Decimal("-208.68")) == -208.68


def test_plain_values_pass_through():
    assert json_safe("BILL-5059") == "BILL-5059"
    assert json_safe(None) is None
    assert json_safe(True) is True


# ---------------------------------------------------------------------------
# build_trace: trimmed for the web, but still readable
# ---------------------------------------------------------------------------
def make_trace(result_text):
    return {
        "case_id": "CASE-001", "status": "completed", "latency_seconds": 30.0,
        "totals": {"cost_usd": 0.1, "tool_calls": 2}, "final_summary": "Done.",
        "steps": [{
            "step": 1, "stop_reason": "tool_use", "model_seconds": 2.0, "cost_usd": 0.05,
            "thinking": ["Checking the case."], "text": [], "usage": {"input_tokens": 10},
            "tool_calls": [{"id": "t1", "name": "get_exception_case", "input": {"case_id": "CASE-001"}}],
            "tool_results": [{"tool_use_id": "t1", "is_error": False, "text": result_text}],
        }],
    }


def test_trace_keeps_the_reasoning():
    trace = build_trace(make_trace("short result"))

    assert trace["steps"][0]["thinking"] == ["Checking the case."]
    assert trace["steps"][0]["tool_calls"][0]["name"] == "get_exception_case"
    assert trace["final_summary"] == "Done."


def test_long_tool_results_are_truncated_and_flagged():
    """Traces can be large; the demo should stay small AND say when it cut."""
    trace = build_trace(make_trace("x" * (MAX_RESULT_CHARS + 500)))

    result = trace["steps"][0]["tool_results"][0]
    assert len(result["text"]) == MAX_RESULT_CHARS
    assert result["truncated"] is True


def test_short_results_are_not_flagged():
    result = build_trace(make_trace("short"))["steps"][0]["tool_results"][0]
    assert result["truncated"] is False


def test_trace_drops_internals_the_demo_does_not_need():
    trace = build_trace(make_trace("short"))
    assert "usage" not in trace["steps"][0]          # per-step token detail
    assert "tool_use_id" not in trace["steps"][0]["tool_results"][0]


# ---------------------------------------------------------------------------
# The real build (skipped without a built warehouse)
# ---------------------------------------------------------------------------
def analytics_exists() -> bool:
    if not real_settings.duckdb_path.exists():
        return False
    with duckdb.connect(str(real_settings.duckdb_path), read_only=True) as con:
        tables = con.execute(
            "select table_name from information_schema.tables where table_schema = 'analytics'"
        ).fetchall()
    return ("fct_exception_cases",) in tables


@pytest.mark.skipif(not analytics_exists(),
                    reason="No analytics schema — run: python -m recon.pipeline.refresh_analytics")
def test_committed_demo_data_is_valid_json_and_complete():
    """The published files must parse and hold what the site expects."""
    web_data = real_settings.project_root / "web" / "data"
    if not web_data.exists():
        pytest.skip("web/data not built yet — run: python -m recon.pipeline.build_web_demo")

    summary = json.loads((web_data / "summary.json").read_text())
    cases = json.loads((web_data / "cases.json").read_text())

    assert summary["eval"]["cases"] == len(cases)
    assert summary["reconciliation"]["bank_lines"] > 0
    assert {"types", "predicted", "rows"} <= set(summary["eval"]["confusion"])

    for case in cases:
        assert case["case_id"].startswith("CASE-")
        assert (web_data / "traces" / f"{case['case_id']}.json").exists()


@pytest.mark.skipif(not analytics_exists(), reason="No analytics schema")
def test_demo_data_contains_no_secrets():
    """It's published on the public internet — check before it ships."""
    web_data = real_settings.project_root / "web" / "data"
    if not web_data.exists():
        pytest.skip("web/data not built yet")

    for path in web_data.rglob("*.json"):
        text = path.read_text()
        assert "sk-ant" not in text, f"API key in {path}"
        assert "ANTHROPIC_API_KEY" not in text, f"key name in {path}"
