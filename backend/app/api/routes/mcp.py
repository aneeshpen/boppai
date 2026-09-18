"""
Remote MCP endpoints -- live status + tool catalogs for the remote MCP servers
(Zepto, Swiggy Instamart, ...).

  GET /api/mcp/remote               -> list remote servers (metadata only, instant)
  GET /api/mcp/remote/{name}/tools  -> live status + tools for one remote server

Unlike /api/tools (static local metadata), the per-server probe actually opens a
throwaway MCP session, so it spawns `npx mcp-remote` and takes a few seconds -- the
frontend shows a "Checking..." state while it runs.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...core.errors import BoppaiError
from ...mcp.servers import REMOTE_MCP_SERVERS
from ...services import settings as settings_service
from ...services.remote_mcp import login_command

router = APIRouter()

_BY_NAME = {server.name: server for server in REMOTE_MCP_SERVERS}


@router.get("/api/mcp/remote")
async def list_remote() -> dict[str, Any]:
    return {
        "servers": [
            {
                "name": server.name,
                "label": server.label,
                "description": server.description,
                "login": login_command(server, settings_service.get_agent()),
            }
            for server in REMOTE_MCP_SERVERS
        ]
    }


@router.get("/api/mcp/remote/{name}/tools")
async def remote_tools(name: str) -> dict[str, Any]:
    server = _BY_NAME.get(name)
    if server is None:
        raise BoppaiError(f"Unknown remote MCP: {name}", status=404)

    # The live probe is wired with the rest of the MCP layer; until then this endpoint
    # must not lie about connectivity.
    from ...services.remote_mcp import list_remote_tools

    agent_id = settings_service.get_agent()
    result = await list_remote_tools(server, agent_id)
    return {**result, "login": login_command(server, agent_id)}
