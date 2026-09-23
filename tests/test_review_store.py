"""Tests for the Phase 7 review store (no Streamlit involved).

Keeping this logic out of the UI is what makes it testable: every rule about
merging cases, proposals, traces and decisions is checked here.
"""

import json

import pytest

from recon.review.store import (
    APPROVED,
    REJECTED,
    approved_entries,
    decision_history,
    entries_csv,
    record_decision,
    review_items,
    review_metrics,
    status_counts,
)


# ---------------------------------------------------------------------------
# Helpers: put a proposal / trace into the throwaway data folder
# ---------------------------------------------------------------------------
def add_proposal(settings, case_id, proposal_id, classification="fx_difference", lines=None):
    proposal = {
        "proposal_id": proposal_id,
        "created_at": "2026-09-21T21:00:00+00:00",
        "status": "pending_human_approval",
        "case_id": case_id,
        "classification": classification,
        "explanation": f"Scripted proposal for {case_id}.",
        "lines": lines if lines is not None else [
            {"account": "7100 FX Gain/Loss", "debit": "208.68", "credit": "0.00", "memo": ""},
            {"account": "1000 Cash - Operating", "debit": "0.00", "credit": "208.68", "memo": ""},
        ],
        "total": "208.68",
        "evidence": ["BNK-0055", "DOC-002"],
    }
    settings.proposals_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings.proposals_path, "a") as f:
        f.write(json.dumps(proposal) + "\n")
    return proposal


def add_trace(settings, case_id, run_id="run-1", status="completed"):
    folder = settings.traces_dir / run_id
    folder.mkdir(parents=True, exist_ok=True)
    trace = {"case_id": case_id, "run_id": run_id, "status": status, "steps": [],
             "proposals": [], "totals": {}, "final_summary": f"Summary for {case_id}"}
    (folder / f"{case_id}.json").write_text(json.dumps(trace))
    return trace


# ---------------------------------------------------------------------------
# review_items
# ---------------------------------------------------------------------------
def test_every_case_appears_even_without_a_proposal(tiny_warehouse):
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")

    items = review_items()

    assert [item["case_id"] for item in items] == ["CASE-001", "CASE-002", "CASE-003"]
    assert items[0]["status"] == "pending"
    # The agent produced nothing for these two — a reviewer must still see them.
    assert items[1]["status"] == "no_proposal"
    assert items[2]["status"] == "no_proposal"


def test_item_carries_the_case_facts_and_the_trace(tiny_warehouse):
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")
    add_trace(tiny_warehouse, "CASE-001")

    item = review_items()[0]

    assert item["case"]["reference"] == "BILL-5059"          # from DuckDB
    assert item["proposal"]["classification"] == "fx_difference"
    assert item["trace"]["final_summary"] == "Summary for CASE-001"


def test_the_newest_run_with_a_trace_is_used(tiny_warehouse):
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")
    add_trace(tiny_warehouse, "CASE-001", run_id="run-1")
    add_trace(tiny_warehouse, "CASE-001", run_id="run-2", status="error")

    assert review_items()[0]["trace"]["run_id"] == "run-2"
    # ...unless a specific run is asked for:
    assert review_items(run_id="run-1")[0]["trace"]["run_id"] == "run-1"


def test_the_latest_proposal_for_a_case_wins(tiny_warehouse):
    """If the agent is re-run, the newer proposal is the one to review."""
    add_proposal(tiny_warehouse, "CASE-001", "PROP-OLD", classification="duplicate")
    add_proposal(tiny_warehouse, "CASE-001", "PROP-NEW", classification="fx_difference")

    item = review_items()[0]
    assert item["proposal"]["proposal_id"] == "PROP-NEW"


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------
def test_approving_updates_the_status(tiny_warehouse):
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")

    record_decision("PROP-A", "CASE-001", APPROVED, reviewer="Rivaa", note="Rate confirmed.")

    item = review_items()[0]
    assert item["status"] == APPROVED
    assert item["decision"]["reviewer"] == "Rivaa"
    assert item["decision"]["note"] == "Rate confirmed."


def test_changing_your_mind_appends_and_the_latest_wins(tiny_warehouse):
    """Append-only: the original decision is still on file."""
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")

    record_decision("PROP-A", "CASE-001", APPROVED, reviewer="Rivaa")
    record_decision("PROP-A", "CASE-001", REJECTED, reviewer="Rivaa", note="Wrong account.")

    assert review_items()[0]["status"] == REJECTED
    history = decision_history("PROP-A")
    assert [d["decision"] for d in history] == [APPROVED, REJECTED]     # both kept


def test_decisions_record_who_and_when(tiny_warehouse):
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")
    record = record_decision("PROP-A", "CASE-001", APPROVED, reviewer="  Rivaa  ")

    assert record["decision_id"].startswith("DEC-")
    assert record["reviewer"] == "Rivaa"              # trimmed
    assert record["decided_at"].startswith("20")      # ISO timestamp
    assert record["proposal_id"] == "PROP-A"


@pytest.mark.parametrize("bad_decision", ["maybe", "APPROVED", ""])
def test_only_approve_or_reject_are_allowed(tiny_warehouse, bad_decision):
    with pytest.raises(ValueError, match="decision must be one of"):
        record_decision("PROP-A", "CASE-001", bad_decision, reviewer="Rivaa")


def test_a_reviewer_name_is_required(tiny_warehouse):
    """An audit log that doesn't say who decided is not an audit log."""
    with pytest.raises(ValueError, match="reviewer is required"):
        record_decision("PROP-A", "CASE-001", APPROVED, reviewer="   ")


def test_a_rejected_decision_never_changes_the_warehouse(tiny_warehouse):
    """Reviewing is read-only for the warehouse — approving posts nothing."""
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")
    before = tiny_warehouse.duckdb_path.read_bytes()

    record_decision("PROP-A", "CASE-001", APPROVED, reviewer="Rivaa")

    assert tiny_warehouse.duckdb_path.read_bytes() == before


# ---------------------------------------------------------------------------
# Counts for the UI header
# ---------------------------------------------------------------------------
def test_status_counts(tiny_warehouse):
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")
    add_proposal(tiny_warehouse, "CASE-002", "PROP-B")
    record_decision("PROP-A", "CASE-001", APPROVED, reviewer="Rivaa")

    counts = status_counts(review_items())
    assert counts == {"pending": 1, APPROVED: 1, REJECTED: 0, "no_proposal": 1}


# ---------------------------------------------------------------------------
# Export and metrics
# ---------------------------------------------------------------------------
def test_export_contains_only_approved_entries_with_approver_details(tiny_warehouse):
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")
    add_proposal(tiny_warehouse, "CASE-002", "PROP-B")
    record_decision("PROP-A", "CASE-001", APPROVED, reviewer="Rivaa")
    record_decision("PROP-B", "CASE-002", REJECTED, reviewer="Rivaa", note="Wrong account.")

    rows = approved_entries()

    assert {row["case_id"] for row in rows} == {"CASE-001"}      # rejected excluded
    assert len(rows) == 2                                        # both lines of the entry
    assert rows[0]["approved_by"] == "Rivaa"
    assert rows[0]["account"] == "7100 FX Gain/Loss"


def test_an_approved_no_entry_proposal_exports_no_lines(tiny_warehouse):
    """A timing difference needs no posting — there is nothing to export,
    but it still counts as reviewed."""
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A",
                 classification="timing_difference", lines=[])
    record_decision("PROP-A", "CASE-001", APPROVED, reviewer="Rivaa")

    items = review_items()
    assert approved_entries(items) == []
    assert review_metrics(items)["no_entry_approved"] == 1


def test_csv_has_a_header_and_one_row_per_line(tiny_warehouse):
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")
    record_decision("PROP-A", "CASE-001", APPROVED, reviewer="Rivaa")

    text = entries_csv(approved_entries())
    lines = text.strip().splitlines()

    assert lines[0].startswith("case_id,proposal_id,classification,account,debit,credit")
    assert len(lines) == 3                       # header + 2 journal lines
    assert "7100 FX Gain/Loss" in lines[1]


def test_metrics_summarise_workload_value_and_agent_cost(tiny_warehouse):
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")
    add_proposal(tiny_warehouse, "CASE-002", "PROP-B")
    record_decision("PROP-A", "CASE-001", APPROVED, reviewer="Rivaa")
    trace = add_trace(tiny_warehouse, "CASE-001")
    trace["totals"] = {"cost_usd": 0.12}
    trace["latency_seconds"] = 30.0
    (tiny_warehouse.traces_dir / "run-1" / "CASE-001.json").write_text(json.dumps(trace))

    metrics = review_metrics(review_items())

    assert metrics["counts"]["pending"] == 1
    assert metrics["approved_value"] == 208.68
    assert metrics["pending_value"] == 208.68
    assert metrics["agent_cost_usd"] == 0.12
    assert metrics["agent_seconds"] == 30.0


# ---------------------------------------------------------------------------
# Fixture drift
# ---------------------------------------------------------------------------
def test_tiny_warehouse_columns_match_the_real_models(tiny_warehouse):
    """The hand-built test warehouse must have the SAME columns as the real
    dbt models. When they drift apart, tests pass against a schema that no
    longer exists (this is exactly how the UI tests broke: the fixture had no
    bank_date column, but the app reads one)."""
    import duckdb

    from recon.config import settings as real_settings

    if not real_settings.duckdb_path.exists():
        pytest.skip("No real warehouse — run: python -m recon.pipeline.run")

    def columns(db_path, table):
        with duckdb.connect(str(db_path), read_only=True) as con:
            return [c[0] for c in con.execute(f"select * from {table} limit 0").description]

    for table in ("matching.exceptions", "cleaned.bank_transactions",
                  "cleaned.gl_entries", "cleaned.documents"):
        missing = set(columns(real_settings.duckdb_path, table)) - set(columns(tiny_warehouse.duckdb_path, table))
        assert not missing, f"tests/conftest.py {table} is missing columns: {sorted(missing)}"
