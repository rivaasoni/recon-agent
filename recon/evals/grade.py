"""
Grading the agent against ground truth — Phase 8.

Inputs (never mixed until here):
    data/eval/answer_key.csv          what each seeded exception really is
    data/processed/traces/<run>/      what the agent decided, per case

The join problem: the answer key is keyed by EXC-01..EXC-16 (from data
generation) and the run by CASE-001..CASE-016 (from matching). Those IDs were
deliberately kept unrelated so nothing could leak. We join them on the bank
and ledger ROW IDs they have in common.

Everything here is a plain function of data, so it can be tested without an
API key, a warehouse or a UI.
"""

from __future__ import annotations

import json
from decimal import Decimal

import duckdb
import pandas as pd

from recon.config import settings

CASH_ACCOUNT = "1000 Cash - Operating"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def latest_run_id() -> str:
    """The most recent run folder that has a summary."""
    runs = sorted(p for p in settings.traces_dir.glob("run-*") if (p / "_summary.json").exists())
    if not runs:
        raise SystemExit(f"No runs found in {settings.traces_dir}. Run: python -m recon.agent.run_all")
    return runs[-1].name


def load_run(run_id: str | None = None) -> tuple[str, dict[str, dict]]:
    """Return (run_id, {case_id: trace}) for one run."""
    run_id = run_id or latest_run_id()
    folder = settings.traces_dir / run_id
    if not folder.exists():
        raise SystemExit(f"No run folder at {folder}")
    traces = {}
    for path in sorted(folder.glob("CASE-*.json")):
        trace = json.loads(path.read_text())
        traces[trace["case_id"]] = trace
    return run_id, traces


def load_answer_key() -> pd.DataFrame:
    path = settings.eval_dir / "answer_key.csv"
    if not path.exists():
        raise SystemExit(f"No answer key at {path}. Run: python -m recon.data_gen.generate")
    # keep_default_na=False so empty ID lists read as "" rather than NaN.
    return pd.read_csv(path, keep_default_na=False)


def load_case_rows() -> dict[str, set[str]]:
    """{case_id: the bank/ledger row IDs it covers}, from the warehouse."""
    with duckdb.connect(str(settings.duckdb_path), read_only=True) as con:
        rows = con.execute(
            "select case_id, bank_txn_id, gl_entry_id from matching.exceptions"
        ).fetchall()
    return {case_id: {i for i in (bank_id, gl_id) if i} for case_id, bank_id, gl_id in rows}


# ---------------------------------------------------------------------------
# The join: which case is which seeded exception?
# ---------------------------------------------------------------------------
def ids_in(text: str) -> set[str]:
    """'BNK-0001, GL-0002' -> {'BNK-0001', 'GL-0002'};  '' -> set()."""
    return {part.strip() for part in str(text).split(",") if part.strip()}


def map_cases_to_exceptions(case_rows: dict[str, set[str]], answer_key: pd.DataFrame) -> dict[str, dict]:
    """{case_id: the answer-key row for the exception it contains}.

    Matched on shared bank/ledger row IDs — the only thing the two sides have
    in common. A case with no matching exception is left out (it would be a
    false alarm, which Phase 4 already grades).
    """
    mapping = {}
    for exception in answer_key.to_dict("records"):
        exception_rows = ids_in(exception["bank_txn_ids"]) | ids_in(exception["gl_entry_ids"])
        for case_id, rows in case_rows.items():
            if rows & exception_rows:
                mapping[case_id] = exception
    return mapping


# ---------------------------------------------------------------------------
# Grading one case
# ---------------------------------------------------------------------------
def cash_effect(lines: list[dict]) -> Decimal:
    """How much a proposed entry changes the ledger's CASH balance.

    Debit cash = cash goes up, credit cash = cash goes down. Other accounts
    are the other side of the entry and don't move cash.
    """
    total = Decimal("0")
    for line in lines:
        if line["account"] == CASH_ACCOUNT:
            total += Decimal(str(line.get("debit", 0) or 0))
            total -= Decimal(str(line.get("credit", 0) or 0))
    return total


def offset_accounts(lines: list[dict]) -> list[str]:
    """The non-cash accounts in an entry — the 'other side'."""
    return sorted({line["account"] for line in lines if line["account"] != CASH_ACCOUNT})


def grade_fix(proposal: dict | None, expected: dict | None) -> dict:
    """Is the PROPOSED ENTRY right, not just the label?

    Compared on net cash effect, to the cent. The offset account is reported
    but NOT counted as a failure: which expense or payable account a
    difference belongs in is a judgement call, while the cash movement is not.
    """
    if expected is None:
        return {"fix_correct": False, "fix_note": "no answer key entry",
                "expected_cash_adjustment": None, "proposed_cash_effect": None,
                "expected_offset_account": None, "proposed_offset_accounts": "",
                "offset_account_match": None}

    expected_cash = Decimal(str(expected["cash_adjustment"]))
    expected_offset = (expected.get("offset_account") or "").strip()
    no_entry_expected = expected["expected_action"] == "no_entry"

    if proposal is None:
        return {"fix_correct": False, "fix_note": "no proposal",
                "expected_cash_adjustment": float(expected_cash), "proposed_cash_effect": None,
                "expected_offset_account": expected_offset, "proposed_offset_accounts": "",
                "offset_account_match": None}

    lines = proposal.get("lines") or []
    proposed_cash = cash_effect(lines)
    proposed_offsets = offset_accounts(lines)

    if no_entry_expected:
        correct = not lines
        note = "ok" if correct else "proposed an entry where none was needed"
    elif not lines:
        correct, note = False, "no entry proposed, but one was needed"
    else:
        # A cent of tolerance: rounding differs between rates and cents.
        correct = abs(proposed_cash - expected_cash) <= Decimal("0.01")
        note = "ok" if correct else (
            f"cash effect {proposed_cash} vs expected {expected_cash}")

    return {
        "fix_correct": correct,
        "fix_note": note,
        "expected_cash_adjustment": float(expected_cash),
        "proposed_cash_effect": float(proposed_cash),
        "expected_offset_account": expected_offset,
        "proposed_offset_accounts": ", ".join(proposed_offsets),
        # Soft signal only — reported, never counted as a failure.
        "offset_account_match": (expected_offset in proposed_offsets) if expected_offset else None,
    }


def agent_answer(trace: dict) -> dict | None:
    """The agent's final proposal for a case (the last one it made)."""
    return trace["proposals"][-1] if trace.get("proposals") else None


def grade_case(case_id: str, trace: dict, expected: dict | None) -> dict:
    """Compare one case's agent answer with the answer key."""
    proposal = agent_answer(trace)
    predicted = proposal["classification"] if proposal else None
    truth = expected["exception_type"] if expected else None

    return {
        "case_id": case_id,
        "exception_id": expected["exception_id"] if expected else None,
        "expected_type": truth,
        "predicted_type": predicted,
        # Only a completed run with a proposal can be correct.
        "classification_correct": bool(predicted and truth and predicted == truth),
        "run_status": trace.get("status"),
        "steps": len(trace.get("steps", [])),
        "tool_calls": trace.get("totals", {}).get("tool_calls", 0),
        "cost_usd": trace.get("totals", {}).get("cost_usd", 0.0),
        "latency_seconds": trace.get("latency_seconds"),
        "explanation": proposal["explanation"] if proposal else None,
        "evidence": ", ".join(proposal.get("evidence", [])) if proposal else "",
        **grade_fix(proposal, expected),
    }


def grade_run(run_id: str | None = None) -> tuple[str, pd.DataFrame]:
    """Grade every case in a run. Returns (run_id, one row per case)."""
    run_id, traces = load_run(run_id)
    expected_by_case = map_cases_to_exceptions(load_case_rows(), load_answer_key())

    rows = [grade_case(case_id, trace, expected_by_case.get(case_id))
            for case_id, trace in sorted(traces.items())]
    return run_id, pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Summarising
# ---------------------------------------------------------------------------
def accuracy(results: pd.DataFrame, column: str = "classification_correct") -> float:
    """Share of cases correct (0.0 - 1.0). Also works for 'fix_correct'."""
    return results[column].mean() if len(results) else 0.0


def fully_correct(results: pd.DataFrame) -> float:
    """Share of cases where BOTH the label and the entry are right — the
    number that matters if a human is going to post the entry."""
    if not len(results):
        return 0.0
    return (results["classification_correct"] & results["fix_correct"]).mean()


def confusion_matrix(results: pd.DataFrame) -> pd.DataFrame:
    """Expected type (rows) vs predicted type (columns).

    The diagonal is correct answers; everything off it is a specific mix-up
    to investigate. A '(none)' column means the agent produced no answer at
    all — a different failure from naming the wrong type.
    """
    if not len(results):
        return pd.DataFrame()
    predicted = results["predicted_type"].fillna("(none)")
    matrix = pd.crosstab(results["expected_type"], predicted)
    matrix.index.name = "expected"
    matrix.columns.name = "predicted"
    return matrix


def failure_cases(results: pd.DataFrame) -> pd.DataFrame:
    """Every case that is not fully correct — the list a human reads.

    Includes cases with the right label but a wrong entry: those look fine in
    a summary yet would post the wrong number.
    """
    failures = results[~(results["classification_correct"] & results["fix_correct"])].copy()
    failures["failure_kind"] = failures.apply(
        lambda row: "no answer" if row["predicted_type"] is None
        else "wrong type" if not row["classification_correct"]
        else "wrong entry",
        axis=1,
    )
    columns = ["case_id", "exception_id", "failure_kind", "expected_type", "predicted_type",
               "expected_cash_adjustment", "proposed_cash_effect", "fix_note",
               "run_status", "cost_usd", "evidence", "explanation"]
    return failures[columns].reset_index(drop=True)


def accuracy_by_type(results: pd.DataFrame) -> pd.DataFrame:
    """Per-type accuracy. With only 2-3 cases per type, read these as a
    pointer to what to investigate, not as a reliable percentage."""
    grouped = (
        results.groupby("expected_type")["classification_correct"]
        .agg(correct="sum", total="count")
        .reset_index()
    )
    grouped["accuracy"] = grouped["correct"] / grouped["total"]
    return grouped.sort_values("expected_type").reset_index(drop=True)
