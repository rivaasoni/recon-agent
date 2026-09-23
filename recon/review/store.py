"""
The review store — Phase 7, Step 1.

Gathers everything a human reviewer needs into one "review item" per case:

    matching.exceptions (DuckDB)  ->  the facts of the case
    proposals.jsonl               ->  what the agent proposed
    traces/<run>/<CASE>.json      ->  how it reached that proposal
    decisions.jsonl               ->  what the human decided   (written here)

Kept separate from the Streamlit app so the logic can be tested on its own.

Two rules:
  1. Append-only. A decision is never edited or deleted; changing your mind
     appends a NEW record and the most recent one wins. The history stays
     intact, which is what an auditor needs.
  2. Approving posts NOTHING. It marks a proposal as ready for a human to
     post in the accounting system. This project never writes to the ledger.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from recon.config import settings

APPROVED = "approved"
REJECTED = "rejected"
VALID_DECISIONS = (APPROVED, REJECTED)


# ---------------------------------------------------------------------------
# Reading the pieces
# ---------------------------------------------------------------------------
def read_jsonl(path: Path) -> list[dict]:
    """Read a .jsonl file (one JSON object per line). Missing file -> []."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_cases() -> list[dict]:
    """Every exception case, from the warehouse (read-only)."""
    with duckdb.connect(str(settings.duckdb_path), read_only=True) as con:
        cursor = con.execute("select * from matching.exceptions order by case_id")
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def latest_by(records: list[dict], key: str) -> dict[str, dict]:
    """Keep the LAST record for each value of `key` (file order = time order)."""
    return {record[key]: record for record in records}


def load_proposals() -> list[dict]:
    return read_jsonl(settings.proposals_path)


def load_decisions() -> list[dict]:
    return read_jsonl(settings.decisions_path)


def find_trace(case_id: str, run_id: str | None = None) -> dict | None:
    """The agent's trace for a case. Without a run_id, the most recent run
    that has one."""
    if not settings.traces_dir.exists():
        return None
    runs = sorted((p for p in settings.traces_dir.iterdir() if p.is_dir()), reverse=True)
    for run in runs:
        if run_id and run.name != run_id:
            continue
        path = run / f"{case_id}.json"
        if path.exists():
            return json.loads(path.read_text())
    return None


# ---------------------------------------------------------------------------
# Writing a decision
# ---------------------------------------------------------------------------
def record_decision(proposal_id: str, case_id: str, decision: str,
                    reviewer: str, note: str = "") -> dict:
    """Append one approve/reject decision. Returns the record written."""
    if decision not in VALID_DECISIONS:
        raise ValueError(f"decision must be one of {VALID_DECISIONS}, got '{decision}'")
    if not reviewer.strip():
        raise ValueError("reviewer is required — an audit log needs to say who decided")

    record = {
        "decision_id": f"DEC-{uuid.uuid4().hex[:8].upper()}",
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "proposal_id": proposal_id,
        "case_id": case_id,
        "decision": decision,
        "reviewer": reviewer.strip(),
        "note": note.strip(),
    }
    settings.decisions_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings.decisions_path, "a", encoding="utf-8") as f:   # "a" = append
        f.write(json.dumps(record) + "\n")
    return record


def decision_history(proposal_id: str) -> list[dict]:
    """Every decision ever recorded for a proposal, oldest first."""
    return [d for d in load_decisions() if d["proposal_id"] == proposal_id]


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------
def review_items(run_id: str | None = None) -> list[dict]:
    """One row per case: the facts, the agent's proposal, its trace and the
    current decision.

    status is one of:
        no_proposal - the agent produced nothing to review
        pending     - waiting for a human
        approved / rejected - decided (the most recent decision wins)
    """
    proposals_by_case = latest_by(load_proposals(), "case_id")
    decisions_by_proposal = latest_by(load_decisions(), "proposal_id")

    items = []
    for case in load_cases():
        proposal = proposals_by_case.get(case["case_id"])
        decision = decisions_by_proposal.get(proposal["proposal_id"]) if proposal else None
        items.append({
            "case_id": case["case_id"],
            "case": case,
            "proposal": proposal,
            "decision": decision,
            "trace": find_trace(case["case_id"], run_id),
            "status": ("no_proposal" if not proposal
                       else decision["decision"] if decision
                       else "pending"),
        })
    return items


def approved_entries(items: list[dict] | None = None) -> list[dict]:
    """The journal lines of every APPROVED proposal, ready for a person to
    post in the accounting system.

    This is where our system stops. It produces a file for a human to import;
    it never posts anything itself. Approved proposals with no lines (e.g. a
    timing difference, where the right action is to wait) contribute no rows.
    """
    rows = []
    for item in items if items is not None else review_items():
        if item["status"] != APPROVED:
            continue
        proposal, decision = item["proposal"], item["decision"]
        for line in proposal["lines"]:
            rows.append({
                "case_id": item["case_id"],
                "proposal_id": proposal["proposal_id"],
                "classification": proposal["classification"],
                "account": line["account"],
                "debit": line["debit"],
                "credit": line["credit"],
                "memo": line["memo"],
                "approved_by": decision["reviewer"],
                "approved_at": decision["decided_at"],
            })
    return rows


def entries_csv(rows: list[dict]) -> str:
    """Journal lines as CSV text (for a download button or a file)."""
    columns = ["case_id", "proposal_id", "classification", "account", "debit",
               "credit", "memo", "approved_by", "approved_at"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def review_metrics(items: list[dict]) -> dict:
    """Headline numbers for the reviewer: workload, value and agent cost."""
    def total_of(item: dict) -> float:
        return float(item["proposal"]["total"]) if item["proposal"] else 0.0

    approved = [i for i in items if i["status"] == APPROVED]
    pending = [i for i in items if i["status"] == "pending"]
    traces = [i["trace"] for i in items if i["trace"]]

    return {
        "counts": status_counts(items),
        # The size of the corrections involved, not a bank balance.
        "pending_value": round(sum(total_of(i) for i in pending), 2),
        "approved_value": round(sum(total_of(i) for i in approved), 2),
        "no_entry_approved": sum(1 for i in approved if not i["proposal"]["lines"]),
        "agent_cost_usd": round(sum(t["totals"].get("cost_usd", 0) for t in traces), 4),
        "agent_seconds": round(sum(t.get("latency_seconds") or 0 for t in traces), 1),
    }


def status_counts(items: list[dict]) -> dict[str, int]:
    """How many cases are pending / approved / rejected / without a proposal."""
    counts = {"pending": 0, APPROVED: 0, REJECTED: 0, "no_proposal": 0}
    for item in items:
        counts[item["status"]] += 1
    return counts
