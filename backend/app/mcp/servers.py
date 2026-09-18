"""
MCP server descriptors — what Boppai wires into the agent for a session.

Remote MCP servers carry NO static `tools` list on purpose: their catalogs are
discovered live (see services/remote_mcp.py) and served by
/api/mcp/remote/{name}/tools, so the Tools panel always shows each server's real,
current tools instead of a frozen copy. The descriptors still feed chat wiring
(Claude's --mcp-config, Codex's -c). Remotes are declared by URL and reached over
streamable HTTP; the agent CLI owns the OAuth flow and the token store, so one
`claude mcp login <name>` (or `codex mcp login <name>`) covers both the Tools panel probe
and the CLI's chat-time use. See McpServerDescriptor for why the old `npx mcp-remote`
bridge was dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class McpServerDescriptor:
    """One MCP server, in either of the two transports we wire.

    * **stdio** — `command` + `args`. Used for Boppai's own bundled tool server.
    * **streamable HTTP** — `url`. Used for the remote grocery services.

    The remotes used to be reached through `npx mcp-remote <url>`, which bridges HTTP to
    stdio and owns the OAuth dance. That stopped working: `mcp-remote` now enforces
    RFC 8414 §3.3 (the `issuer` in an authorization server's metadata must match the URL
    the metadata was discovered at), and Swiggy's metadata is served at a path implying
    `https://mcp.swiggy.com/` while declaring `issuer: https://mcp.swiggy.com/auth`.
    Every published `mcp-remote` version from 0.11.0 up refuses that, so the bridge is a
    dead end regardless of pinning.

    Both CLIs speak streamable HTTP natively and have more forgiving OAuth clients
    (`claude mcp login <name>` / `codex mcp login <name>`), so we hand them the URL and
    let them own authentication. That also removes a whole `npx` subprocess per session.
    """

    name: str
    label: str
    description: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    required: bool = True
    tool_approvals: dict[str, str] = field(default_factory=dict)
    # Only Boppai's own server carries a static catalog; remotes stay empty.
    tools: list[dict[str, str]] = field(default_factory=list)

    @property
    def is_http(self) -> bool:
        return bool(self.url)


ZEPTO_MCP_SERVER = McpServerDescriptor(
    name="zepto",
    label="Zepto MCP",
    description=(
        "Remote Zepto quick-commerce tools over streamable HTTP. Authenticate once with "
        "your agent CLI (`claude mcp login zepto`)."
    ),
    url="https://mcp.zepto.co.in/mcp",
    required=False,
)

SWIGGY_INSTAMART_MCP_SERVER = McpServerDescriptor(
    name="swiggy-instamart",
    label="Swiggy Instamart MCP",
    description=(
        "Remote Swiggy Instamart grocery tools over streamable HTTP. Authenticate once "
        "with your agent CLI (`claude mcp login swiggy-instamart`)."
    ),
    url="https://mcp.swiggy.com/im",
    required=False,
)


def create_browserclaw_mcp_server(url: str) -> McpServerDescriptor | None:
    trimmed = (url or "").strip()
    if not trimmed:
        return None
    return McpServerDescriptor(
        name="BrowserClaw",
        label="BrowserClaw MCP",
        description=(
            "BrowserClaw browser tools for user-requested browser actions in the "
            "signed-in local browser."
        ),
        url=trimmed,
        required=False,
        tool_approvals={
            "name_session": "approve",
            "tabs": "approve",
            "snapshot": "approve",
            "act": "approve",
            "read": "approve",
            "grep": "approve",
            "wait": "approve",
            "screenshot": "approve",
        },
    )


# The registry of remote MCP servers Boppai exposes. Add a descriptor here and it
# automatically flows into chat wiring, the /api/mcp/remote endpoints, and the Tools
# panel — no per-server plumbing.
REMOTE_MCP_SERVERS: list[McpServerDescriptor] = [ZEPTO_MCP_SERVER, SWIGGY_INSTAMART_MCP_SERVER]

# The provider a session uses when the user hasn't picked one. Swiggy Instamart is the
# working integration, so it's the safe out-of-the-box default. Zepto is wired only
# when explicitly chosen.
DEFAULT_PROVIDER = "swiggy-instamart"


# --- Boppai's own local MCP ------------------------------------------------


def create_boppai_mcp_server() -> McpServerDescriptor:
    """The bundled stdio tool server, as the CLI is told to launch it.

    Node passed `process.execPath` + a script path; the Python equivalent is this
    interpreter (so the venv that has `mcp` installed is the one that runs) plus
    `-m app.mcp.server`. Two env vars are load-bearing:

      * PYTHONPATH  -- so `app.mcp.server` resolves in the child, whatever its cwd.
      * PYTHONUTF8  -- Windows would otherwise give the child a cp1252 stdout, and the
                       JSON-RPC stream carries product names and prices full of
                       characters like "₹". Node's stdio was UTF-8 by default.
    """
    from ..core.config import BACKEND_ROOT, MCP_SERVER_ARGS, MCP_SERVER_COMMAND, settings
    from .tools import TOOLS

    return McpServerDescriptor(
        name="boppai",
        label="Boppai MCP",
        description="Boppai's local app tools for profile, chat surface, and meal planning.",
        command=MCP_SERVER_COMMAND,
        args=list(MCP_SERVER_ARGS),
        env={
            "BOPPAI_API_URL": settings.api_url,
            "PYTHONPATH": str(BACKEND_ROOT),
            "PYTHONUTF8": "1",
        },
        tools=[
            {"name": tool.name, "title": tool.title, "description": tool.description}
            for tool in TOOLS
        ],
        tool_approvals={
            tool.name: tool.headless_approval for tool in TOOLS if tool.headless_approval
        },
    )


def boppai_mcp_server() -> McpServerDescriptor:
    """Cached accessor -- the descriptor is pure data, built once."""
    global _BOPPAI_SERVER
    if _BOPPAI_SERVER is None:
        _BOPPAI_SERVER = create_boppai_mcp_server()
    return _BOPPAI_SERVER


def browserclaw_mcp_server() -> McpServerDescriptor | None:
    from ..core.config import settings

    return create_browserclaw_mcp_server(settings.browserclaw_mcp_url)


_BOPPAI_SERVER: McpServerDescriptor | None = None
_REMOTE_BY_NAME = {server.name: server for server in REMOTE_MCP_SERVERS}


# --- provider wiring -------------------------------------------------------


def provider_or_default(name: str | None) -> str:
    """Normalize an incoming provider name to one we can actually wire.

    A missing or unknown name (e.g. a stale setting) falls back to the working default
    instead of leaving a session with no grocery tools.
    """
    return name if name in _REMOTE_BY_NAME else DEFAULT_PROVIDER


def provider_descriptor(name: str | None) -> McpServerDescriptor:
    """The remote descriptor for a provider -- used for its human label in the prompt."""
    return _REMOTE_BY_NAME[provider_or_default(name)]


def provider_label(name: str | None) -> str:
    """The consumer-facing brand ("Swiggy Instamart"), dropping the descriptor's " MCP"."""
    return re.sub(r"\s*MCP$", "", provider_descriptor(name).label)


def mcp_servers_for_provider(name: str | None) -> list[McpServerDescriptor]:
    """What a session actually wires: our local boppai tools + ONLY the chosen grocery
    provider's remote. Optional non-grocery helpers, such as BrowserClaw, can be appended
    without making them selectable grocery providers."""
    browserclaw = browserclaw_mcp_server()
    return [
        boppai_mcp_server(),
        provider_descriptor(name),
        *([browserclaw] if browserclaw else []),
    ]


def mcp_config_path_for_provider(name: str | None) -> Path:
    """Per-provider config file path. boot materializes one of these for each remote;
    chat hands the matching one to Claude via --mcp-config."""
    from ..core.config import DATA_DIR

    return DATA_DIR / f"boppai.mcp.{provider_or_default(name)}.json"


def all_mcp_servers() -> list[McpServerDescriptor]:
    """Local + every remote.

    Only consumer is GET /api/tools, which filters to servers carrying a static `tools`
    list -- that's boppai alone, since remotes have none -- so this stays purely the
    local-tools source for that panel. Chat wiring does NOT use this; it scopes to one
    provider via the helpers above.
    """
    return [boppai_mcp_server(), *REMOTE_MCP_SERVERS]
