"""
The agent contract -- what every "brain" must provide.

Each adapter answers the same three questions: how do we check it's logged in, how do
we build the chat command, and which stream parser reads its output. Everything
brain-specific is sealed inside its own module, so the layers above stay symmetric and
never branch on which CLI is running.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..mcp.servers import McpServerDescriptor


@dataclass(frozen=True)
class AuthStatus:
    logged_in: bool
    account: str | None = None


@dataclass
class ChatArgs:
    """Everything an adapter may need to build its CLI invocation.

    Every adapter receives the same Boppai context and decides for itself how to start
    or resume its native runtime and how to inject the prompt/MCP wiring.
    """

    boppai_session_id: str | None = None
    runtime_session_id: str | None = None
    mcp_config_path: str | None = None
    mcp_servers: list["McpServerDescriptor"] = field(default_factory=list)
    system_prompt: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    image_paths: list[str] = field(default_factory=list)


class AgentDef(ABC):
    """One brain. Subclasses are stateless singletons held in the registry."""

    id: str
    name: str
    tagline: str
    bin: str
    version_args: list[str]
    auth_probe_args: list[str]
    model: str | None = None
    reasoning_effort: str | None = None
    supports_images: bool = False
    stream_format: str

    @abstractmethod
    def parse_auth(self, output: str) -> AuthStatus:
        """Read the auth probe's combined stdout+stderr."""

    @abstractmethod
    def build_chat_args(self, args: ChatArgs) -> list[str]:
        """The argv (excluding the binary) for one turn."""

    def build_prompt(self, prompt: str, image_paths: list[str] | None = None) -> str:
        """How attachments reach this runtime. Default: the prompt is used verbatim."""
        return prompt
