"""
Call one MCP tool from the terminal — handy for trying tools by hand.

It connects to the server exactly the way an agent would (through an MCP
Client, in-memory) and prints what the agent would see.

Usage:
    python -m recon.mcp_server.call_tool                      # list the tools
    python -m recon.mcp_server.call_tool get_exception_case case_id=CASE-005

List/object arguments are passed as JSON, in single quotes:
    python -m recon.mcp_server.call_tool propose_journal_entry case_id=CASE-014 \\
        classification=bank_fee "explanation=Monthly service charge per the fee schedule." \\
        'lines=[{"account": "6100 Bank Fees", "debit": 45}, {"account": "1000 Cash - Operating", "credit": 45}]'
"""

from __future__ import annotations

import json
import sys

import anyio
from mcp import Client

from recon.mcp_server.server import server


async def main(args: list[str]) -> None:
    async with Client(server) as client:
        if not args:
            for tool in (await client.list_tools()).tools:
                first_line = (tool.description or "").strip().splitlines()[0]
                print(f"{tool.name:<28} {first_line}")
            return

        tool_name, *pairs = args
        # "case_id=CASE-005" -> {"case_id": "CASE-005"}
        arguments = dict(pair.split("=", 1) for pair in pairs)
        # Values that look like JSON lists/objects ('[...]', '{...}') are
        # parsed, so list arguments like `lines` can be passed too.
        for key, value in arguments.items():
            if value.strip().startswith(("[", "{")):
                arguments[key] = json.loads(value)
        result = await client.call_tool(tool_name, arguments)

        if result.is_error:
            print("TOOL ERROR (this is what the agent would see):")
        for block in result.content:
            print(block.text)


if __name__ == "__main__":
    anyio.run(main, sys.argv[1:])
