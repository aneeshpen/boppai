"""
GET /api/tools -- the LOCAL MCP tools Boppai exposes to the agents.

Plain metadata only: no handlers, no CLI spawn, no remote introspection -- so it returns
instantly. Only servers that carry a static tool catalog (Boppai's own) are listed here.
Remote servers like Zepto and Swiggy have no static catalog; their live tools +
connection status come from /api/mcp/remote/{name}/tools.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...mcp.servers import all_mcp_servers

router = APIRouter()


@router.get("/api/tools")
async def tools() -> dict[str, Any]:
    return {
        "servers": [
            {
                "name": server.name,
                "label": server.label,
                "description": server.description,
                "tools": [
                    {
                        "name": tool["name"],
                        "title": tool["title"],
                        "description": tool["description"],
                    }
                    for tool in server.tools
                ],
            }
            for server in all_mcp_servers()
            if server.tools
        ]
    }
