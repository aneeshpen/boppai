"""
Boppai MCP server (stdio) -- the reusable tool rig.

The tools themselves are authored in ./tools.py (the ONE catalog). This module just
takes that list and exposes it over stdio.

Design choice (separation of concerns): this server is AGENT-AGNOSTIC. It knows nothing
about Claude or Codex -- it just exposes tools over stdio. HOW it gets injected into a
CLI is each agent's own business (Claude uses `--mcp-config`; Codex uses
`-c mcp_servers.*`). And the tools don't write files directly -- they call back into our
backend over localhost, so there's a SINGLE write path (file + DB name + refresh) that
both CLIs share.

stdio rule: never write to stdout -- it corrupts the JSON-RPC stream. Logs go to stderr
only. app.core.logging enforces that process-wide, and config.py sets PYTHONUTF8=1 in
this child's environment so a rupee sign in a product name can't raise mid-stream.

Run as: python -m app.mcp.server
"""

from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer

from .tools import API, TOOLS


def build_server() -> MCPServer:
    server = MCPServer(name="boppai", version="0.1.0")
    # Register every tool from the catalog. The registration shape (name/title/
    # description + the function's typed signature, which becomes the input schema) is
    # exactly what add_tool wants, so this is a straight hand-off.
    for spec in TOOLS:
        server.add_tool(
            spec.fn,
            name=spec.name,
            title=spec.title,
            description=spec.description,
        )
    return server


def main() -> None:
    server = build_server()
    print(f"[boppai-mcp] running on stdio, API = {API}", file=sys.stderr, flush=True)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
