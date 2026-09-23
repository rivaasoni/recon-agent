"""
The agent loop with trace logging — Phase 6.

investigate_case() lets Claude work ONE exception case using our MCP tools,
and records every step in a TRACE: what Claude said and (a summary of) what
it thought, which tools it called with which arguments, what came back, plus
tokens, cost and timing.

The trace is written to disk even if the run fails part-way — a trace of a
failure is often the most useful one.

The loop, in plain words:
    1. Send Claude: system prompt + "investigate CASE-006" + our tool list
    2. Claude replies with text and/or tool calls
    3. The Tool Runner runs the tool calls (via MCP) and sends results back -> 2
    4. Stop when Claude makes no more tool calls, or at MAX_ITERATIONS
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from anthropic.lib.tools.mcp import async_mcp_tool
from mcp import ClientSession

from recon.agent.costs import cost_usd
from recon.agent.prompts import SYSTEM_PROMPT
from recon.config import settings

# Safety cap on loop steps. A case normally needs well under 10.
MAX_ITERATIONS = 15

# How much of each tool result to PRINT. (The trace keeps the full text.)
PREVIEW_CHARS = 300

PROPOSAL_TOOL = "propose_journal_entry"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    """A folder name for one run, e.g. 'run-20260921-211530'. Sorts by time."""
    return datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")


def preview(text: str) -> str:
    """Shorten long text for the terminal, on one line."""
    text = " ".join(text.split())
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + " ..."


def result_text(content: Any) -> str:
    """The text of one tool result, whatever shape the SDK gave it.

    Reading the SDK source showed `content` can be a plain string (e.g.
    "Error: Tool 'x' not found") OR a list of content blocks — so handle both
    rather than assume one and crash mid-run.
    """
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict):
            parts.append(block.get("text", ""))
        else:
            parts.append(getattr(block, "text", ""))
    return "".join(parts)


def empty_totals() -> dict:
    return {
        "input_tokens": 0, "output_tokens": 0,
        "cache_write_tokens": 0, "cache_read_tokens": 0,
        "cost_usd": 0.0, "tool_calls": 0, "tool_errors": 0,
    }


# ---------------------------------------------------------------------------
# Recording one step
# ---------------------------------------------------------------------------
def record_step(step_number: int, message: Any, model_seconds: float) -> dict:
    """Turn one Claude response into a trace step (tool results added later)."""
    usage = message.usage
    cache_write = usage.cache_creation_input_tokens or 0
    cache_read = usage.cache_read_input_tokens or 0

    step = {
        "step": step_number,
        # The model that ACTUALLY answered (differs from the one requested only
        # if a server-side fallback kicked in).
        "model": message.model,
        "stop_reason": message.stop_reason,
        "model_seconds": round(model_seconds, 2),
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_write_tokens": cache_write,
            "cache_read_tokens": cache_read,
        },
        "cost_usd": cost_usd(message.model, usage.input_tokens, usage.output_tokens,
                             cache_write_tokens=cache_write, cache_read_tokens=cache_read),
        "thinking": [],      # readable summaries of Claude's reasoning
        "text": [],          # what Claude said
        "tool_calls": [],    # what Claude asked to run
        "tool_results": [],  # what came back
        "tool_seconds": 0.0,
    }
    for block in message.content:
        if block.type == "thinking" and block.thinking:
            step["thinking"].append(block.thinking)
        elif block.type == "text" and block.text.strip():
            step["text"].append(block.text.strip())
        elif block.type == "tool_use":
            step["tool_calls"].append({"id": block.id, "name": block.name, "input": block.input})
    return step


def print_step(step: dict) -> None:
    print(f"\n=== Step {step['step']}  ({step['model']}, stop_reason={step['stop_reason']}, "
          f"${step['cost_usd']:.4f}, {step['model_seconds']}s)")
    for thought in step["thinking"]:
        print(f"THINKS: {preview(thought)}")
    for text in step["text"]:
        print(f"CLAUDE: {text}")
    for call in step["tool_calls"]:
        print(f"CALLS:  {call['name']}({json.dumps(call['input'])})")
    for result in step["tool_results"]:
        flag = "ERROR " if result["is_error"] else ""
        print(f"RESULT: {flag}{preview(result['text'])}")


# ---------------------------------------------------------------------------
# Finding the proposal in the trace
# ---------------------------------------------------------------------------
def extract_proposals(steps: list[dict]) -> list[dict]:
    """Every SUCCESSFUL propose_journal_entry call: what the agent proposed,
    plus the proposal_id the server gave back."""
    proposals = []
    for step in steps:
        results_by_id = {r["tool_use_id"]: r for r in step["tool_results"]}
        for call in step["tool_calls"]:
            result = results_by_id.get(call["id"])
            if call["name"] != PROPOSAL_TOOL or result is None or result["is_error"]:
                continue
            try:
                proposal_id = json.loads(result["text"]).get("proposal_id")
            except json.JSONDecodeError:
                proposal_id = None
            proposals.append({"proposal_id": proposal_id, **call["input"]})
    return proposals


def decide_status(trace: dict) -> str:
    """One word summarising how the run ended. Checked in this order."""
    if trace["error"]:
        return "error"
    last_stop = trace["steps"][-1]["stop_reason"] if trace["steps"] else None
    if last_stop == "refusal":
        return "refused"
    if last_stop == "tool_use":
        # Claude still wanted tools when the loop ended -> the cap stopped it.
        return "hit_iteration_cap"
    if not trace["proposals"]:
        # "Finished" without proposing anything is a failure, not a success.
        return "no_proposal"
    return "completed"


def write_trace(trace: dict, run_id: str) -> None:
    folder = settings.traces_dir / run_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{trace['case_id']}.json"
    path.write_text(json.dumps(trace, indent=2, default=str))
    trace["trace_path"] = str(path)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
async def investigate_case(
    case_id: str,
    session: ClientSession,
    client: Any,
    run_id: str,
    verbose: bool = True,
) -> dict:
    """Let the agent work one case. Returns the trace (also saved to disk).

    `client` is an AsyncAnthropic client — or, in tests, a fake with the same
    shape, so the whole loop can be tested without calling the API.
    """
    trace = {
        "case_id": case_id,
        "run_id": run_id,
        "model_requested": settings.model,
        "started_at": now_iso(),
        "finished_at": None,
        "latency_seconds": None,
        "status": None,
        "error": None,
        "steps": [],
        "proposals": [],
        "final_summary": None,
        "totals": empty_totals(),
    }
    started = time.perf_counter()

    try:
        # Our MCP tools, wrapped so the Tool Runner can call them via `session`.
        mcp_tools = (await session.list_tools()).tools
        tools = [async_mcp_tool(tool, session) for tool in mcp_tools]

        runner = client.beta.messages.tool_runner(
            model=settings.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Investigate exception case {case_id}."}],
            tools=tools,
            max_iterations=MAX_ITERATIONS,
            # Claude decides how much to think. "summarized" returns a readable
            # summary of that reasoning for the trace (the default on this
            # model returns thinking blocks with empty text).
            thinking={"type": "adaptive", "display": "summarized"},
            # Cache the unchanging start of each request (tools + system).
            cache_control={"type": "ephemeral"},
            # Retry on a fallback model if a request is ever declined.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

        mark = time.perf_counter()
        async for message in runner:
            # Time since the last mark = waiting for Claude's reply.
            step = record_step(len(trace["steps"]) + 1, message, time.perf_counter() - mark)
            trace["steps"].append(step)

            # The tool results the runner will send back. (Tools run once;
            # the runner reuses this same result.)
            tool_started = time.perf_counter()
            tool_response = await runner.generate_tool_call_response()
            step["tool_seconds"] = round(time.perf_counter() - tool_started, 2)
            if tool_response is not None:
                for result in tool_response["content"]:
                    step["tool_results"].append({
                        "tool_use_id": result["tool_use_id"],
                        "is_error": bool(result.get("is_error")),
                        "text": result_text(result["content"]),
                    })

            if verbose:
                print_step(step)
            if message.stop_reason == "refusal":
                break
            mark = time.perf_counter()

    except Exception as exc:  # record ANY failure in the trace, then carry on
        trace["error"] = f"{type(exc).__name__}: {exc}"
        if verbose:
            print(f"\nERROR: {trace['error']}")

    finally:
        # Always finish and save the trace — even after an error.
        trace["finished_at"] = now_iso()
        trace["latency_seconds"] = round(time.perf_counter() - started, 2)
        trace["proposals"] = extract_proposals(trace["steps"])
        final_texts = [t for s in trace["steps"] for t in s["text"]]
        trace["final_summary"] = final_texts[-1] if final_texts else None

        totals = trace["totals"]
        for step in trace["steps"]:
            for key in ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens"):
                totals[key] += step["usage"][key]
            totals["cost_usd"] += step["cost_usd"]
            totals["tool_calls"] += len(step["tool_calls"])
            totals["tool_errors"] += sum(r["is_error"] for r in step["tool_results"])
        totals["cost_usd"] = round(totals["cost_usd"], 6)

        trace["status"] = decide_status(trace)
        write_trace(trace, run_id)

    return trace
