"""
Codex adapter -- how Boppai drives the `codex` CLI.

Everything Codex-specific lives in this file, including the TOML-escaping helpers
below: `codex -c key=value` parses each value as TOML, and Codex is the only brain that
needs them, so they stay module-local rather than sitting in the shared registry.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..mcp.servers import McpServerDescriptor
from .base import AgentDef, AuthStatus, ChatArgs


def toml_literal(value: Any) -> str:
    """JSON string/array literals are valid TOML literals for the values we inject and
    correctly escape newlines, quotes, backslashes, spaces, and absolute paths.

    `bool` is checked before `int` deliberately -- in Python `bool` is a subclass of
    `int`, and TOML wants lowercase `true`/`false`, not Python's `True`/`False`.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ",".join(toml_literal(item) for item in value) + "]"
    raise TypeError(f"Unsupported Codex config value: {type(value).__name__}")


def _add_config(argv: list[str], key: str, value: Any) -> None:
    argv += ["-c", f"{key}={toml_literal(value)}"]


def _add_contained_runtime(argv: list[str]) -> None:
    argv.append("--ignore-user-config")
    _add_config(argv, "sandbox_mode", "read-only")
    # Session folders live below the Boppai repository, but the app runtime must not
    # inherit repository-development AGENTS.md rules. Boppai's conductor prompt is the
    # complete application instruction set for this child.
    _add_config(argv, "project_doc_max_bytes", 0)


def _add_mcp_server(argv: list[str], server: McpServerDescriptor) -> None:
    """Codex takes its MCP wiring as `-c mcp_servers.<name>.*` TOML overrides.

    A streamable-HTTP server is declared by `url` alone — `command`/`args`/`env` are
    stdio-only and Codex rejects `--env` for URL servers, so they are omitted entirely.
    """
    if server.is_http:
        _add_config(argv, f"mcp_servers.{server.name}.url", server.url)
    else:
        _add_config(argv, f"mcp_servers.{server.name}.command", server.command)
        _add_config(argv, f"mcp_servers.{server.name}.args", list(server.args or []))
        for key, value in (server.env or {}).items():
            _add_config(argv, f"mcp_servers.{server.name}.env.{key}", value)

    _add_config(argv, f"mcp_servers.{server.name}.required", server.required is not False)
    for tool, approval_mode in (server.tool_approvals or {}).items():
        _add_config(argv, f"mcp_servers.{server.name}.tools.{tool}.approval_mode", approval_mode)


class CodexAgent(AgentDef):
    id = "codex"
    name = "Codex"
    tagline = "OpenAI's coding agent"
    bin = "codex"
    version_args = ["--version"]
    auth_probe_args = ["login", "status"]

    # Keep Codex on Terra with medium reasoning: a balanced conductor pairing for
    # Claude's Sonnet pin without leaving the choice to CLI defaults.
    model = "gpt-5.6-terra"
    reasoning_effort = "medium"

    # Codex takes images as argv (`--image` in build_chat_args), so the prompt needs no
    # image plumbing -- see build_prompt below.
    supports_images = True

    stream_format = "codex"

    def parse_auth(self, output: str) -> AuthStatus:
        """`codex login status` prints e.g. "Logged in using ChatGPT".

        Note: this can report logged-in while the token is actually expired -- the real
        check is a chat attempt, whose 401 we surface to the user.
        """
        text = output or ""
        logged_in = bool(re.search(r"logged in", text, re.I)) and not re.search(
            r"not logged in", text, re.I
        )
        account = text.strip().split("\n")[0] if logged_in else None
        return AuthStatus(logged_in=logged_in, account=account)

    def build_chat_args(self, args: ChatArgs) -> list[str]:
        """Same lifecycle contract as Claude: no runtime id starts a session, a stored
        runtime id resumes it. Codex differs only inside this adapter because it mints
        the id itself and reports it as `thread.started.thread_id`."""
        argv = (
            ["exec", "resume", "--json", "--skip-git-repo-check"]
            if args.runtime_session_id
            else ["exec", "--json", "--skip-git-repo-check"]
        )

        # Keep Boppai's Codex runs from merging with user-level MCP config. Boppai
        # injects the MCPs it needs for this run, including any helper approvals.
        _add_contained_runtime(argv)

        if args.system_prompt:
            _add_config(argv, "developer_instructions", args.system_prompt)
        for server in args.mcp_servers or []:
            _add_mcp_server(argv, server)

        if args.model:
            argv += ["--model", args.model]
        if args.reasoning_effort:
            _add_config(argv, "model_reasoning_effort", args.reasoning_effort)
        for image_path in args.image_paths or []:
            argv += ["--image", image_path]

        # Resume flags must precede Codex's positional SESSION_ID. The prompt itself is
        # still delivered through stdin, so the runtime id is the final argv item.
        if args.runtime_session_id:
            argv.append(args.runtime_session_id)
        return argv

    def build_prompt(self, prompt: str, image_paths: list[str] | None = None) -> str:
        """Images already ride argv as `--image`, so the prompt is used verbatim. Kept
        for symmetry with Claude's adapter -- every brain exposes the same hook."""
        return prompt


codex = CodexAgent()
