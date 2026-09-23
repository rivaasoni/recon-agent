"""Tests for the Phase 8 grader — no API key, no agent run needed.

Everything is built by hand: a small answer key, a small set of traces, and
the tiny warehouse's three cases. That way we know the right score and can
check the grader reports exactly that.
"""

import json

import pandas as pd
import pytest

from recon.evals.grade import (
    accuracy,
    confusion_matrix,
    failure_cases,
    fully_correct,
    accuracy_by_type,
    grade_case,
    grade_run,
    ids_in,
    map_cases_to_exceptions,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def answer_key(*rows) -> pd.DataFrame:
    """rows: (exception_id, exception_type, bank_txn_ids, gl_entry_ids,
              expected_action, cash_adjustment, offset_account)
    The last three default to a correcting entry of -208.68 against FX."""
    filled = [row + ("book_fx_gain_loss", -208.68, "7100 FX Gain/Loss")[len(row) - 4:]
              for row in rows]
    return pd.DataFrame(filled, columns=["exception_id", "exception_type",
                                         "bank_txn_ids", "gl_entry_ids",
                                         "expected_action", "cash_adjustment",
                                         "offset_account"])


def trace(case_id, classification=None, status="completed", lines=None, **totals):
    proposals = []
    if classification:
        proposals = [{
            "proposal_id": "PROP-X",
            "case_id": case_id,
            "classification": classification,
            "explanation": f"Because of reasons ({classification}).",
            "lines": lines if lines is not None else [],
            "evidence": ["BNK-0055"],
        }]
    return {
        "case_id": case_id, "status": status, "proposals": proposals,
        "steps": [{}, {}], "latency_seconds": 30.0,
        "totals": {"tool_calls": 4, "cost_usd": 0.10, **totals},
    }


def write_run(settings, traces, run_id="run-1"):
    folder = settings.traces_dir / run_id
    folder.mkdir(parents=True, exist_ok=True)
    for one in traces:
        (folder / f"{one['case_id']}.json").write_text(json.dumps(one))
    (folder / "_summary.json").write_text(json.dumps({"run_id": run_id}))


def write_answer_key(settings, df):
    settings.eval_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(settings.eval_dir / "answer_key.csv", index=False)


# The tiny warehouse's cases: CASE-001 -> BNK-0055/GL-0063,
# CASE-002 -> BNK-0125, CASE-003 -> GL-0047.
TINY_KEY = answer_key(
    ("EXC-01", "fx_difference", "BNK-0055", "GL-0063", "book_fx_gain_loss", -208.68, "7100 FX Gain/Loss"),
    ("EXC-02", "bank_fee", "BNK-0125", "", "book_bank_fee", -45.00, "6100 Bank Fees"),
    ("EXC-03", "duplicate", "", "GL-0047", "reverse_duplicate", 11541.85, "2000 Accounts Payable"),
)

# The entry that correctly fixes EXC-01: cash goes down 208.68.
FX_LINES = [
    {"account": "7100 FX Gain/Loss", "debit": "208.68", "credit": "0.00", "memo": ""},
    {"account": "1000 Cash - Operating", "debit": "0.00", "credit": "208.68", "memo": ""},
]


# ---------------------------------------------------------------------------
# The join between answer key and cases
# ---------------------------------------------------------------------------
def test_ids_in_handles_lists_and_blanks():
    assert ids_in("BNK-0001, GL-0002") == {"BNK-0001", "GL-0002"}
    assert ids_in("") == set()


def test_cases_are_matched_to_exceptions_by_shared_row_ids(tiny_warehouse):
    """The answer key and the run share no IDs — only row IDs connect them."""
    from recon.evals.grade import load_case_rows

    mapping = map_cases_to_exceptions(load_case_rows(), TINY_KEY)

    assert {case: row["exception_id"] for case, row in mapping.items()} == {
        "CASE-001": "EXC-01", "CASE-002": "EXC-02", "CASE-003": "EXC-03"}


def test_a_case_with_no_matching_exception_is_unmapped(tiny_warehouse):
    from recon.evals.grade import load_case_rows

    mapping = map_cases_to_exceptions(load_case_rows(), answer_key(
        ("EXC-99", "duplicate", "BNK-9999", "")))
    assert mapping == {}


# ---------------------------------------------------------------------------
# Grading one case
# ---------------------------------------------------------------------------
def test_right_answer_is_correct():
    result = grade_case("CASE-001", trace("CASE-001", "fx_difference"),
                        FX_EXPECTED)
    assert result["classification_correct"] is True
    assert result["predicted_type"] == "fx_difference"


def test_wrong_answer_is_recorded_with_both_labels():
    result = grade_case("CASE-001", trace("CASE-001", "amount_mismatch"),
                        FX_EXPECTED)
    assert result["classification_correct"] is False
    assert (result["expected_type"], result["predicted_type"]) == ("fx_difference", "amount_mismatch")


def test_a_case_with_no_proposal_counts_as_wrong():
    """An agent that produces nothing is not 'not wrong' — it failed."""
    result = grade_case("CASE-001", trace("CASE-001", None, status="no_proposal"),
                        FX_EXPECTED)
    assert result["classification_correct"] is False
    assert result["predicted_type"] is None
    assert result["run_status"] == "no_proposal"


# ---------------------------------------------------------------------------
# Grading a whole run
# ---------------------------------------------------------------------------
def test_grade_run_scores_every_case(tiny_warehouse):
    write_answer_key(tiny_warehouse, TINY_KEY)
    write_run(tiny_warehouse, [
        trace("CASE-001", "fx_difference"),      # right
        trace("CASE-002", "bank_fee"),           # right
        trace("CASE-003", "timing_difference"),  # WRONG (it's a duplicate)
    ])

    run_id, results = grade_run()

    assert run_id == "run-1"
    assert len(results) == 3
    assert accuracy(results) == pytest.approx(2 / 3)
    wrong = results[~results["classification_correct"]].iloc[0]
    assert (wrong["case_id"], wrong["expected_type"], wrong["predicted_type"]) == \
        ("CASE-003", "duplicate", "timing_difference")


def test_accuracy_by_type_shows_where_it_fails(tiny_warehouse):
    write_answer_key(tiny_warehouse, TINY_KEY)
    write_run(tiny_warehouse, [
        trace("CASE-001", "fx_difference"),
        trace("CASE-002", "bank_fee"),
        trace("CASE-003", "timing_difference"),
    ])

    _, results = grade_run()
    by_type = accuracy_by_type(results).set_index("expected_type")

    assert by_type.loc["fx_difference", "accuracy"] == 1.0
    assert by_type.loc["duplicate", "accuracy"] == 0.0        # 0 of 1
    assert by_type.loc["duplicate", "total"] == 1


def test_grading_carries_cost_and_latency_through(tiny_warehouse):
    write_answer_key(tiny_warehouse, TINY_KEY)
    write_run(tiny_warehouse, [trace("CASE-001", "fx_difference", cost_usd=0.25)])

    _, results = grade_run()

    assert results.iloc[0]["cost_usd"] == 0.25
    assert results.iloc[0]["latency_seconds"] == 30.0
    assert results.iloc[0]["evidence"] == "BNK-0055"


# ---------------------------------------------------------------------------
# Grading the FIX, not just the label
# ---------------------------------------------------------------------------
FX_EXPECTED = {"exception_id": "EXC-01", "exception_type": "fx_difference",
               "expected_action": "book_fx_gain_loss", "cash_adjustment": -208.68,
               "offset_account": "7100 FX Gain/Loss"}
TIMING_EXPECTED = {"exception_id": "EXC-06", "exception_type": "timing_difference",
                   "expected_action": "no_entry", "cash_adjustment": 0.0,
                   "offset_account": ""}


def test_correct_entry_passes(tiny_warehouse):
    result = grade_case("CASE-001", trace("CASE-001", "fx_difference", lines=FX_LINES),
                        FX_EXPECTED)
    assert result["fix_correct"] is True
    assert result["proposed_cash_effect"] == -208.68
    assert result["offset_account_match"] is True


def test_right_label_but_wrong_amount_fails_the_fix(tiny_warehouse):
    """Classifying correctly is not enough — the entry has to be right."""
    typo = [dict(FX_LINES[0]), {**FX_LINES[1], "credit": "208.86"}]   # digits transposed
    result = grade_case("CASE-001", trace("CASE-001", "fx_difference", lines=typo), FX_EXPECTED)

    assert result["classification_correct"] is True
    assert result["fix_correct"] is False
    assert "vs expected" in result["fix_note"]


def test_no_entry_needed_is_respected(tiny_warehouse):
    result = grade_case("CASE-013", trace("CASE-013", "timing_difference", lines=[]),
                        TIMING_EXPECTED)
    assert result["fix_correct"] is True
    assert result["fix_note"] == "ok"


def test_proposing_an_entry_when_none_is_needed_fails(tiny_warehouse):
    """A timing difference clears by itself; 'fixing' it would be an error."""
    result = grade_case("CASE-013", trace("CASE-013", "timing_difference", lines=FX_LINES),
                        TIMING_EXPECTED)
    assert result["fix_correct"] is False
    assert result["fix_note"] == "proposed an entry where none was needed"


def test_missing_entry_when_one_is_needed_fails(tiny_warehouse):
    result = grade_case("CASE-001", trace("CASE-001", "fx_difference", lines=[]), FX_EXPECTED)
    assert result["fix_correct"] is False
    assert result["fix_note"] == "no entry proposed, but one was needed"


def test_a_cent_of_rounding_is_tolerated(tiny_warehouse):
    close = [dict(FX_LINES[0]), {**FX_LINES[1], "credit": "208.69"}]
    result = grade_case("CASE-001", trace("CASE-001", "fx_difference", lines=close), FX_EXPECTED)
    assert result["fix_correct"] is True


def test_offset_account_is_reported_but_does_not_fail_the_fix(tiny_warehouse):
    """Which expense/payable account to use is a judgement call; the cash
    movement is not. So a different offset is flagged, not failed."""
    other = [{"account": "2000 Accounts Payable", "debit": "208.68", "credit": "0.00", "memo": ""},
             FX_LINES[1]]
    result = grade_case("CASE-001", trace("CASE-001", "fx_difference", lines=other), FX_EXPECTED)

    assert result["fix_correct"] is True
    assert result["offset_account_match"] is False
    assert result["proposed_offset_accounts"] == "2000 Accounts Payable"


def test_fully_correct_needs_both_label_and_entry(tiny_warehouse):
    write_answer_key(tiny_warehouse, TINY_KEY)
    write_run(tiny_warehouse, [
        trace("CASE-001", "fx_difference", lines=FX_LINES),          # both right
        trace("CASE-002", "bank_fee", lines=FX_LINES),               # label right, entry wrong
        trace("CASE-003", "timing_difference", lines=[]),            # label wrong
    ])

    _, results = grade_run()

    assert accuracy(results) == pytest.approx(2 / 3)                  # labels
    assert accuracy(results, "fix_correct") == pytest.approx(1 / 3)   # entries
    assert fully_correct(results) == pytest.approx(1 / 3)             # both


# ---------------------------------------------------------------------------
# Confusion matrix and failure list
# ---------------------------------------------------------------------------
def graded(tiny_warehouse, traces):
    write_answer_key(tiny_warehouse, TINY_KEY)
    write_run(tiny_warehouse, traces)
    return grade_run()[1]


def test_confusion_matrix_puts_correct_answers_on_the_diagonal(tiny_warehouse):
    results = graded(tiny_warehouse, [
        trace("CASE-001", "fx_difference", lines=FX_LINES),          # correct
        trace("CASE-002", "duplicate"),                              # fee called a duplicate
        trace("CASE-003", None, status="no_proposal"),               # no answer at all
    ])

    matrix = confusion_matrix(results)

    assert matrix.loc["fx_difference", "fx_difference"] == 1         # on the diagonal
    assert matrix.loc["bank_fee", "duplicate"] == 1                  # the mix-up
    assert matrix.loc["duplicate", "(none)"] == 1                    # produced nothing


def test_failures_include_right_label_with_wrong_entry(tiny_warehouse):
    """The dangerous case: looks correct in a summary, posts a wrong number."""
    wrong_amount = [dict(FX_LINES[0]), {**FX_LINES[1], "credit": "999.00"}]
    results = graded(tiny_warehouse, [
        trace("CASE-001", "fx_difference", lines=wrong_amount),
        trace("CASE-002", "bank_fee", lines=[
            {"account": "6100 Bank Fees", "debit": "45.00", "credit": "0.00", "memo": ""},
            {"account": "1000 Cash - Operating", "debit": "0.00", "credit": "45.00", "memo": ""}]),
        trace("CASE-003", "duplicate", lines=[
            {"account": "2000 Accounts Payable", "debit": "11541.85", "credit": "0.00", "memo": ""},
            {"account": "1000 Cash - Operating", "debit": "11541.85", "credit": "0.00", "memo": ""}]),
    ])

    failures = failure_cases(results)

    assert list(failures["case_id"]) == ["CASE-001"]
    assert failures.iloc[0]["failure_kind"] == "wrong entry"
    assert failures.iloc[0]["expected_type"] == "fx_difference"      # the label was right


def test_failure_kinds_are_distinguished(tiny_warehouse):
    results = graded(tiny_warehouse, [
        trace("CASE-001", "amount_mismatch", lines=FX_LINES),        # wrong type
        trace("CASE-002", None, status="error"),                     # no answer
        trace("CASE-003", "duplicate", lines=[]),                    # right type, no entry
    ])

    kinds = dict(zip(failure_cases(results)["case_id"], failure_cases(results)["failure_kind"]))
    assert kinds == {"CASE-001": "wrong type", "CASE-002": "no answer", "CASE-003": "wrong entry"}


def test_a_perfect_run_has_no_failures(tiny_warehouse):
    results = graded(tiny_warehouse, [
        trace("CASE-001", "fx_difference", lines=FX_LINES),
        trace("CASE-002", "bank_fee", lines=[
            {"account": "6100 Bank Fees", "debit": "45.00", "credit": "0.00", "memo": ""},
            {"account": "1000 Cash - Operating", "debit": "0.00", "credit": "45.00", "memo": ""}]),
        trace("CASE-003", "duplicate", lines=[
            {"account": "2000 Accounts Payable", "debit": "11541.85", "credit": "0.00", "memo": ""},
            {"account": "1000 Cash - Operating", "debit": "11541.85", "credit": "0.00", "memo": ""}]),
    ])

    assert len(failure_cases(results)) == 0
    assert fully_correct(results) == 1.0
