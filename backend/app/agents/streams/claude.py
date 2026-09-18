"""
Claude Code stream parser.

Reads the `--output-format stream-json --verbose --include-partial-messages` JSONL
stream and boils it down to our normalized events:
  {"type": "session", "sessionId": ..., "model": ...}  -- the CLI session id (for --resume)
  {"type": "status",  "label": ...}                    -- lifecycle hint
  {"type": "delta",   "text": ...}                     -- assistant text chunk
  {"type": "tool",    "name": ..., "input": ...}       -- a tool the agent called
  {"type": "error",   "message": ...}
  {"type": "done",    "costUsd": ...}                  -- turn finished

Keeps only what the UI needs. Text arrives as `stream_event` deltas (word-by-word); if a
build doesn't stream them, we fall back to the final `assistant` wrapper text.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

Event = dict[str, Any]

_MCP_PREFIX_RE = re.compile(r"^mcp__.+?__")


def normalize_tool_name(name: Any) -> Any:
    """Claude Code namespaces MCP tools as `mcp__<server>__<tool>` (e.g.
    `mcp__boppai__show_basket`), while Codex reports the bare `<tool>` name.

    The rest of the app -- and the frontend's surface switching -- keys off the bare
    name, so we strip the prefix here to keep both brains interchangeable. Generic on
    purpose: any future boppai tool (or added MCP server) just works.
    """
    if not isinstance(name, str):
        return name
    return _MCP_PREFIX_RE.sub("", name, count=1)


class ClaudeStreamParser:
    def __init__(self, on_event: Callable[[Event], None]) -> None:
        self._on_event = on_event
        self._buffer = ""
        self._streamed_text = False  # did the current message already stream deltas?

    def _handle(self, obj: Any) -> None:
        if not isinstance(obj, dict):
            return

        if obj.get("type") == "system" and obj.get("subtype") == "init":
            self._on_event(
                {
                    "type": "session",
                    "sessionId": obj.get("session_id"),
                    "model": obj.get("model") if obj.get("model") is not None else None,
                }
            )
            self._on_event({"type": "status", "label": "thinking"})
            return

        if obj.get("type") == "stream_event" and obj.get("event"):
            event = obj["event"]
            if not isinstance(event, dict):
                return
            if event.get("type") == "message_start":
                self._streamed_text = False
            elif event.get("type") == "content_block_delta":
                delta = event.get("delta")
                if isinstance(delta, dict) and delta.get("type") == "text_delta":
                    self._streamed_text = True
                    self._on_event({"type": "delta", "text": delta.get("text")})
            return

        # The `assistant` wrapper is the "block finished" signal. It carries tool_use
        # blocks, and (on builds without streaming) the full text.
        message = obj.get("message")
        if obj.get("type") == "assistant" and isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        self._on_event(
                            {
                                "type": "tool",
                                "name": normalize_tool_name(block.get("name")),
                                "input": block.get("input")
                                if block.get("input") is not None
                                else None,
                            }
                        )
                    elif (
                        block.get("type") == "text"
                        and not self._streamed_text
                        and block.get("text")
                    ):
                        self._on_event({"type": "delta", "text": block["text"]})
                self._streamed_text = False
            return

        if obj.get("type") == "result":
            if obj.get("is_error"):
                self._on_event(
                    {
                        "type": "error",
                        "message": obj.get("result")
                        or obj.get("subtype")
                        or "Claude run failed",
                    }
                )
            self._on_event({"type": "done", "costUsd": obj.get("total_cost_usd")})
            return

    def feed(self, chunk: str) -> None:
        self._buffer += chunk
        while True:
            newline = self._buffer.find("\n")
            if newline == -1:
                break
            line = self._buffer[:newline].strip()
            self._buffer = self._buffer[newline + 1 :]
            if not line:
                continue
            try:
                self._handle(json.loads(line))
            except ValueError:
                pass  # ignore non-JSON log lines

    def flush(self) -> None:
        line = self._buffer.strip()
        self._buffer = ""
        if line:
            try:
                self._handle(json.loads(line))
            except ValueError:
                pass


def create_claude_parser(on_event: Callable[[Event], None]) -> ClaudeStreamParser:
    return ClaudeStreamParser(on_event)
