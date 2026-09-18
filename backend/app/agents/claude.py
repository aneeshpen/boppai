"""
Claude Code adapter -- how Boppai drives the `claude` CLI.

Everything Claude-specific lives in this file: how we (a) check it's logged in, (b)
build the chat command, and (c) which stream parser reads its output. The registry just
imports this def; nothing else in the app knows the difference between one brain and
another.
"""

from __future__ import annotations

import json
import re

from .base import AgentDef, AuthStatus, ChatArgs

_LOGGED_IN_RE = re.compile(r'"loggedIn"\s*:\s*true')


class ClaudeAgent(AgentDef):
    id = "claude"
    name = "Claude Code"
    tagline = "Anthropic's coding agent"
    bin = "claude"
    version_args = ["--version"]
    auth_probe_args = ["auth", "status"]

    # The conductor runs on Sonnet: smart enough to route + converse, cheaper/faster
    # than Opus. Medium effort mirrors Codex's pin so neither brain is left to CLI
    # defaults. Change here to retune the brain.
    model = "sonnet"
    reasoning_effort = "medium"

    # Claude Code has no image CLI flag, so instead of argv we hand it the saved file
    # paths in the prompt (see build_prompt) and let its built-in Read tool load them
    # as visual content. Same UX as Codex, different plumbing.
    supports_images = True

    stream_format = "claude"

    def parse_auth(self, output: str) -> AuthStatus:
        """`claude auth status` prints JSON: {"loggedIn": true, "email": "...", ...}."""
        try:
            parsed = json.loads(output)
        except (ValueError, TypeError):
            return AuthStatus(logged_in=bool(_LOGGED_IN_RE.search(output or "")), account=None)

        if not isinstance(parsed, dict):
            return AuthStatus(logged_in=False, account=None)
        return AuthStatus(
            logged_in=parsed.get("loggedIn") is True,
            account=parsed.get("email") or parsed.get("orgName") or None,
        )

    def build_chat_args(self, args: ChatArgs) -> list[str]:
        """Print mode + streaming JSON out.

        The prompt goes in via stdin, so it never hits argv length limits.
        `--include-partial-messages` gives us word-by-word text deltas.
        bypassPermissions = don't prompt for tool use.

        This is also where Claude-specific tool wiring lives:
          - `--mcp-config <file>` injects Boppai's current MCPs while still allowing
            the user's normal Claude configuration to participate.
          - `--append-system-prompt` injects the conductor brain + current profile.
          - start without a runtime id: propose Boppai's UUID via `--session-id`.
          - resume with the runtime id captured from Claude's init stream event.
        """
        argv = [
            "-p",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
        ]
        if args.model:
            argv += ["--model", args.model]
        if args.reasoning_effort:
            argv += ["--effort", args.reasoning_effort]
        if args.mcp_config_path:
            argv += ["--mcp-config", args.mcp_config_path]
        if args.system_prompt:
            argv += ["--append-system-prompt", args.system_prompt]

        if args.runtime_session_id:
            argv += ["--resume", args.runtime_session_id]
        elif args.boppai_session_id:
            argv += ["--session-id", args.boppai_session_id]
        return argv

    def build_prompt(self, prompt: str, image_paths: list[str] | None = None) -> str:
        """Claude reads local files with its Read tool, so we list the saved absolute
        paths under the user's text. bypassPermissions means it opens them without
        asking; absolute paths keep it working on --resume too. No images = prompt
        returned untouched."""
        paths = image_paths or []
        if not paths:
            return prompt
        label = "images" if len(paths) > 1 else "image"
        return "\n".join(
            [
                prompt,
                "",
                f"[Attached {label} — view each with the Read tool before replying:]",
                *paths,
            ]
        )


claude = ClaudeAgent()
