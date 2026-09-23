"""
Load the agent's outputs into DuckDB — Phase 9, Step 1.

The transaction data lives in the warehouse; the agent's work lives in files.
To report across both, the files have to be loaded too:

    proposals.jsonl            -> raw.agent_proposals    (one row per proposal)
    decisions.jsonl            -> raw.agent_decisions    (one row per decision)
    traces/<run>/CASE-*.json   -> raw.agent_case_runs    (one row per case per run)

Same rules as the Phase 3 loader: idempotent (CREATE OR REPLACE), lineage
columns, and an explicit allow-list of inputs.

NOT loaded, ever: data/eval/ (the answer key and grading results). Ground
truth stays out of the warehouse — a test enforces this.

Run it:
    python -m recon.pipeline.load_agent_outputs
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb
import pandas as pd

from recon.config import settings


def read_jsonl(path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def proposal_rows() -> list[dict]:
    """One row per proposal. The journal lines stay as JSON text: a proposal
    has many lines, and flattening them here would change the grain."""
    return [{
        "proposal_id": p["proposal_id"],
        "created_at": p["created_at"],
        "case_id": p["case_id"],
        "classification": p["classification"],
        "status": p["status"],
        "explanation": p["explanation"],
        "line_count": len(p["lines"]),
        "entry_total": p["total"],
        "lines_json": json.dumps(p["lines"]),
        "evidence": ", ".join(p.get("evidence", [])),
        "_source_file": "proposals.jsonl",
    } for p in read_jsonl(settings.proposals_path)]


def decision_rows() -> list[dict]:
    """One row per human decision (append-only, so a case can have several)."""
    return [{
        "decision_id": d["decision_id"],
        "decided_at": d["decided_at"],
        "proposal_id": d["proposal_id"],
        "case_id": d["case_id"],
        "decision": d["decision"],
        "reviewer": d["reviewer"],
        "note": d["note"],
        "_source_file": "decisions.jsonl",
    } for d in read_jsonl(settings.decisions_path)]


def case_run_rows() -> list[dict]:
    """One row per case per run: how the agent's investigation went."""
    rows = []
    if not settings.traces_dir.exists():
        return rows
    for run_folder in sorted(settings.traces_dir.glob("run-*")):
        for path in sorted(run_folder.glob("CASE-*.json")):
            trace = json.loads(path.read_text())
            totals = trace.get("totals", {})
            proposals = trace.get("proposals", [])
            rows.append({
                # The FOLDER is the run — more reliable than a field inside
                # the file, which could be missing or stale after a move.
                "run_id": run_folder.name,
                "case_id": trace["case_id"],
                "status": trace["status"],
                "model_requested": trace.get("model_requested"),
                "started_at": trace.get("started_at"),
                "latency_seconds": trace.get("latency_seconds"),
                "steps": len(trace.get("steps", [])),
                "tool_calls": totals.get("tool_calls", 0),
                "tool_errors": totals.get("tool_errors", 0),
                "input_tokens": totals.get("input_tokens", 0),
                "output_tokens": totals.get("output_tokens", 0),
                "cost_usd": totals.get("cost_usd", 0.0),
                # The agent's final answer for this case in this run.
                "proposal_id": proposals[-1]["proposal_id"] if proposals else None,
                "classification": proposals[-1]["classification"] if proposals else None,
                "_source_file": f"traces/{run_folder.name}/{path.name}",
            })
    return rows


def load_table(con: duckdb.DuckDBPyConnection, table: str, rows: list[dict], columns: list[str]) -> int:
    """Create or replace raw.<table> from a list of dicts.

    An empty list still creates the table (with no rows), so downstream
    models don't break before the agent has ever run.
    """
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        # An empty pandas column has no type, and DuckDB then guesses INTEGER —
        # so `trim(decision_id)` downstream fails with "trim(INTEGER)" until
        # the first row exists. Text is the safe empty-table type; the dbt
        # staging models cast each column to what it should be.
        frame = frame.astype("string")
    frame["_loaded_at"] = datetime.now(timezone.utc)
    con.register("incoming", frame)
    con.execute(f"CREATE OR REPLACE TABLE raw.{table} AS SELECT * FROM incoming")
    con.unregister("incoming")
    return len(frame)


PROPOSAL_COLUMNS = ["proposal_id", "created_at", "case_id", "classification", "status",
                    "explanation", "line_count", "entry_total", "lines_json", "evidence",
                    "_source_file"]
DECISION_COLUMNS = ["decision_id", "decided_at", "proposal_id", "case_id", "decision",
                    "reviewer", "note", "_source_file"]
CASE_RUN_COLUMNS = ["run_id", "case_id", "status", "model_requested", "started_at",
                    "latency_seconds", "steps", "tool_calls", "tool_errors",
                    "input_tokens", "output_tokens", "cost_usd", "proposal_id",
                    "classification", "_source_file"]


def load_all() -> dict[str, int]:
    """Load every agent-output table. Returns {table: row count}."""
    settings.ensure_dirs()
    with duckdb.connect(str(settings.duckdb_path)) as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        return {
            "agent_proposals": load_table(con, "agent_proposals", proposal_rows(), PROPOSAL_COLUMNS),
            "agent_decisions": load_table(con, "agent_decisions", decision_rows(), DECISION_COLUMNS),
            "agent_case_runs": load_table(con, "agent_case_runs", case_run_rows(), CASE_RUN_COLUMNS),
        }


def main() -> None:
    counts = load_all()
    print(f"Loaded into {settings.duckdb_path.relative_to(settings.project_root)}:")
    for table, n in counts.items():
        print(f"  raw.{table:<16} {n:>4} rows")


if __name__ == "__main__":
    main()
