"""
Remote MCP introspection -- Boppai's OWN live client to an MCP server.

Boppai's chat path never touches this module: there, the claude/codex CLI is the MCP
client and calls remote tools itself. This exists for one job only -- answering the two
questions the Tools panel asks about each server (Zepto, Swiggy Instamart, ...): is it
connected right now, and which tools does it expose?

Two transports, because the remotes moved:

* **streamable HTTP** (the grocery services). Authentication belongs to the agent CLI --
  `claude mcp login <name>` or `codex mcp login <name>` -- and the token lives in that
  CLI's credential store, not ours. So an unauthenticated probe from here is *expected* to
  come back 401, and the honest answer is "reachable, needs authentication" plus the exact
  command to fix it. We deliberately do not read the CLI's stored tokens.
* **stdio** (Boppai's own bundled server). Spawned directly; no auth involved.

Connection state is inferred purely from what the probe observes. Fresh session per call.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from ..agents.executable import resolve_executable
from ..core.logging import get_logger
from ..mcp.servers import McpServerDescriptor

log = get_logger("remote-mcp")

# A whole open+list round-trip is "a few seconds" when authed. When NOT authed a server
# can stall, so we cap the wait and report offline.
PROBE_TIMEOUT_SECONDS = 20.0

_AUTH_HINTS = ("401", "unauthorized", "403", "forbidden", "invalid_token")


def login_command(server: McpServerDescriptor, agent_id: str | None = None) -> str:
    """The one-time login the UI surfaces when a server is not connected.

    HTTP servers authenticate through the agent CLI, which owns the OAuth flow and the
    token store. Two steps, because the CLI can only log into a server it knows about:
    register the URL, then authenticate. stdio servers need no login, so the legacy `npx`
    form is only ever produced for a command-based descriptor.
    """
    if server.is_http:
        agent = agent_id if agent_id in ("claude", "codex") else "claude"
        # --scope user is load-bearing, not a preference. Boppai spawns the CLI with the
        # session folder as its cwd, which is a different "project" from the repo, so a
        # project-scoped login is invisible at chat time and the turn dies with
        # "OAuth session expired". User scope applies everywhere.
        register = f"{agent} mcp add --transport http --scope user {server.name} {server.url}"
        return f"{register} && {agent} mcp login {server.name}"
    return f"npx -y {' '.join(server.args)}"


async def _agent_auth_status(server: McpServerDescriptor, agent_id: str | None) -> bool | None:
    """Does the agent CLI consider this server authenticated? None = can't tell.

    The token lives in the CLI's credential store, not ours, so the CLI is the only
    honest source of truth about whether the tools will actually work in chat.
    """
    agent = agent_id if agent_id in ("claude", "codex") else "claude"
    launcher = resolve_executable(agent)
    if launcher is None:
        return None

    try:
        process = await asyncio.create_subprocess_exec(
            *launcher,
            "mcp",
            "get",
            server.name,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
    except (OSError, asyncio.TimeoutError, TimeoutError):
        return None

    output = f"{stdout.decode('utf-8', 'replace')}\n{stderr.decode('utf-8', 'replace')}".lower()
    if "needs authentication" in output or "not authenticated" in output:
        return False
    if "connected" in output:
        return True
    return None


def to_tool_summaries(raw_tools: Any = None) -> list[dict[str, Any]]:
    """Pure shaping: turn raw MCP tool descriptors into the small summary the UI wants.

    Kept separate and side-effect-free so it's unit-testable without spawning anything.
    """
    summaries = []
    for tool in raw_tools or []:
        name = getattr(tool, "name", None)
        title = getattr(tool, "title", None)
        description = getattr(tool, "description", None)
        annotations = getattr(tool, "annotations", None)
        if name is None and isinstance(tool, dict):
            name = tool.get("name")
            title = tool.get("title")
            description = tool.get("description")
            annotations = tool.get("annotations")
        if title is None and annotations is not None:
            title = getattr(annotations, "title", None)
            if title is None and isinstance(annotations, dict):
                title = annotations.get("title")
        summaries.append({"name": name, "title": title or None, "description": description or ""})
    return summaries


def _leaf_message(exc: BaseException) -> str:
    """The innermost useful message from an anyio/asyncio failure.

    The MCP client runs its transport in a task group, so a plain `str(exc)` surfaces
    "unhandled errors in a TaskGroup (1 sub-exception)" instead of the real cause.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _looks_like_auth_failure(message: str, exc: BaseException | None = None) -> bool:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403):
        return True
    lowered = message.lower()
    return any(hint in lowered for hint in _AUTH_HINTS)


_INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "boppai-probe", "version": "0.1.0"},
    },
}


async def _probe_http(server: McpServerDescriptor, agent_id: str | None) -> dict[str, Any]:
    """Reachability first, then auth, then tools.

    A plain unauthenticated POST gives a definitive status code, which the SDK client
    flattens into a generic "Server returned an error response". Both grocery remotes
    answer 401 to us by design -- the bearer token lives in the agent CLI's store -- so a
    401 is not a failure, it is a question to redirect at the CLI.
    """
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                server.url,
                json=_INITIALIZE_REQUEST,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
    except httpx.HTTPError as exc:
        message = str(exc) or "Remote MCP unreachable"
        log.info("[remote-mcp] %s unreachable: %s", server.name, message)
        return {"connected": False, "tools": [], "error": message}

    if response.status_code in (401, 403):
        authed = await _agent_auth_status(server, agent_id)
        agent_label = "Codex" if agent_id == "codex" else "Claude Code"

        if authed:
            # The agent can use these tools even though we can't introspect them.
            # Saying "not connected" here would be flatly wrong.
            log.info("[remote-mcp] %s authenticated via %s", server.name, agent_label)
            return {
                "connected": True,
                "tools": [],
                "note": (
                    f"Authenticated in {agent_label}, which holds the token. Boppai can't "
                    "list the tools itself, but the agent can call them in chat."
                ),
            }

        log.info("[remote-mcp] %s needs authentication", server.name)
        return {
            "connected": False,
            "tools": [],
            "error": f"Needs authentication. Run: {login_command(server, agent_id)}",
        }

    if response.status_code >= 400:
        return {
            "connected": False,
            "tools": [],
            "error": f"Remote MCP returned HTTP {response.status_code}",
        }

    # Reachable and not gated -- open a real session and list the catalog.
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            # mcp 2.x yields a 2-tuple (read, write); the 1.x client also handed back a
            # session-id callback, which no longer exists.
            async with streamable_http_client(server.url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return {"connected": True, "tools": to_tool_summaries(result.tools)}
    except (TimeoutError, asyncio.TimeoutError):
        log.info("[remote-mcp] %s timed out after %ss", server.name, PROBE_TIMEOUT_SECONDS)
        return {"connected": False, "tools": [], "error": "Remote MCP timed out"}
    except Exception as exc:  # noqa: BLE001 - any failure means "not connected"
        message = _leaf_message(exc)
        log.info("[remote-mcp] %s probe failed: %s", server.name, message)
        return {"connected": False, "tools": [], "error": message}


async def _probe_stdio(server: McpServerDescriptor) -> dict[str, Any]:
    params = StdioServerParameters(
        command=server.command,
        args=list(server.args),
        env={**os.environ, **(server.env or {})} if server.env else None,
    )
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            # errlog -> devnull keeps a chatty bridge's stack traces out of our log; the
            # failure itself is still reported via _leaf_message below.
            with open(os.devnull, "w", encoding="utf-8") as devnull:
                async with stdio_client(params, errlog=devnull) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        return {"connected": True, "tools": to_tool_summaries(result.tools)}
    except (TimeoutError, asyncio.TimeoutError):
        return {"connected": False, "tools": [], "error": "Remote MCP timed out"}
    except Exception as exc:  # noqa: BLE001
        message = _leaf_message(exc)
        log.info("[remote-mcp] %s probe failed: %s", server.name, message)
        return {"connected": False, "tools": [], "error": message}


async def list_remote_tools(
    server: McpServerDescriptor, agent_id: str | None = None
) -> dict[str, Any]:
    """Open a short-lived session against the server, list tools, and close."""
    if server.is_http:
        return await _probe_http(server, agent_id)
    return await _probe_stdio(server)
