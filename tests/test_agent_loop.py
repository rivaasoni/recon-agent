"""Tests for the agent loop and trace logging — WITHOUT calling the Claude API.

The trick: a FAKE Claude that follows a script. Everything else is real —
the loop code, the MCP server, the tools, the tiny warehouse, the proposals
file and the trace files. So these tests prove the plumbing works before any
money is spent, and run in under a second.

The fake has the same shape as the real SDK objects the loop uses:
    client.beta.messages.tool_runner(**kwargs) -> runner
    async for message in runner: ...
    await runner.generate_tool_call_response()
"""

import json
from types import SimpleNamespace

import pytest
from mcp import Client

from recon.agent.loop import MAX_ITERATIONS, investigate_case
from recon.mcp_server.server import server


# ---------------------------------------------------------------------------
# Building blocks for scripted Claude replies
# ---------------------------------------------------------------------------
def usage(input_tokens=1000, output_tokens=200):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_creation_input_tokens=0, cache_read_input_tokens=0)


def reply(*blocks, stop_reason):
    """One scripted Claude response."""
    return SimpleNamespace(model="claude-opus-5", stop_reason=stop_reason,
                           usage=usage(), content=list(blocks))


def thinking(text):
    return SimpleNamespace(type="thinking", thinking=text)


def say(text):
    return SimpleNamespace(type="text", text=text)


def call_tool(tool_id, name, **tool_input):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


# ---------------------------------------------------------------------------
# The fake client and runner
# ---------------------------------------------------------------------------
class FakeRunner:
    """Replays a script of replies. Tool calls are REALLY executed, through
    the same MCP tool wrappers the real runner would use."""

    def __init__(self, script, tools):
        self.script = script
        self.tools = {tool.name: tool for tool in tools}
        self.current = None

    def __aiter__(self):
        return self._replies()

    async def _replies(self):
        for item in self.script:
            if isinstance(item, Exception):
                raise item            # simulate an API failure mid-run
            self.current = item
            yield item

    async def generate_tool_call_response(self):
        calls = [b for b in self.current.content if b.type == "tool_use"]
        if not calls:
            return None
        results = []
        for call in calls:
            try:
                output = await self.tools[call.name].call(call.input)
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": output})
            except Exception as exc:   # the real SDK turns tool errors into is_error results
                results.append({"type": "tool_result", "tool_use_id": call.id,
                                "content": str(exc), "is_error": True})
        return {"role": "user", "content": results}


class FakeClient:
    """`script` is either a list of replies (same for every case), or a
    function case_id -> list of replies (a different script per case)."""

    def __init__(self, script):
        self.script = script
        self.runner_kwargs = None
        self.runs_started = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(tool_runner=self._tool_runner))

    def _tool_runner(self, **kwargs):
        self.runner_kwargs = kwargs   # so tests can check what we sent
        # "Investigate exception case CASE-001." -> "CASE-001"
        case_id = kwargs["messages"][0]["content"].split()[-1].rstrip(".")
        self.runs_started.append(case_id)
        script = self.script(case_id) if callable(self.script) else self.script
        return FakeRunner(script, kwargs["tools"])


async def run_script(script, case_id="CASE-001"):
    """Run the real loop against the fake Claude and the real (in-memory) MCP server."""
    fake = FakeClient(script)
    async with Client(server) as mcp_client:
        trace = await investigate_case(case_id, mcp_client.session, fake,
                                       run_id="run-test", verbose=False)
    return trace, fake


# A correct, balanced FX proposal for the tiny warehouse's CASE-001.
FX_PROPOSAL = dict(
    case_id="CASE-001",
    classification="fx_difference",
    explanation="Same GBP 9,400.31 on both sides; bank rate 1.3022 vs ledger 1.2800.",
    lines=[{"account": "7100 FX Gain/Loss", "debit": 208.68},
           {"account": "1000 Cash - Operating", "credit": 208.68}],
    evidence=["BNK-0055", "GL-0063", "DOC-002"],
)

HAPPY_PATH = [
    reply(thinking("Start by reading the case."),
          call_tool("t1", "get_exception_case", case_id="CASE-001"),
          stop_reason="tool_use"),
    reply(call_tool("t2", "propose_journal_entry", **FX_PROPOSAL), stop_reason="tool_use"),
    reply(say("fx_difference: bank rate 1.3022 vs ledger 1.2800. Proposed an FX loss of 208.68."),
          stop_reason="end_turn"),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_happy_path_completes_with_a_proposal(tiny_warehouse):
    trace, _ = await run_script(HAPPY_PATH)

    assert trace["status"] == "completed"
    assert len(trace["steps"]) == 3
    [proposal] = trace["proposals"]
    assert proposal["classification"] == "fx_difference"
    assert proposal["proposal_id"].startswith("PROP-")
    assert trace["final_summary"].startswith("fx_difference")


@pytest.mark.anyio
async def test_trace_records_thinking_tool_calls_and_real_results(tiny_warehouse):
    trace, _ = await run_script(HAPPY_PATH)
    first = trace["steps"][0]

    assert first["thinking"] == ["Start by reading the case."]
    assert first["tool_calls"][0]["name"] == "get_exception_case"
    # The result came from the REAL MCP server + tiny warehouse:
    assert '"reference": "BILL-5059"' in first["tool_results"][0]["text"]


@pytest.mark.anyio
async def test_trace_is_saved_as_json_with_totals(tiny_warehouse):
    trace, _ = await run_script(HAPPY_PATH)

    saved = json.loads((tiny_warehouse.traces_dir / "run-test" / "CASE-001.json").read_text())
    assert saved["status"] == "completed"
    assert saved["totals"]["tool_calls"] == 2
    assert saved["totals"]["input_tokens"] == 3000          # 3 steps x 1000
    assert saved["totals"]["cost_usd"] > 0


@pytest.mark.anyio
async def test_trace_proposal_id_matches_the_proposals_file(tiny_warehouse):
    """The trace and the proposals file must point at the same proposal —
    that link is how Phase 7 shows a reviewer the reasoning behind it."""
    trace, _ = await run_script(HAPPY_PATH)
    saved = json.loads(tiny_warehouse.proposals_path.read_text().splitlines()[0])
    assert saved["proposal_id"] == trace["proposals"][0]["proposal_id"]


@pytest.mark.anyio
async def test_finishing_without_a_proposal_is_not_success(tiny_warehouse):
    script = [
        reply(call_tool("t1", "get_exception_case", case_id="CASE-001"), stop_reason="tool_use"),
        reply(say("Looks like FX."), stop_reason="end_turn"),     # ...but never proposed
    ]
    trace, _ = await run_script(script)
    assert trace["status"] == "no_proposal"


@pytest.mark.anyio
async def test_tool_errors_are_recorded_and_the_agent_can_recover(tiny_warehouse):
    script = [
        reply(call_tool("t1", "get_exception_case", case_id="CASE-1"), stop_reason="tool_use"),
        reply(call_tool("t2", "get_exception_case", case_id="CASE-001"), stop_reason="tool_use"),
        reply(call_tool("t3", "propose_journal_entry", **FX_PROPOSAL), stop_reason="tool_use"),
        reply(say("Done."), stop_reason="end_turn"),
    ]
    trace, _ = await run_script(script)

    first_result = trace["steps"][0]["tool_results"][0]
    assert first_result["is_error"] is True
    assert "CASE-001" in first_result["text"]           # the hint reached the agent
    assert trace["totals"]["tool_errors"] == 1
    assert trace["status"] == "completed"


@pytest.mark.anyio
async def test_a_rejected_proposal_does_not_count(tiny_warehouse):
    """An unbalanced entry is refused by the server — it must not appear as
    the agent's proposal."""
    unbalanced = {**FX_PROPOSAL, "lines": [
        {"account": "7100 FX Gain/Loss", "debit": 208.68},
        {"account": "1000 Cash - Operating", "credit": 208.86},
    ]}
    script = [
        reply(call_tool("t1", "propose_journal_entry", **unbalanced), stop_reason="tool_use"),
        reply(say("Proposed."), stop_reason="end_turn"),
    ]
    trace, _ = await run_script(script)
    assert trace["proposals"] == []
    assert trace["status"] == "no_proposal"


@pytest.mark.anyio
async def test_api_failure_mid_run_still_writes_a_trace(tiny_warehouse):
    """The trace of a failed run is often the most useful one."""
    script = [
        reply(call_tool("t1", "get_exception_case", case_id="CASE-001"), stop_reason="tool_use"),
        ConnectionError("network dropped"),
    ]
    trace, _ = await run_script(script)

    assert trace["status"] == "error"
    assert "network dropped" in trace["error"]
    assert len(trace["steps"]) == 1                     # the work before the failure is kept
    assert (tiny_warehouse.traces_dir / "run-test" / "CASE-001.json").exists()


@pytest.mark.anyio
async def test_still_calling_tools_when_the_loop_ends_means_the_cap_was_hit(tiny_warehouse):
    script = [reply(call_tool(f"t{i}", "get_exception_case", case_id="CASE-001"),
                    stop_reason="tool_use") for i in range(3)]
    trace, _ = await run_script(script)
    assert trace["status"] == "hit_iteration_cap"


@pytest.mark.anyio
async def test_runner_is_given_the_safety_settings(tiny_warehouse):
    """Check what we actually SEND to the API, not just what the code says."""
    _, fake = await run_script(HAPPY_PATH)
    kwargs = fake.runner_kwargs

    assert kwargs["max_iterations"] == MAX_ITERATIONS
    assert kwargs["thinking"]["type"] == "adaptive"
    assert "budget_tokens" not in kwargs["thinking"]        # rejected by this model
    assert "never say or imply that anything has been posted" in kwargs["system"]
    assert {t.name for t in kwargs["tools"]} >= {"get_exception_case", "propose_journal_entry"}


# ---------------------------------------------------------------------------
# Batch runs (run_all.run_cases)
# ---------------------------------------------------------------------------
from recon.agent.run_all import list_case_ids, load_previous_rows, run_cases  # noqa: E402


def good_script(case_id):
    """Investigate, propose 'no entry needed', summarise — for any case."""
    return [
        reply(call_tool("t1", "get_exception_case", case_id=case_id), stop_reason="tool_use"),
        reply(call_tool("t2", "propose_journal_entry", case_id=case_id,
                        classification="timing_difference",
                        explanation="Scripted test proposal: no entry needed for this case.",
                        lines=[]), stop_reason="tool_use"),
        reply(say("Done."), stop_reason="end_turn"),
    ]


async def run_batch(script, case_ids=None, max_cost_usd=10.0):
    fake = FakeClient(script)
    async with Client(server) as mcp_client:
        ids = case_ids or await list_case_ids(mcp_client.session)
        summary = await run_cases(ids, mcp_client.session, fake, "run-batch", max_cost_usd,
                                  retry_sleep_seconds=0)
    return summary, fake


@pytest.mark.anyio
async def test_batch_runs_every_case_and_saves_a_summary(tiny_warehouse):
    summary, fake = await run_batch(good_script)

    assert fake.runs_started == ["CASE-001", "CASE-002", "CASE-003"]
    assert summary["totals"]["completed"] == 3
    assert all(row["proposal_id"] for row in summary["cases"])

    folder = tiny_warehouse.traces_dir / "run-batch"
    assert {p.name for p in folder.iterdir()} == {
        "CASE-001.json", "CASE-002.json", "CASE-003.json", "_summary.json"}


@pytest.mark.anyio
async def test_one_failing_case_does_not_stop_the_others(tiny_warehouse):
    """Error isolation: CASE-002 blows up; CASE-001 and CASE-003 still complete."""
    def script(case_id):
        if case_id == "CASE-002":
            return [ConnectionError("API unavailable")]
        return good_script(case_id)

    summary, _ = await run_batch(script)
    statuses = {row["case_id"]: row["status"] for row in summary["cases"]}
    assert statuses == {"CASE-001": "completed", "CASE-002": "error", "CASE-003": "completed"}
    assert summary["totals"]["status_counts"] == {"completed": 2, "error": 1}


@pytest.mark.anyio
async def test_budget_cap_stops_new_cases_but_never_abandons_one_midway(tiny_warehouse):
    """Each scripted step costs $0.01 (1000 in + 200 out on Opus 5); a case
    is 3 steps = $0.03. With a $0.02 cap, the FIRST case runs to completion,
    and the other two are never started."""
    summary, fake = await run_batch(good_script, max_cost_usd=0.02)

    assert fake.runs_started == ["CASE-001"]
    statuses = [row["status"] for row in summary["cases"]]
    assert statuses == ["completed", "skipped_budget", "skipped_budget"]
    assert summary["totals"]["cost_usd"] == pytest.approx(0.03)


@pytest.mark.anyio
async def test_can_run_a_chosen_subset_of_cases(tiny_warehouse):
    summary, fake = await run_batch(good_script, case_ids=["CASE-003"])
    assert fake.runs_started == ["CASE-003"]
    assert [row["case_id"] for row in summary["cases"]] == ["CASE-003"]


@pytest.mark.anyio
async def test_a_case_that_fails_once_is_retried_and_succeeds(tiny_warehouse):
    """Network blips are common on long runs, and a failed case costs nothing
    (no steps completed), so retrying is cheap."""
    attempts = {"CASE-001": 0}

    def script(case_id):
        attempts[case_id] = attempts.get(case_id, 0) + 1
        if case_id == "CASE-001" and attempts[case_id] == 1:
            return [ConnectionError("Connection error.")]
        return good_script(case_id)

    fake = FakeClient(script)
    async with Client(server) as mcp_client:
        summary = await run_cases(["CASE-001"], mcp_client.session, fake, "run-retry",
                                  retries=1, retry_sleep_seconds=0)

    [row] = summary["cases"]
    assert row["status"] == "completed"
    assert row["attempts"] == 2


@pytest.mark.anyio
async def test_retries_give_up_after_the_limit(tiny_warehouse):
    fake = FakeClient(lambda case_id: [ConnectionError("Connection error.")])
    async with Client(server) as mcp_client:
        summary = await run_cases(["CASE-001"], mcp_client.session, fake, "run-retry",
                                  retries=2, retry_sleep_seconds=0)

    [row] = summary["cases"]
    assert row["status"] == "error"
    assert row["attempts"] == 3          # 1 try + 2 retries


@pytest.mark.anyio
async def test_resume_only_reruns_unfinished_cases_and_keeps_the_rest(tiny_warehouse):
    """The core of --resume: cases already paid for are never run twice."""
    # First attempt: CASE-002 fails.
    def flaky(case_id):
        return [ConnectionError("Connection error.")] if case_id == "CASE-002" else good_script(case_id)

    first, _ = await run_batch(flaky)
    assert first["totals"]["status_counts"] == {"completed": 2, "error": 1}

    # Resume: only the unfinished case should run this time.
    previous = load_previous_rows("run-batch")
    unfinished = [cid for cid, row in previous.items() if row["status"] != "completed"]
    assert unfinished == ["CASE-002"]

    fake = FakeClient(good_script)
    async with Client(server) as mcp_client:
        summary = await run_cases(unfinished, mcp_client.session, fake, "run-batch",
                                  previous_rows=previous)

    assert fake.runs_started == ["CASE-002"]                       # only the failed one
    assert [row["case_id"] for row in summary["cases"]] == ["CASE-001", "CASE-002", "CASE-003"]
    assert summary["totals"]["completed"] == 3
    # Run total counts every case; "this attempt" counts only what we just ran.
    assert summary["totals"]["cost_usd"] > summary["totals"]["cost_usd_this_attempt"]


# ---------------------------------------------------------------------------
# The trace viewer
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_show_trace_renders_a_saved_trace(tiny_warehouse, capsys, monkeypatch):
    """Reads a real saved trace and prints the parts a reviewer needs."""
    from recon.agent import show_trace
    monkeypatch.setattr(show_trace, "settings", tiny_warehouse)

    await run_script(HAPPY_PATH)                      # writes run-test/CASE-001.json
    assert show_trace.list_runs() == ["run-test"]

    show_trace.show(show_trace.load_trace("CASE-001", None))
    printed = capsys.readouterr().out

    assert "CASE-001   status: completed" in printed
    assert "get_exception_case" in printed            # the tool calls
    assert "7100 FX Gain/Loss" in printed             # the proposed entry
    assert "evidence: BNK-0055, GL-0063, DOC-002" in printed
