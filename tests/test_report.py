"""Tests for the Phase 8 report writer.

A report is what people read instead of the raw data, so it must never hide
a failure or print a number that doesn't match the results.

Builders (trace, answer_key, write_run...) come from test_grade.py.
"""

import json
from pathlib import Path

from test_grade import FX_LINES, TINY_KEY, trace, write_answer_key, write_run

from recon.evals.report import write_report

FEE_LINES = [
    {"account": "6100 Bank Fees", "debit": "45.00", "credit": "0.00", "memo": ""},
    {"account": "1000 Cash - Operating", "debit": "0.00", "credit": "45.00", "memo": ""},
]
DUPLICATE_LINES = [
    {"account": "2000 Accounts Payable", "debit": "11541.85", "credit": "0.00", "memo": ""},
    {"account": "1000 Cash - Operating", "debit": "11541.85", "credit": "0.00", "memo": ""},
]


def build_run(settings, traces):
    write_answer_key(settings, TINY_KEY)
    write_run(settings, traces)
    return write_report()


def read_report(folder) -> str:
    return (Path(folder) / "report.md").read_text()


def test_report_writes_all_five_files(tiny_warehouse):
    folder, _ = build_run(tiny_warehouse, [trace("CASE-001", "fx_difference", lines=FX_LINES)])

    written = {p.name for p in Path(folder).iterdir()}
    assert written == {"report.md", "metrics.json", "results.csv",
                       "failures.csv", "confusion_matrix.csv"}


def test_metrics_match_the_graded_results(tiny_warehouse):
    folder, metrics = build_run(tiny_warehouse, [
        trace("CASE-001", "fx_difference", lines=FX_LINES),       # fully correct
        trace("CASE-002", "bank_fee", lines=FX_LINES),            # label ok, entry wrong
        trace("CASE-003", "timing_difference"),                   # wrong label
    ])

    assert metrics["cases"] == 3
    assert metrics["classification_accuracy"] == 0.6667           # 2 of 3
    assert metrics["fix_accuracy"] == 0.3333                      # 1 of 3
    assert metrics["fully_correct"] == 0.3333
    # metrics.json holds the same numbers as the returned dict
    saved = json.loads((Path(folder) / "metrics.json").read_text())
    assert saved == metrics


def test_report_shows_each_failure_with_the_agents_own_words(tiny_warehouse):
    folder, _ = build_run(tiny_warehouse, [
        trace("CASE-001", "fx_difference", lines=FX_LINES),
        trace("CASE-002", "duplicate", lines=FEE_LINES),          # a fee called a duplicate
        trace("CASE-003", "duplicate", lines=DUPLICATE_LINES),
    ])

    report = read_report(folder)

    assert "## Failure cases" in report
    assert "CASE-002" in report and "wrong type" in report
    assert "Because of reasons (duplicate)." in report            # the explanation is quoted
    assert "1 case(s) were not fully correct" in report


def test_a_perfect_run_says_so_explicitly(tiny_warehouse):
    folder, metrics = build_run(tiny_warehouse, [
        trace("CASE-001", "fx_difference", lines=FX_LINES),
        trace("CASE-002", "bank_fee", lines=FEE_LINES),
        trace("CASE-003", "duplicate", lines=DUPLICATE_LINES),
    ])

    report = read_report(folder)

    assert metrics["fully_correct"] == 1.0
    assert "None — every case was classified correctly" in report


def test_report_always_carries_its_caveats(tiny_warehouse):
    """A score with no context invites over-claiming — especially a perfect one."""
    folder, _ = build_run(tiny_warehouse, [trace("CASE-001", "fx_difference", lines=FX_LINES)])

    report = read_report(folder)

    assert "## How to read this" in report
    for caveat in ["Sample size", "One run", "Synthetic, clean data"]:
        assert caveat in report


def test_failures_csv_lists_the_same_cases_as_the_report(tiny_warehouse):
    import pandas as pd

    folder, _ = build_run(tiny_warehouse, [
        trace("CASE-001", "amount_mismatch", lines=FX_LINES),     # wrong type
        trace("CASE-002", "bank_fee", lines=FEE_LINES),
        trace("CASE-003", "duplicate", lines=DUPLICATE_LINES),
    ])

    failures = pd.read_csv(Path(folder) / "failures.csv")
    assert list(failures["case_id"]) == ["CASE-001"]
    assert "CASE-001" in read_report(folder)
