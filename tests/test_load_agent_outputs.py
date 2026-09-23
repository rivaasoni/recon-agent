"""Tests for the Phase 9 loader that brings agent outputs into the warehouse."""

import json

import duckdb
import pytest

from recon.pipeline.load_agent_outputs import load_all
from recon.review.store import APPROVED, record_decision
from test_grade import FX_LINES, trace, write_run
from test_review_store import add_proposal


@pytest.fixture
def agent_outputs(tiny_warehouse):
    """Two proposals (one case proposed twice), one decision, two runs."""
    add_proposal(tiny_warehouse, "CASE-001", "PROP-OLD", classification="duplicate")
    add_proposal(tiny_warehouse, "CASE-001", "PROP-NEW", classification="fx_difference")
    record_decision("PROP-NEW", "CASE-001", APPROVED, reviewer="Rivaa", note="Rate checked.")

    write_run(tiny_warehouse, [trace("CASE-001", "duplicate")], run_id="run-1")
    write_run(tiny_warehouse, [trace("CASE-001", "fx_difference", lines=FX_LINES),
                               trace("CASE-002", "bank_fee")], run_id="run-2")
    return tiny_warehouse


def query(settings, sql):
    with duckdb.connect(str(settings.duckdb_path), read_only=True) as con:
        return con.execute(sql).fetchall()


def test_counts_match_the_files(agent_outputs):
    counts = load_all()
    assert counts == {"agent_proposals": 2, "agent_decisions": 1, "agent_case_runs": 3}


def test_proposal_grain_is_one_row_per_proposal(agent_outputs):
    """Re-running the agent ADDS a proposal; it doesn't replace one. The
    metrics layer has to pick the latest per case."""
    load_all()
    rows = query(agent_outputs, "select proposal_id, classification from raw.agent_proposals order by 1")
    assert rows == [("PROP-NEW", "fx_difference"), ("PROP-OLD", "duplicate")]


def test_case_run_grain_is_one_row_per_case_per_run(agent_outputs):
    load_all()
    rows = query(agent_outputs,
                 "select run_id, case_id from raw.agent_case_runs order by run_id, case_id")
    assert rows == [("run-1", "CASE-001"), ("run-2", "CASE-001"), ("run-2", "CASE-002")]


def test_run_stats_are_carried_through(agent_outputs):
    load_all()
    [(status, steps, tools, cost, classification)] = query(
        agent_outputs,
        """select status, steps, tool_calls, cost_usd, classification
           from raw.agent_case_runs where run_id = 'run-2' and case_id = 'CASE-001'""")
    assert (status, steps, tools, cost, classification) == \
        ("completed", 2, 4, 0.10, "fx_difference")


def test_journal_lines_stay_as_json_so_the_grain_is_unchanged(agent_outputs):
    load_all()
    [(count, lines_json)] = query(
        agent_outputs,
        "select line_count, lines_json from raw.agent_proposals where proposal_id = 'PROP-NEW'")
    assert count == 2
    assert json.loads(lines_json)[0]["account"] == "7100 FX Gain/Loss"


def test_loading_twice_does_not_duplicate_rows(agent_outputs):
    assert load_all() == load_all()


def test_tables_exist_even_before_the_agent_has_run(tiny_warehouse):
    """Downstream models must not break on a fresh project."""
    counts = load_all()
    assert counts == {"agent_proposals": 0, "agent_decisions": 0, "agent_case_runs": 0}
    assert query(tiny_warehouse, "select count(*) from raw.agent_proposals") == [(0,)]


def test_ground_truth_is_still_never_in_the_warehouse(agent_outputs):
    """data/eval/ (answer key, grading results) must stay out of DuckDB."""
    load_all()
    tables = [name for (name,) in query(
        agent_outputs, "select table_name from information_schema.tables")]
    assert not [t for t in tables if "answer" in t.lower() or "eval" in t.lower()], tables


def test_empty_tables_still_have_text_columns_not_guessed_numbers(tiny_warehouse):
    """An empty pandas column has no type and DuckDB guesses INTEGER, which
    broke `trim(decision_id)` in the dbt model until the first decision
    existed. Empty tables must still be usable."""
    load_all()
    types = query(tiny_warehouse, """
        select data_type from information_schema.columns
        where table_name = 'agent_decisions' and column_name = 'decision_id'
    """)
    assert types == [("VARCHAR",)]
    # And the query that used to fail now works on the empty table:
    assert query(tiny_warehouse, "select trim(decision_id) from raw.agent_decisions") == []
