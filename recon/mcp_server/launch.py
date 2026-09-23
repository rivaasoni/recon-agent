"""
How a client starts our MCP server as a separate process (stdio transport).

Shared by the stdio check, the agent, and the tests, so there's exactly one
definition of "how to launch the server".
"""

from __future__ import annotations

import sys

from mcp import StdioServerParameters

from recon.config import settings

# Run our server module with the SAME Python as the caller (so the .venv is
# used), from the project root (so `recon` can be imported).
SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "recon.mcp_server.server"],
    cwd=str(settings.project_root),
)
