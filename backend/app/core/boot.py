"""
One-time startup side-effects, run from the FastAPI lifespan before serving.

Make sure our folders + DB exist and materialize the MCP config files the CLI needs to
launch our tool servers. Kept apart from config.py (which only computes values) so
importing a path never has the side-effect of touching the disk.
"""

from __future__ import annotations

from typing import Any

from ..mcp.servers import (
    REMOTE_MCP_SERVERS,
    McpServerDescriptor,
    mcp_config_path_for_provider,
    mcp_servers_for_provider,
)
from ..persistence import database as db
from ..persistence import files
from .config import DATA_DIR, DB_PATH, SESSIONS_DIR
from .logging import get_logger

log = get_logger("boot")


def _to_claude_mcp_config(server: McpServerDescriptor) -> dict[str, Any]:
    """One entry of Claude's `--mcp-config` file.

    HTTP servers are declared by URL and Claude owns the OAuth (`claude mcp login
    <name>`); stdio servers get the command/args/env they are launched with.
    """
    if server.is_http:
        return {"type": "http", "url": server.url}

    config: dict[str, Any] = {"command": server.command, "args": list(server.args or [])}
    if server.env:
        config["env"] = dict(server.env)
    return config


def build_mcp_config(servers: list[McpServerDescriptor]) -> dict[str, Any]:
    return {"mcpServers": {server.name: _to_claude_mcp_config(server) for server in servers}}


def boot() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    db.init(DB_PATH)

    # One MCP config file per grocery provider. Each tells Claude how to launch our
    # local tool server plus exactly that provider's remote MCP; optional helper MCPs
    # such as BrowserClaw may also be appended. The session picks the file matching the
    # user's provider setting, so other grocery providers are never wired. Codex reads
    # the server list directly (not the file), but writing per-provider keeps both
    # agents' wiring driven by the same source.
    for remote in REMOTE_MCP_SERVERS:
        files.write_json(
            mcp_config_path_for_provider(remote.name),
            build_mcp_config(mcp_servers_for_provider(remote.name)),
        )

    log.info("[boppai] data dir %s", DATA_DIR)
    log.info(
        "[boppai] wrote MCP config for %s",
        ", ".join(server.name for server in REMOTE_MCP_SERVERS),
    )


def shutdown() -> None:
    """Release the SQLite handle on a clean stop."""
    db.close()
    log.info("[boppai] backend stopped")
