"""
Run the agent on EVERY exception case — Phase 6, Step 4.

One run = one folder of traces (data/processed/traces/<run_id>/) plus a
_summary.json with one row per case. Phase 7 (review) and Phase 8 (grading)
read these.

Robustness:
  - Error isolation: a failed case is recorded (status 'error') and the run
    moves on. investigate_case() already catches its own errors.
  - Budget cap: before starting each case, check total spend so far. Once it
    passes --max-cost, no new cases start; the rest are 'skipped_budget'.

This COSTS MONEY: roughly $0.15 per case on Opus 5, so ~$2-4 for all 16.

Run it:
    python -m recon.agent.run_all                          # all cases
    python -m recon.agent.run_all --cases CASE-003,CASE-010
    python -m recon.agent.run_all --max-cost 5
    python -m recon.agent.run_all --resume run-20260921-215515   # finish an interrupted run
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import anyio
from anthropic import AsyncAnthropic
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from recon.agent.loop import investigate_case, new_run_id, now_iso
from recon.config import settings
from recon.mcp_server.launch import SERVER

DEFAULT_MAX_COST_USD = 10.00


async def list_case_ids(session: ClientSession) -> list[str]:
    """Every open case, via the same MCP tool the agent uses."""
    result = await session.call_tool("list_exception_cases", {})
    return [case["case_id"] for case in json.loads(result.content[0].text)["cases"]]


def summary_row(trace: dict) -> dict:
    """The one-line version of a trace, for the run summary."""
    proposals = trace["proposals"]
    return {
        "case_id": trace["case_id"],
        "status": trace["status"],
        # The LAST successful proposal is the agent's final answer.
        "classification": proposals[-1]["classification"] if proposals else None,
        "proposal_id": proposals[-1]["proposal_id"] if proposals else None,
        "proposal_count": len(proposals),
        "steps": len(trace["steps"]),
        "tool_calls": trace["totals"]["tool_calls"],
        "tool_errors": trace["totals"]["tool_errors"],
        "cost_usd": trace["totals"]["cost_usd"],
        "latency_seconds": trace["latency_seconds"],
        "models_used": sorted({step["model"] for step in trace["steps"]}),
        "error": trace["error"],
    }


def print_row(row: dict) -> None:
    print(f"{row['case_id']:<9} {row['status']:<18} {str(row['classification']):<22} "
          f"{row['steps']:>3} steps  ${row['cost_usd']:>7.4f}  {row['latency_seconds'] or 0:>6.1f}s")


async def investigate_with_retries(case_id, session, client, run_id, retries, sleep_seconds=5.0):
    """Run one case, retrying if it fails for a transient reason.

    Network blips (APIConnectionError) are common on long runs. A failed case
    costs nothing (no steps completed), so retrying is cheap.
    """
    for attempt in range(1, retries + 2):          # 1 try + `retries` retries
        trace = await investigate_case(case_id, session, client, run_id, verbose=False)
        row = summary_row(trace)
        row["attempts"] = attempt
        if row["status"] != "error":
            return row
        if attempt <= retries:
            print(f"{case_id:<9} attempt {attempt} failed ({trace['error']}) — retrying in {sleep_seconds:.0f}s")
            await anyio.sleep(sleep_seconds)
    return row


async def run_cases(
    case_ids: list[str],
    session: ClientSession,
    client: Any,
    run_id: str,
    max_cost_usd: float = DEFAULT_MAX_COST_USD,
    retries: int = 1,
    retry_sleep_seconds: float = 5.0,
    previous_rows: dict[str, dict] | None = None,
) -> dict:
    """Investigate each case in turn. Returns the run summary (also saved).

    `previous_rows` are results kept from an earlier attempt at this same run
    (see --resume); they are included in the summary without being re-run.
    """
    summary = {
        "run_id": run_id,
        "model_requested": settings.model,
        "started_at": now_iso(),
        "finished_at": None,
        "max_cost_usd": max_cost_usd,
        "cases": [],
        "totals": {},
    }
    spent = 0.0

    for case_id in case_ids:
        # Budget check BEFORE starting a case, so we never abandon one halfway.
        if spent >= max_cost_usd:
            row = {"case_id": case_id, "status": "skipped_budget", "classification": None,
                   "proposal_id": None, "proposal_count": 0, "steps": 0, "tool_calls": 0,
                   "tool_errors": 0, "cost_usd": 0.0, "latency_seconds": None,
                   "models_used": [], "error": None}
        else:
            row = await investigate_with_retries(case_id, session, client, run_id,
                                                 retries, retry_sleep_seconds)
            spent += row["cost_usd"]
        summary["cases"].append(row)
        print_row(row)

    # Keep results from an earlier attempt at this run (--resume), then sort
    # so the summary always reads in case order.
    already_done = previous_rows or {}
    done_ids = {row["case_id"] for row in summary["cases"]}
    summary["cases"].extend(row for case_id, row in already_done.items() if case_id not in done_ids)
    summary["cases"].sort(key=lambda row: row["case_id"])

    rows = summary["cases"]
    statuses = [r["status"] for r in rows]
    summary["finished_at"] = now_iso()
    summary["totals"] = {
        "cases": len(rows),
        "completed": statuses.count("completed"),
        "not_completed": len(rows) - statuses.count("completed"),
        "status_counts": {s: statuses.count(s) for s in sorted(set(statuses))},
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
        "cost_usd_this_attempt": round(spent, 4),
        "latency_seconds": round(sum(r["latency_seconds"] or 0 for r in rows), 1),
        "tool_calls": sum(r["tool_calls"] for r in rows),
    }

    folder = settings.traces_dir / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def load_previous_rows(run_id: str) -> dict[str, dict]:
    """Rows from an earlier attempt at this run, keyed by case ID."""
    path = settings.traces_dir / run_id / "_summary.json"
    if not path.exists():
        raise SystemExit(f"No run found at {path}")
    return {row["case_id"]: row for row in json.loads(path.read_text())["cases"]}


async def main(case_filter: list[str] | None, max_cost_usd: float,
               retries: int, resume_run_id: str | None) -> None:
    # Checked FIRST, so a missing key stops us before anything else starts.
    client = AsyncAnthropic(api_key=settings.anthropic_api_key())

    # --resume: reuse an existing run folder and only redo what didn't finish,
    # so cases already paid for aren't run (or charged) twice.
    previous_rows: dict[str, dict] = {}
    unfinished: list[str] | None = None
    if resume_run_id:
        run_id = resume_run_id
        previous_rows = load_previous_rows(run_id)
        unfinished = [case_id for case_id, row in previous_rows.items()
                      if row["status"] != "completed"]
    else:
        run_id = new_run_id()

    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            case_ids = case_filter or unfinished or await list_case_ids(session)
            if resume_run_id and not case_ids:
                raise SystemExit(f"Nothing to resume: every case in {run_id} completed.")
            print(f"Run {run_id}: {len(case_ids)} cases, model {settings.model}, "
                  f"budget ${max_cost_usd:.2f}\n")
            print(f"{'CASE':<9} {'STATUS':<18} {'CLASSIFICATION':<22} {'STEPS':>9}  {'COST':>8}  {'TIME':>7}")
            summary = await run_cases(case_ids, session, client, run_id, max_cost_usd,
                                      retries=retries, previous_rows=previous_rows)

    t = summary["totals"]
    print(f"\n{t['completed']}/{t['cases']} completed   statuses: {t['status_counts']}")
    print(f"Cost this attempt: ${t['cost_usd_this_attempt']:.4f}   run total: ${t['cost_usd']:.4f}")
    print(f"Total agent time: {t['latency_seconds']}s   tool calls: {t['tool_calls']}")
    print(f"Traces + summary: {settings.traces_dir / run_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the agent on every exception case.")
    parser.add_argument("--cases", help="Comma-separated case IDs, e.g. CASE-003,CASE-010")
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST_USD,
                        help=f"Stop starting new cases once spend passes this (default ${DEFAULT_MAX_COST_USD})")
    parser.add_argument("--retries", type=int, default=1,
                        help="Retries per case after a failure, e.g. a network blip (default 1)")
    parser.add_argument("--resume", metavar="RUN_ID",
                        help="Redo only the unfinished cases of an existing run, e.g. run-20260921-215515")
    args = parser.parse_args()
    cases = [c.strip().upper() for c in args.cases.split(",")] if args.cases else None
    anyio.run(main, cases, args.max_cost, args.retries, args.resume)
