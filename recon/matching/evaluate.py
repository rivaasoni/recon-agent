"""
Evaluate the rule-based matcher against ground truth — Phase 4, Step 3.

Two questions:

  1. Were the MATCHES correct?
       precision = correct pairs / pairs the rules made
       recall    = correct pairs / pairs that truly exist

  2. Did every seeded EXCEPTION surface as exactly one case?
       caught  - exactly one case, containing exactly this exception's rows
       missed  - no case at all (its rows were hidden inside a match!)
       split   - its rows ended up in more than one case
       merged  - its case also contains rows from something else
     ...and is any case a FALSE ALARM (made only of normal rows)?

Ground truth is read from CSVs in data/eval/. The warehouse is opened
READ-ONLY. The two never mix — the answer key never enters DuckDB.

Run it (after the pipeline):
    python -m recon.matching.evaluate
"""

from __future__ import annotations

import duckdb
import pandas as pd

from recon.config import settings


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_matcher_output() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rule 1 matches and the exception cases, straight from the warehouse."""
    with duckdb.connect(str(settings.duckdb_path), read_only=True) as con:
        matches = con.execute(
            "select bank_txn_id, gl_entry_id from matching.match_rule1_exact"
        ).df()
        cases = con.execute(
            "select case_id, bank_txn_id, gl_entry_id from matching.exceptions"
        ).df()
    return matches, cases


def load_ground_truth() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The answer key and the true pairs, from data/eval/."""
    # keep_default_na=False: read empty cells as "" instead of NaN, so the
    # ID lists below are always strings.
    answer_key = pd.read_csv(settings.eval_dir / "answer_key.csv", keep_default_na=False)
    true_matches = pd.read_csv(settings.eval_dir / "true_matches.csv")
    return answer_key, true_matches


# ---------------------------------------------------------------------------
# Scoring — plain functions of DataFrames, so they're easy to unit test
# ---------------------------------------------------------------------------
def score_matches(matches: pd.DataFrame, true_matches: pd.DataFrame) -> dict:
    """Compare the pairs the rules made with the pairs that truly exist."""
    made = set(zip(matches["bank_txn_id"], matches["gl_entry_id"]))
    truth = set(zip(true_matches["bank_txn_id"], true_matches["gl_entry_id"]))
    correct = made & truth

    return {
        "made": len(made),
        "true": len(truth),
        "correct": len(correct),
        # max(..., 1) avoids dividing by zero when a set is empty.
        "precision": len(correct) / max(len(made), 1),
        "recall": len(correct) / max(len(truth), 1),
        "wrong_pairs": sorted(made - truth),    # matched, but shouldn't be
        "missed_pairs": sorted(truth - made),   # should be matched, but isn't
    }


def ids_in(text: str) -> set[str]:
    """'BNK-0001, BNK-0002' -> {'BNK-0001', 'BNK-0002'};  '' -> set()."""
    return {part.strip() for part in text.split(",") if part.strip()}


def score_cases(cases: pd.DataFrame, answer_key: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Check each answer-key exception against the cases the matcher raised.

    Returns (per-exception results, list of false-alarm case IDs).
    """
    # Each case as a set of row IDs, e.g. CASE-003 -> {'BNK-0029', 'GL-0017'}
    case_rows = {
        row.case_id: {i for i in (row.bank_txn_id, row.gl_entry_id) if pd.notna(i)}
        for row in cases.itertuples()
    }

    results = []
    explained_cases = set()  # cases that belong to SOME exception
    for exc in answer_key.itertuples():
        exc_rows = ids_in(exc.bank_txn_ids) | ids_in(exc.gl_entry_ids)
        # Which cases contain at least one of this exception's rows?
        touching = [cid for cid, rows in case_rows.items() if rows & exc_rows]
        explained_cases.update(touching)

        if not touching:
            status = "missed"
        elif len(touching) > 1:
            status = "split"
        elif case_rows[touching[0]] != exc_rows:
            status = "merged"
        else:
            status = "caught"

        results.append({
            "exception_id": exc.exception_id,
            "exception_type": exc.exception_type,
            "status": status,
            "case_ids": ", ".join(touching),
        })

    false_alarms = sorted(set(case_rows) - explained_cases)
    return pd.DataFrame(results), false_alarms


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def main() -> None:
    matches, cases = load_matcher_output()
    answer_key, true_matches = load_ground_truth()

    m = score_matches(matches, true_matches)
    results, false_alarms = score_cases(cases, answer_key)
    status_counts = results["status"].value_counts()

    print("=== Rule 1 matches ===")
    print(f"  Pairs made:     {m['made']:>4}   correct: {m['correct']:>4}   -> precision {m['precision']:.1%}")
    print(f"  Pairs that exist: {m['true']:>2}   found:   {m['correct']:>4}   -> recall    {m['recall']:.1%}")
    for pair in m["wrong_pairs"]:
        print(f"  WRONG MATCH:  {pair}")
    for pair in m["missed_pairs"]:
        print(f"  MISSED MATCH: {pair}")

    print("\n=== Exceptions surfaced ===")
    print(f"  In answer key: {len(answer_key)}")
    for status in ("caught", "missed", "split", "merged"):
        print(f"  {status:<8} {status_counts.get(status, 0):>3}")
    # Show at most 10 IDs so a bad run doesn't flood the screen.
    shown = ", ".join(false_alarms[:10]) + (" ..." if len(false_alarms) > 10 else "")
    print(f"  Cases raised: {len(cases)}   false alarms: {len(false_alarms)}  {shown}")

    print("\n=== By exception type ===")
    by_type = (
        results.assign(caught=results["status"] == "caught")
        .groupby("exception_type")["caught"]
        .agg(caught="sum", total="count")
    )
    print(by_type.to_string())

    problems = results[results["status"] != "caught"]
    if len(problems):
        print("\n=== Problems ===")
        print(problems.to_string(index=False))


if __name__ == "__main__":
    main()
