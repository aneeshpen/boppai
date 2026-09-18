"""
Codex stream parser.

Reads `codex exec --json` output and emits the SAME normalized events as the Claude
parser, so the rest of the app doesn't care which brain is running:
  {"type": "session", "sessionId": ...}   -- from `thread.started` (for exec resume)
  {"type": "status",  "label": ...}
  {"type": "delta",   "text": ...}        -- from the `agent_message` item
  {"type": "tool",    "name": ..., "input": ...}  -- command / MCP tool items
  {"type": "error",   "message": ...}
  {"type": "done",    "costUsd": None}    -- from `turn.completed`

Codex interleaves non-JSON log lines (token-refresh, tracing) with the JSON events, so we
simply skip any line that isn't valid JSON. Codex delivers the assistant reply as one
completed `agent_message` item rather than word-by-word.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

Event = dict[str, Any]

_TOOL_ITEM_TYPES = ("command_execution", "tool_call", "mcp_tool_call")


def _coalesce(*values: Any) -> Any:
    """JavaScript's `??` chain -- first value that is not None."""
    for value in values:
        if value is not None:
            return value
    return None


def error_message(value: Any, fallback: str) -> str:
    """Dig a human message out of Codex's nested error payloads.

    Codex wraps failures inconsistently -- sometimes a string, sometimes a JSON string,
    sometimes {error: {detail: ...}} -- so unwrap recursively and fall back.
    """
    if isinstance(value, str) and value.strip():
        try:
            return error_message(json.loads(value), value)
        except ValueError:
            return value
    if isinstance(value, dict):
        return error_message(
            _coalesce(value.get("message"), value.get("detail"), value.get("error")), fallback
        )
    return fallback


class CodexStreamParser:
    def __init__(self, on_event: Callable[[Event], None]) -> None:
        self._on_event = on_event
        self._buffer = ""
        self._previous_agent_message = False
        self._previous_ended_with_newline = False
        self._emitted_tool_ids: set[str] = set()

    def _emit_tool(self, item: Any) -> None:
        if not isinstance(item, dict):
            return
        item_type = item.get("type")
        if item_type not in _TOOL_ITEM_TYPES:
            return

        item_id = item.get("id")
        if item_id and item_id in self._emitted_tool_ids:
            return
        if item_id:
            self._emitted_tool_ids.add(item_id)

        if item_type == "mcp_tool_call":
            name = item.get("tool") or item.get("name") or "mcp_tool"
        elif item_type == "command_execution":
            name = "Bash"
        else:
            name = item.get("name") or item.get("tool") or "tool"

        self._on_event(
            {
                "type": "tool",
                "name": name,
                "input": _coalesce(item.get("arguments"), item.get("input"), item),
            }
        )

    def _handle(self, obj: Any) -> None:
        if not isinstance(obj, dict):
            return

        obj_type = obj.get("type")

        if obj_type == "thread.started":
            thread_id = obj.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                self._on_event({"type": "session", "sessionId": thread_id})
            self._on_event({"type": "status", "label": "initializing"})

        elif obj_type == "turn.started":
            self._previous_agent_message = False
            self._previous_ended_with_newline = False
            self._on_event({"type": "status", "label": "thinking"})

        elif obj_type == "item.started":
            self._emit_tool(obj.get("item"))

        elif obj_type == "item.completed":
            item = obj.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "agent_message" and item.get("text"):
                text = item["text"]
                # Codex sends each assistant message as its own completed item; keep the
                # paragraph break the user would have seen in the CLI.
                if (
                    self._previous_agent_message
                    and not self._previous_ended_with_newline
                    and not text.startswith("\n")
                ):
                    text = f"\n{text}"
                self._on_event({"type": "delta", "text": text})
                self._previous_agent_message = True
                self._previous_ended_with_newline = text.endswith("\n")
            else:
                self._previous_agent_message = False
                self._previous_ended_with_newline = False
                self._emit_tool(item)

        elif obj_type == "turn.completed":
            self._on_event({"type": "done", "costUsd": None})

        elif obj_type == "error":
            self._on_event(
                {
                    "type": "error",
                    "message": error_message(
                        _coalesce(obj.get("message"), obj.get("error")), "Codex run failed"
                    ),
                }
            )

        elif obj_type == "turn.failed":
            self._on_event(
                {
                    "type": "error",
                    "message": error_message(
                        _coalesce(obj.get("error"), obj.get("message")), "Codex turn failed"
                    ),
                }
            )

    def feed(self, chunk: str) -> None:
        self._buffer += chunk
        while True:
            newline = self._buffer.find("\n")
            if newline == -1:
                break
            line = self._buffer[:newline].strip()
            self._buffer = self._buffer[newline + 1 :]
            if not line or line[0] != "{":
                continue  # skip log noise
            try:
                self._handle(json.loads(line))
            except ValueError:
                pass

    def flush(self) -> None:
        line = self._buffer.strip()
        self._buffer = ""
        if line and line[0] == "{":
            try:
                self._handle(json.loads(line))
            except ValueError:
                pass


def create_codex_parser(on_event: Callable[[Event], None]) -> CodexStreamParser:
    return CodexStreamParser(on_event)
