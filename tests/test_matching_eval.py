"""Unit tests for the Phase 4 matcher evaluation (recon/matching/evaluate.py).

Each test hand-builds a TINY input — a few rows — where the right answer can
be worked out on paper, then checks the scorer reports exactly that.
No database, no generated data: these run in milliseconds and a failure
points straight at the scoring logic.
"""

import pandas as pd
import pytest

from recon.matching.evaluate import ids_in, score_cases, score_matches


# ---------------------------------------------------------------------------
# Tiny builders so each test reads like a sentence
# ---------------------------------------------------------------------------
def pairs(*rows):
    """pairs(("B1", "G1"), ("B2", "G2")) -> a DataFrame of matches."""
    return pd.DataFrame(rows, columns=["bank_txn_id", "gl_entry_id"])


def cases(*rows):
    """cases(("CASE-1", "B1", None), ...) -> a DataFrame of exception cases."""
    return pd.DataFrame(rows, columns=["case_id", "bank_txn_id", "gl_entry_id"])


def key(*rows):
    """key(("EXC-01", "fx_difference", "B1", "G1"), ...) -> an answer key.
    Empty sides are "" — exactly how answer_key.csv reads with keep_default_na=False."""
    return pd.DataFrame(
        rows, columns=["exception_id", "exception_type", "bank_txn_ids", "gl_entry_ids"]
    )


# ---------------------------------------------------------------------------
# ids_in
# ---------------------------------------------------------------------------
def test_ids_in_splits_and_trims():
    assert ids_in("BNK-0001, BNK-0002") == {"BNK-0001", "BNK-0002"}


def test_ids_in_empty_string_is_empty_set():
    assert ids_in("") == set()


# ---------------------------------------------------------------------------
# score_matches: precision and recall
# ---------------------------------------------------------------------------
def test_perfect_matching():
    truth = pairs(("B1", "G1"), ("B2", "G2"))
    result = score_matches(truth, truth)
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0


def test_one_wrong_pair_hurts_precision_and_recall():
    truth = pairs(("B1", "G1"), ("B2", "G2"))
    made = pairs(("B1", "G1"), ("B2", "G3"))        # B2 paired with the wrong row

    result = score_matches(made, truth)

    assert result["precision"] == 0.5                  # 1 of 2 made is right
    assert result["recall"] == 0.5                     # 1 of 2 true pairs found
    assert result["wrong_pairs"] == [("B2", "G3")]
    assert result["missed_pairs"] == [("B2", "G2")]


def test_few_but_correct_matches_keep_precision_but_lose_recall():
    """The Step 3 sabotage in miniature: cautious matcher, perfect precision,
    poor recall. Precision alone would hide the problem."""
    truth = pairs(("B1", "G1"), ("B2", "G2"), ("B3", "G3"), ("B4", "G4"))
    made = pairs(("B1", "G1"))

    result = score_matches(made, truth)

    assert result["precision"] == 1.0
    assert result["recall"] == 0.25


def test_zero_matches_reports_zero_precision():
    """0 correct / 0 made is mathematically undefined. We report 0.0 (via
    max(..., 1)) rather than crash or claim perfection. This test pins that
    choice down so it can't change by accident."""
    result = score_matches(pairs(), pairs(("B1", "G1")))
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0


# ---------------------------------------------------------------------------
# score_cases: caught / missed / split / merged / false alarm
# ---------------------------------------------------------------------------
def status_of(results: pd.DataFrame, exception_id: str) -> str:
    return results.set_index("exception_id").loc[exception_id, "status"]


def test_caught_both_sides():
    """An FX-style exception: one case holding exactly its bank + ledger row."""
    results, false_alarms = score_cases(
        cases(("CASE-1", "B1", "G1")),
        key(("EXC-01", "fx_difference", "B1", "G1")),
    )
    assert status_of(results, "EXC-01") == "caught"
    assert false_alarms == []


def test_caught_one_side():
    """A bank-fee-style exception: bank row only."""
    results, _ = score_cases(
        cases(("CASE-1", "B9", None)),
        key(("EXC-01", "bank_fee", "B9", "")),
    )
    assert status_of(results, "EXC-01") == "caught"


def test_missed_when_rows_were_hidden_in_a_match():
    """No case contains the exception's rows — the matcher swallowed them."""
    results, _ = score_cases(
        cases(),
        key(("EXC-01", "duplicate", "", "G5")),
    )
    assert status_of(results, "EXC-01") == "missed"


def test_split_when_rows_land_in_two_cases():
    """Bank and ledger halves of one exception ended up in separate cases."""
    results, _ = score_cases(
        cases(("CASE-1", "B1", None), ("CASE-2", None, "G1")),
        key(("EXC-01", "amount_mismatch", "B1", "G1")),
    )
    assert status_of(results, "EXC-01") == "split"


def test_merged_when_a_case_holds_extra_rows():
    """The case contains this exception's row PLUS an unrelated one."""
    results, _ = score_cases(
        cases(("CASE-1", "B7", "G5")),
        key(("EXC-01", "duplicate", "", "G5")),
    )
    assert status_of(results, "EXC-01") == "merged"


def test_false_alarm_when_case_is_all_normal_rows():
    results, false_alarms = score_cases(
        cases(("CASE-1", "B1", None), ("CASE-2", "B2", "G2")),
        key(("EXC-01", "bank_fee", "B1", "")),
    )
    assert status_of(results, "EXC-01") == "caught"
    assert false_alarms == ["CASE-2"]


@pytest.mark.parametrize("n_exceptions", [1, 3, 10])
def test_one_result_row_per_exception(n_exceptions):
    """parametrize runs this test 3 times with different inputs.
    Whatever happens, every exception gets exactly one verdict."""
    answer_key = key(*[(f"EXC-{i}", "bank_fee", f"B{i}", "") for i in range(n_exceptions)])
    results, _ = score_cases(cases(), answer_key)
    assert len(results) == n_exceptions
