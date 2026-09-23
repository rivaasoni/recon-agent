"""
Print a saved agent trace in a readable form — Phase 6, Step 5.

Traces are JSON (good for the Phase 8 grader, hard for a human). This shows
one case's investigation the way a reviewer would want to read it.

Run it:
    python -m recon.agent.show_trace CASE-006             # latest run
    python -m recon.agent.show_trace CASE-006 run-20260921-215515
    python -m recon.agent.show_trace --runs               # list runs
"""

from __future__ import annotations

import json
import sys

from recon.config import settings

RESULT_PREVIEW_CHARS = 200


def list_runs() -> list[str]:
    """Run folders, oldest first."""
    if not settings.traces_dir.exists():
        return []
    return sorted(p.name for p in settings.traces_dir.iterdir() if p.is_dir())


def load_trace(case_id: str, run_id: str | None) -> dict:
    runs = list_runs()
    if not runs:
        raise SystemExit(f"No runs found in {settings.traces_dir}. Run the agent first.")
    run_id = run_id or runs[-1]          # default: the most recent run
    path = settings.traces_dir / run_id / f"{case_id}.json"
    if not path.exists():
        raise SystemExit(f"No trace at {path}.\nRuns available: {', '.join(runs)}")
    return json.loads(path.read_text())


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + " ..."


def show(trace: dict) -> None:
    totals = trace["totals"]
    print("=" * 78)
    print(f"{trace['case_id']}   status: {trace['status']}   run: {trace['run_id']}")
    print(f"{len(trace['steps'])} steps, {totals['tool_calls']} tool calls, "
          f"{trace['latency_seconds']}s, ${totals['cost_usd']:.4f}")
    if trace["error"]:
        print(f"ERROR: {trace['error']}")
    print("=" * 78)

    for step in trace["steps"]:
        print(f"\n--- Step {step['step']}  ({step['stop_reason']}, {step['model_seconds']}s, "
              f"${step['cost_usd']:.4f})")
        for thought in step["thinking"]:
            print(f"  [thinking] {shorten(thought, 400)}")
        for text in step["text"]:
            print(f"  [says] {shorten(text, 400)}")
        for call in step["tool_calls"]:
            print(f"  [calls] {call['name']}({shorten(json.dumps(call['input']), 160)})")
        for result in step["tool_results"]:
            flag = "ERROR " if result["is_error"] else ""
            print(f"  [result] {flag}{shorten(result['text'], RESULT_PREVIEW_CHARS)}")

    for proposal in trace["proposals"]:
        print(f"\nPROPOSAL {proposal['proposal_id']}: {proposal['classification']}")
        for line in proposal.get("lines", []):
            side = f"debit {line.get('debit')}" if line.get("debit") else f"credit {line.get('credit')}"
            print(f"  {line['account']:<26} {side}")
        if not proposal.get("lines"):
            print("  (no correcting entry needed)")
        print(f"  evidence: {', '.join(proposal.get('evidence', [])) or '(none cited)'}")

    if trace["final_summary"]:
        print(f"\nFINAL SUMMARY\n{trace['final_summary']}")


def main(args: list[str]) -> None:
    if args and args[0] == "--runs":
        for run_id in list_runs():
            print(run_id)
        return
    if not args:
        raise SystemExit("Usage: python -m recon.agent.show_trace CASE-006 [run-id]")
    show(load_trace(args[0].strip().upper(), args[1] if len(args) > 1 else None))


if __name__ == "__main__":
    main(sys.argv[1:])
