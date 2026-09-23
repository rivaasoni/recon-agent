"""
Run the agent on ONE exception case, printing each step and saving a trace.

This COSTS MONEY (roughly $0.10-$0.40 per case on Opus 5).

Run it:
    python -m recon.agent.run_case CASE-006

The loop itself lives in recon/agent/loop.py.
"""

from __future__ import annotations

import sys

import anyio
from anthropic import AsyncAnthropic
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from recon.agent.loop import investigate_case, new_run_id
from recon.config import settings
from recon.mcp_server.launch import SERVER


async def main(case_id: str) -> None:
    # Checked FIRST, so a missing key stops us before anything else starts.
    client = AsyncAnthropic(api_key=settings.anthropic_api_key())

    # Start our MCP server as a subprocess and open a session to it.
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            trace = await investigate_case(case_id.strip().upper(), session, client, new_run_id())

    totals = trace["totals"]
    print(f"\nStatus:  {trace['status']}")
    print(f"Steps:   {len(trace['steps'])}   tool calls: {totals['tool_calls']}   "
          f"time: {trace['latency_seconds']}s")
    # With prompt caching, almost all input shows up as cache WRITES (first
    # time) or cache READS (every step after) — so show all three.
    print(f"Input:   {totals['input_tokens']} uncached + {totals['cache_write_tokens']} written to cache "
          f"+ {totals['cache_read_tokens']} read from cache")
    print(f"Output:  {totals['output_tokens']} (includes thinking)")
    print(f"Cost:    ${totals['cost_usd']:.4f}")
    for proposal in trace["proposals"]:
        print(f"Proposal {proposal['proposal_id']}: {proposal['classification']}")
    print(f"Trace:   {trace['trace_path']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m recon.agent.run_case CASE-006")
    anyio.run(main, sys.argv[1])
