"""Integration tests: the MCP server as a REAL separate process over stdio.

These are slower than the in-memory tests (they start a new Python process),
but they prove the thing real clients depend on: the server boots, speaks
the protocol over stdin/stdout, and keeps stdout clean.
"""

import subprocess
import sys

import pytest

from recon.config import settings
from recon.mcp_server.stdio_check import SERVER


@pytest.mark.anyio
async def test_server_runs_as_a_separate_process_over_stdio():
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools

    assert init.server_info.name == "recon-tools"
    assert len(tools) == 8


def test_importing_the_server_prints_nothing_to_stdout():
    """Over stdio, stdout IS the message channel. A stray print() at import
    time would corrupt the very first message a client receives."""
    result = subprocess.run(
        [sys.executable, "-c", "import recon.mcp_server.server"],
        cwd=settings.project_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""
