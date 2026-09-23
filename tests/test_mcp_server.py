"""Tests for the Phase 5 MCP server.

We talk to the server exactly the way a real agent would — through an MCP
Client — but in-memory (`Client(server)`), so there's no subprocess and the
tests run in milliseconds.

The warehouse here is a TINY hand-built DuckDB file (see `tiny_warehouse`),
not the real pipeline output. We know every value in it, so we know exactly
what each tool should return.

Async tests: MCP clients are async (they `await` replies). The
@pytest.mark.anyio marker lets pytest run an `async def` test.
"""

import json

import duckdb
import pytest
from mcp import Client

from recon.mcp_server.server import server


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# The tiny_warehouse fixture lives in tests/conftest.py (shared with the agent tests).


async def call(tool: str, **arguments):
    """Call one tool through a real MCP client; return the raw result."""
    async with Client(server) as client:
        return await client.call_tool(tool, arguments)


def as_json(result) -> dict:
    """A successful tool result carries its JSON in the first text block."""
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


# ---------------------------------------------------------------------------
# What the agent SEES: tool definitions
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tool_is_listed_with_description_and_parameter_help():
    """The agent only knows what the tool list tells it. Check that the
    description and the parameter description actually reach it."""
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    tool = tools["get_exception_case"]
    assert "does not say what kind of exception" in tool.description.lower()
    assert "CASE-003" in tool.input_schema["properties"]["case_id"]["description"]
    assert tool.input_schema["required"] == ["case_id"]


# The COMPLETE list of tools the agent may have. Adding a tool to the server
# fails this test until someone deliberately adds it here — so a tool that
# writes to the ledger can't slip in unnoticed.
READ_ONLY_TOOLS = {
    "get_exception_case",
    "list_exception_cases",
    "get_bank_transaction",
    "get_ledger_entry",
    "find_transactions_by_reference",
    "get_documents_for_reference",
    "search_documents",
}
PROPOSAL_TOOLS = {"propose_journal_entry"}


@pytest.mark.anyio
async def test_server_offers_exactly_the_expected_tools():
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == READ_ONLY_TOOLS | PROPOSAL_TOOLS


@pytest.mark.anyio
async def test_tool_annotations_are_honest():
    """Lookup tools: read-only. The proposal tool: records something (so NOT
    read-only), but never destroys or changes anything."""
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    for name in READ_ONLY_TOOLS:
        assert tools[name].annotations.read_only_hint is True, f"{name} is not read-only"
    for name in PROPOSAL_TOOLS:
        assert tools[name].annotations.read_only_hint is False
        assert tools[name].annotations.destructive_hint is False


# ---------------------------------------------------------------------------
# get_exception_case
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_get_exception_case_returns_the_case(tiny_warehouse):
    case = as_json(await call("get_exception_case", case_id="CASE-001"))

    assert case["case_shape"] == "both_sides"
    assert case["reference"] == "BILL-5059"
    assert case["amount_difference"] == -208.68     # Decimal arrived as a number
    assert case["case_date"] == "2026-08-12"         # date arrived as ISO text


@pytest.mark.anyio
async def test_one_sided_case_has_nulls_for_the_missing_side(tiny_warehouse):
    case = as_json(await call("get_exception_case", case_id="CASE-002"))
    assert case["case_shape"] == "bank_only"
    assert case["gl_entry_id"] is None


@pytest.mark.anyio
async def test_case_id_formatting_is_forgiven(tiny_warehouse):
    """Models sometimes add spaces or use lower case. Don't punish that."""
    case = as_json(await call("get_exception_case", case_id="  case-001 "))
    assert case["case_id"] == "CASE-001"


@pytest.mark.anyio
async def test_unknown_case_is_a_helpful_error_not_a_crash(tiny_warehouse):
    """The agent should get a message it can act on, and the server must
    keep running."""
    result = await call("get_exception_case", case_id="CASE-999")

    assert result.is_error
    message = result.content[0].text
    assert "CASE-999" in message
    assert "CASE-001" in message       # shows the expected format


@pytest.mark.anyio
async def test_missing_argument_is_rejected_before_our_code_runs(tiny_warehouse):
    """The library validates arguments against the type hints for us."""
    result = await call("get_exception_case")
    assert result.is_error
    assert "case_id" in result.content[0].text


# ---------------------------------------------------------------------------
# list_exception_cases
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_list_all_cases(tiny_warehouse):
    result = as_json(await call("list_exception_cases"))
    assert result["count"] == 3
    assert [c["case_id"] for c in result["cases"]] == ["CASE-001", "CASE-002", "CASE-003"]


@pytest.mark.anyio
async def test_list_cases_filtered_by_shape(tiny_warehouse):
    result = as_json(await call("list_exception_cases", case_shape="ledger_only"))
    assert [c["case_id"] for c in result["cases"]] == ["CASE-003"]


@pytest.mark.anyio
async def test_invalid_shape_is_rejected(tiny_warehouse):
    """Literal[...] in the type hint becomes an allowed-values list in the
    tool schema, and anything else is rejected before our code runs."""
    result = await call("list_exception_cases", case_shape="sideways")
    assert result.is_error


# ---------------------------------------------------------------------------
# get_bank_transaction / get_ledger_entry — including match status
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_matched_bank_row_shows_its_partner(tiny_warehouse):
    row = as_json(await call("get_bank_transaction", bank_txn_id="BNK-0036"))
    assert row["match_status"] == "matched"
    assert row["matched_to_gl_entry_id"] == "GL-0042"
    assert row["exception_case_id"] is None


@pytest.mark.anyio
async def test_exception_bank_row_shows_its_case(tiny_warehouse):
    row = as_json(await call("get_bank_transaction", bank_txn_id="bnk-0125"))
    assert row["match_status"] == "exception"
    assert row["exception_case_id"] == "CASE-002"
    assert row["reference"] is None          # bank fees have no reference


@pytest.mark.anyio
async def test_ledger_row_exposes_currency_details(tiny_warehouse):
    row = as_json(await call("get_ledger_entry", gl_entry_id="GL-0063"))
    assert row["currency"] == "GBP"
    assert row["foreign_amount"] == 9400.31
    assert row["fx_rate"] == 1.28


@pytest.mark.anyio
async def test_internal_columns_are_not_exposed(tiny_warehouse):
    """Tool outputs are a fixed contract — no lineage/internal columns."""
    row = as_json(await call("get_ledger_entry", gl_entry_id="GL-0042"))
    assert not [key for key in row if key.startswith("_")]


@pytest.mark.anyio
@pytest.mark.parametrize("tool, arg, bad_id", [
    ("get_bank_transaction", "bank_txn_id", "BNK-9999"),
    ("get_ledger_entry", "gl_entry_id", "GL-9999"),
])
async def test_unknown_ids_are_helpful_errors(tiny_warehouse, tool, arg, bad_id):
    result = await call(tool, **{arg: bad_id})
    assert result.is_error
    assert bad_id in result.content[0].text
    assert "look like" in result.content[0].text


# ---------------------------------------------------------------------------
# find_transactions_by_reference
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_reference_search_reveals_the_duplicate_story(tiny_warehouse):
    """One bank line, two ledger entries: one matched, one left over.
    That is exactly the evidence a duplicate posting needs."""
    result = as_json(await call("find_transactions_by_reference", reference="BILL-5051"))

    assert result["bank_transaction_count"] == 1
    assert result["ledger_entry_count"] == 2
    statuses = {e["gl_entry_id"]: e["match_status"] for e in result["ledger_entries"]}
    assert statuses == {"GL-0042": "matched", "GL-0047": "exception"}


@pytest.mark.anyio
async def test_unknown_reference_is_empty_not_an_error(tiny_warehouse):
    """'Nothing carries this reference' is a FACT the agent can use."""
    result = as_json(await call("find_transactions_by_reference", reference="INV-0000"))
    assert result["bank_transaction_count"] == 0
    assert result["ledger_entry_count"] == 0


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_sql_injection_attempt_is_just_an_unknown_id(tiny_warehouse):
    """With `?` placeholders the whole string is treated as a VALUE, never
    as SQL. The 'attack' finds nothing — and the table is untouched."""
    attack = "BNK-0036'; drop table cleaned.bank_transactions; --"
    result = await call("get_bank_transaction", bank_txn_id=attack)
    assert result.is_error

    with duckdb.connect(str(tiny_warehouse.duckdb_path), read_only=True) as con:
        assert con.execute("select count(*) from cleaned.bank_transactions").fetchone()[0] == 3


# ---------------------------------------------------------------------------
# Document tools
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_documents_for_reference_finds_all_paperwork(tiny_warehouse):
    result = as_json(await call("get_documents_for_reference", reference="bill-5059"))
    assert result["count"] == 2
    assert {d["doc_type"] for d in result["documents"]} == {"wire_confirmation", "vendor_bill"}


@pytest.mark.anyio
async def test_no_documents_is_an_empty_list(tiny_warehouse):
    result = as_json(await call("get_documents_for_reference", reference="INV-9999"))
    assert result["count"] == 0


@pytest.mark.anyio
async def test_keyword_search_finds_the_fee_schedule(tiny_warehouse):
    """The fee schedule has no reference — keyword search is the only way in."""
    result = as_json(await call("search_documents", keywords="Service CHARGE"))
    assert [d["doc_id"] for d in result["documents"]] == ["DOC-001"]


@pytest.mark.anyio
async def test_keyword_search_requires_all_words(tiny_warehouse):
    """'wire' alone matches one doc; 'wire 1.3022' must match only docs with both."""
    both = as_json(await call("search_documents", keywords="wire 1.3022"))
    assert [d["doc_id"] for d in both["documents"]] == ["DOC-002"]

    neither = as_json(await call("search_documents", keywords="wire 9,400.31"))
    assert neither["count"] == 0


@pytest.mark.anyio
async def test_percent_sign_is_not_a_wildcard(tiny_warehouse):
    """With LIKE, '%' would match everything. contains() takes it literally."""
    result = as_json(await call("search_documents", keywords="%"))
    assert result["count"] == 0


@pytest.mark.anyio
async def test_empty_keywords_are_a_helpful_error(tiny_warehouse):
    result = await call("search_documents", keywords="   ")
    assert result.is_error
    assert "at least one keyword" in result.content[0].text


@pytest.mark.anyio
async def test_injection_text_comes_back_as_plain_data(tiny_warehouse):
    """A document may contain instruction-like text. The tool's job is to
    return it faithfully as data — deciding it's not a real instruction is
    the agent's job, which is why the warning below must reach the agent."""
    result = as_json(await call("get_documents_for_reference", reference="INV-1001"))
    assert "ignore previous instructions" in result["documents"][0]["content"]


@pytest.mark.anyio
async def test_untrusted_text_warning_reaches_the_agent():
    """Checks what the agent RECEIVES, not what the source looks like.
    (An earlier version edited __doc__ after registration — the code looked
    right, but the warning never reached the agent. This test catches that.)"""
    from recon.mcp_server.server import UNTRUSTED_TEXT_WARNING

    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    for name in ("get_documents_for_reference", "search_documents"):
        description = " ".join(tools[name].description.split())   # normalise whitespace
        assert UNTRUSTED_TEXT_WARNING in description, f"{name} is missing the warning"


# ---------------------------------------------------------------------------
# propose_journal_entry
# ---------------------------------------------------------------------------
# A correct proposal for the tiny warehouse's FX case (CASE-001): the bank
# paid 208.68 more than the ledger recorded, so book an FX loss.
FX_LINES = [
    {"account": "7100 FX Gain/Loss", "debit": 208.68, "memo": "FX loss on BILL-5059"},
    {"account": "1000 Cash - Operating", "credit": 208.68},
]
FX_EXPLANATION = "Same GBP amount on both sides; the bank converted at 1.3022 vs 1.2800 booked."


def read_proposals(settings) -> list[dict]:
    path = settings.proposals_path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.anyio
async def test_valid_proposal_is_recorded_as_pending(tiny_warehouse):
    result = as_json(await call(
        "propose_journal_entry",
        case_id="CASE-001", classification="fx_difference",
        explanation=FX_EXPLANATION, lines=FX_LINES, evidence=["BNK-0055", "DOC-002"],
    ))

    assert result["status"] == "pending_human_approval"
    assert "Nothing has been posted" in result["message"]

    [saved] = read_proposals(tiny_warehouse)          # exactly one proposal
    assert saved["proposal_id"] == result["proposal_id"]
    assert saved["classification"] == "fx_difference"
    assert saved["total"] == "208.68"                  # money stored exactly, as text
    assert saved["lines"][0]["debit"] == "208.68"
    assert saved["evidence"] == ["BNK-0055", "DOC-002"]


@pytest.mark.anyio
async def test_no_entry_needed_is_an_empty_list(tiny_warehouse):
    """E.g. a timing difference: the right fix is to wait. Still recorded,
    so a human sees the reasoning and signs off on it."""
    result = as_json(await call(
        "propose_journal_entry",
        case_id="CASE-003", classification="timing_difference",
        explanation="Booked at month end; the payment should clear the bank next month.",
        lines=[],
    ))
    assert result["status"] == "pending_human_approval"
    assert read_proposals(tiny_warehouse)[0]["lines"] == []


@pytest.mark.anyio
async def test_unbalanced_entry_is_rejected_and_nothing_saved(tiny_warehouse):
    result = await call(
        "propose_journal_entry",
        case_id="CASE-001", classification="fx_difference", explanation=FX_EXPLANATION,
        lines=[
            {"account": "7100 FX Gain/Loss", "debit": 208.68},
            {"account": "1000 Cash - Operating", "credit": 208.86},   # transposed digits!
        ],
    )
    assert result.is_error
    message = result.content[0].text
    assert "does not balance" in message and "208.68" in message and "208.86" in message
    assert read_proposals(tiny_warehouse) == []


@pytest.mark.anyio
async def test_float_trap_does_not_break_balancing(tiny_warehouse):
    """In float maths 0.10 + 0.20 != 0.30. With Decimal it balances exactly."""
    result = await call(
        "propose_journal_entry",
        case_id="CASE-002", classification="bank_fee",
        explanation="Split fee test: two small debits against one credit.",
        lines=[
            {"account": "6100 Bank Fees", "debit": 0.10},
            {"account": "6100 Bank Fees", "debit": 0.20},
            {"account": "1000 Cash - Operating", "credit": 0.30},
        ],
    )
    assert not result.is_error, result.content[0].text


@pytest.mark.anyio
@pytest.mark.parametrize("bad_lines, expected_text", [
    ([{"account": "6100 Bank Fees", "debit": 45, "credit": 45},
      {"account": "1000 Cash - Operating", "credit": 45}], "not both"),
    ([{"account": "6100 Bank Fees"},
      {"account": "1000 Cash - Operating", "credit": 45}], "not both and not neither"),
    ([{"account": "6100 Bank Fees", "debit": 45}], "at least two lines"),
])
async def test_malformed_lines_get_specific_errors(tiny_warehouse, bad_lines, expected_text):
    result = await call(
        "propose_journal_entry",
        case_id="CASE-002", classification="bank_fee",
        explanation="Monthly service charge per the fee schedule.", lines=bad_lines,
    )
    assert result.is_error
    assert expected_text in result.content[0].text
    assert read_proposals(tiny_warehouse) == []


@pytest.mark.anyio
@pytest.mark.parametrize("bad_line", [
    {"account": "9999 Made Up Account", "debit": 45},    # not in the chart of accounts
    {"account": "6100 Bank Fees", "debit": 45.001},      # fractions of a cent
    {"account": "6100 Bank Fees", "debit": -45},         # negative amount
])
async def test_schema_rejects_bad_values_before_our_code_runs(tiny_warehouse, bad_line):
    result = await call(
        "propose_journal_entry",
        case_id="CASE-002", classification="bank_fee",
        explanation="Monthly service charge per the fee schedule.",
        lines=[bad_line, {"account": "1000 Cash - Operating", "credit": 45}],
    )
    assert result.is_error
    assert read_proposals(tiny_warehouse) == []


@pytest.mark.anyio
async def test_unknown_case_is_rejected(tiny_warehouse):
    result = await call(
        "propose_journal_entry",
        case_id="CASE-999", classification="bank_fee",
        explanation="Monthly service charge per the fee schedule.", lines=[],
    )
    assert result.is_error
    assert "CASE-999" in result.content[0].text


@pytest.mark.anyio
async def test_proposing_never_changes_the_warehouse(tiny_warehouse):
    """The core promise: the agent never writes. Compare the warehouse file
    byte-for-byte before and after a proposal."""
    before = tiny_warehouse.duckdb_path.read_bytes()
    as_json(await call(
        "propose_journal_entry",
        case_id="CASE-001", classification="fx_difference",
        explanation=FX_EXPLANATION, lines=FX_LINES,
    ))
    assert tiny_warehouse.duckdb_path.read_bytes() == before


@pytest.mark.anyio
async def test_proposals_are_appended_not_overwritten(tiny_warehouse):
    for _ in range(2):
        as_json(await call(
            "propose_journal_entry",
            case_id="CASE-001", classification="fx_difference",
            explanation=FX_EXPLANATION, lines=FX_LINES,
        ))
    proposals = read_proposals(tiny_warehouse)
    assert len(proposals) == 2
    assert proposals[0]["proposal_id"] != proposals[1]["proposal_id"]


@pytest.mark.anyio
async def test_money_is_always_stored_with_two_decimals(tiny_warehouse):
    """45 must be saved as '45.00', not '45' — one consistent money format."""
    as_json(await call(
        "propose_journal_entry",
        case_id="CASE-002", classification="bank_fee",
        explanation="Monthly service charge per the fee schedule.",
        lines=[{"account": "6100 Bank Fees", "debit": 45},
               {"account": "1000 Cash - Operating", "credit": 45}],
    ))
    [saved] = read_proposals(tiny_warehouse)
    assert saved["total"] == "45.00"
    assert saved["lines"][0] == {"account": "6100 Bank Fees", "debit": "45.00", "credit": "0.00", "memo": ""}
