"""Port of backend/test/remote-mcp.test.js, plus a real stdio round-trip.

The last test is the one that proves the MCP layer actually works rather than merely
type-checking: it launches Boppai's own stdio server as a subprocess and lists its tools
through the same client path the Zepto/Swiggy probe uses.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.mcp.servers import (
    REMOTE_MCP_SERVERS,
    McpServerDescriptor,
    create_browserclaw_mcp_server,
)
from app.services.remote_mcp import login_command, to_tool_summaries


@dataclass
class RawTool:
    """Stand-in for an SDK Tool object (attribute access, not dict)."""

    name: str
    title: str | None = None
    description: str | None = None
    annotations: object | None = None


@dataclass
class Annotations:
    title: str


def test_to_tool_summaries_keeps_fields_and_normalizes_missing_ones():
    raw = [
        RawTool(name="search_products", title="Search products", description="Find items."),
        # title can arrive under annotations; description may be absent entirely.
        RawTool(name="checkout", annotations=Annotations(title="Place order")),
    ]

    assert to_tool_summaries(raw) == [
        {"name": "search_products", "title": "Search products", "description": "Find items."},
        {"name": "checkout", "title": "Place order", "description": ""},
    ]


def test_to_tool_summaries_defaults_an_absent_list_to_empty():
    assert to_tool_summaries() == []
    assert to_tool_summaries([]) == []


def test_to_tool_summaries_also_accepts_plain_dicts():
    assert to_tool_summaries([{"name": "x", "description": "d"}]) == [
        {"name": "x", "title": None, "description": "d"}
    ]


def test_login_command_points_at_the_agent_cli_for_http_servers():
    """HTTP remotes authenticate through the agent CLI, which owns the token store.

    The old `npx -y mcp-remote <url>` form is dead for these: every published mcp-remote
    from 0.11.0 up enforces RFC 8414 §3.3 and Swiggy's metadata violates it.
    """
    server = McpServerDescriptor(
        name="swiggy-instamart",
        label="Swiggy Instamart MCP",
        description="",
        url="https://mcp.swiggy.com/im",
    )
    claude_cmd = login_command(server)
    assert claude_cmd == (
        "claude mcp add --transport http --scope user swiggy-instamart "
        "https://mcp.swiggy.com/im && claude mcp login swiggy-instamart"
    )
    # --scope user is required: Boppai spawns the CLI from a session folder, so a
    # project-scoped login is invisible at chat time.
    assert "--scope user" in claude_cmd
    assert login_command(server, "codex").startswith("codex mcp add --transport http --scope user")
    # An unknown agent falls back rather than emitting a nonsense command.
    assert login_command(server, "nope").startswith("claude mcp add")


def test_login_command_still_renders_npx_for_a_stdio_descriptor():
    server = McpServerDescriptor(
        name="legacy", label="", description="", command="npx", args=["mcp-remote", "https://x/y"]
    )
    assert login_command(server) == "npx -y mcp-remote https://x/y"


def test_remote_registry_wires_zepto_and_swiggy_over_http():
    by_name = {server.name: server for server in REMOTE_MCP_SERVERS}
    assert by_name["zepto"].url == "https://mcp.zepto.co.in/mcp"
    assert by_name["swiggy-instamart"].url == "https://mcp.swiggy.com/im"

    for server in REMOTE_MCP_SERVERS:
        assert server.is_http is True
        assert server.command is None, "remotes must not spawn a bridge subprocess"
        assert server.required is False
        # Remotes carry no static catalog -- tools are discovered live.
        assert server.tools == []


def test_browserclaw_descriptor_wraps_the_local_http_mcp_url():
    assert create_browserclaw_mcp_server("") is None
    assert create_browserclaw_mcp_server("   ") is None

    server = create_browserclaw_mcp_server(" http://127.0.0.1:9010/mcp ")
    assert server is not None
    assert server.name == "BrowserClaw"
    assert server.label == "BrowserClaw MCP"
    assert server.description == (
        "BrowserClaw browser tools for user-requested browser actions in the "
        "signed-in local browser."
    )
    assert server.is_http is True
    assert server.url == "http://127.0.0.1:9010/mcp"
    assert server.required is False
    assert server.tool_approvals == {
        "name_session": "approve",
        "tabs": "approve",
        "snapshot": "approve",
        "act": "approve",
        "read": "approve",
        "grep": "approve",
        "wait": "approve",
        "screenshot": "approve",
    }


def test_claude_mcp_config_emits_http_for_remotes_and_stdio_for_boppai():
    from app.core.boot import build_mcp_config
    from app.mcp.servers import boppai_mcp_server

    config = build_mcp_config([boppai_mcp_server(), REMOTE_MCP_SERVERS[1]])["mcpServers"]

    assert config["swiggy-instamart"] == {
        "type": "http",
        "url": "https://mcp.swiggy.com/im",
    }
    assert "command" not in config["swiggy-instamart"]

    assert config["boppai"]["command"].endswith("python.exe") or config["boppai"]["command"]
    assert config["boppai"]["args"] == ["-m", "app.mcp.server"]
    assert config["boppai"]["env"]["PYTHONUTF8"] == "1"


def test_codex_declares_an_http_remote_by_url_only():
    from app.agents.base import ChatArgs
    from app.agents.registry import AGENTS
    from app.mcp.servers import boppai_mcp_server

    argv = AGENTS["codex"].build_chat_args(
        ChatArgs(mcp_servers=[boppai_mcp_server(), REMOTE_MCP_SERVERS[1]])
    )
    flat = " ".join(argv)

    assert 'mcp_servers.swiggy-instamart.url="https://mcp.swiggy.com/im"' in flat
    # command/args/env are stdio-only; Codex rejects them for URL servers.
    assert "mcp_servers.swiggy-instamart.command" not in flat
    assert "mcp_servers.swiggy-instamart.args" not in flat
    assert "mcp_servers.swiggy-instamart.required=false" in flat
    # Boppai's own server keeps the stdio form.
    assert "mcp_servers.boppai.command=" in flat


@pytest.mark.asyncio
async def test_probing_boppais_own_stdio_server_reports_connected():
    """End-to-end MCP check without any network or OAuth.

    Points the live probe at our own bundled server, which exercises the whole path --
    spawn, JSON-RPC initialize, list_tools, shape -- and proves the `connected: True`
    branch, not just the failure branch the Zepto/Swiggy probes hit locally.
    """
    from app.mcp.servers import boppai_mcp_server
    from app.services.remote_mcp import list_remote_tools

    result = await list_remote_tools(boppai_mcp_server())

    assert result["connected"] is True, result.get("error")
    names = [tool["name"] for tool in result["tools"]]
    assert names == [
        "get_profile",
        "save_profile",
        "show_chat",
        "show_calendar",
        "show_basket",
        "start_prava_checkout",
        "get_prava_checkout_credential",
        "report_prava_merchant_outcome",
        # Razorpay test mode -- the free rail added alongside the hackathon's Prava.
        "start_razorpay_checkout",
        "get_razorpay_payment_status",
    ]
    assert all(tool["description"] for tool in result["tools"])
