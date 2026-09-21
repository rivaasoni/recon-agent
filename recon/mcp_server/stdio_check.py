"""
Connect to the MCP server as a REAL separate process — Phase 5, Step 5.

Until now, tests talked to the server in-memory. Real clients (our Phase 6
agent, Claude Desktop, Claude Code) instead START the server as a child
process and exchange JSON messages over its stdin/stdout ("stdio").

This script does exactly that, then:
  1. lists the tools and calls one, over the real transport;
  2. converts the tools with the Anthropic SDK's MCP helper and shows the
     definition Claude will actually receive in Phase 6.

No Claude API call is made — this costs nothing.

Run it:
    python -m recon.mcp_server.stdio_check
"""

from __future__ import annotations

import json
import sys

import anyio
from anthropic.lib.tools.mcp import async_mcp_tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from recon.config import settings

# How to launch the server: the same Python as this script (so the .venv is
# used), running our server module, from the project root (so `recon`
# can be imported).
SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "recon.mcp_server.server"],
    cwd=str(settings.project_root),
)


async def main() -> None:
    # stdio_client starts the server process and gives us its two pipes.
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            # The MCP handshake: client and server agree on a protocol
            # version and exchange capabilities.
            init = await session.initialize()
            print(f"Connected to server '{init.server_info.name}' (separate process)")

            tools = (await session.list_tools()).tools
            print(f"\n{len(tools)} tools available:")
            for tool in tools:
                kind = "read-only" if tool.annotations.read_only_hint else "PROPOSES (human approval)"
                print(f"  {tool.name:<32} {kind}")

            # One real call through the pipe.
            result = await session.call_tool("list_exception_cases", {})
            cases = json.loads(result.content[0].text)
            print(f"\nlist_exception_cases -> {cases['count']} open cases")

            # What Claude will receive in Phase 6. async_mcp_tool wraps an MCP
            # tool so the Anthropic Tool Runner can call it through this session.
            claude_tools = [async_mcp_tool(t, session) for t in tools]
            example = claude_tools[0].to_dict()
            print("\nWhat Claude sees for one tool (first 700 characters):")
            print(json.dumps(example, indent=2)[:700] + "\n  ...")


if __name__ == "__main__":
    anyio.run(main)
