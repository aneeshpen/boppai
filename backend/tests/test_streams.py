"""Port of backend/test/codex-stream.test.js, plus equivalent coverage for Claude.

The event vocabulary these produce is the SSE contract the frontend switches surfaces
on, so the assertions compare whole event lists, not just individual fields.
"""

from __future__ import annotations

import json

from app.agents.streams import create_parser
from app.agents.streams.claude import normalize_tool_name


def harness(stream_format: str):
    events: list[dict] = []
    return events, create_parser(stream_format, events.append)


# --- Codex -----------------------------------------------------------------


def test_captures_codex_runtime_id_and_handles_fragmented_jsonl():
    events, parser = harness("codex")
    parser.feed('{"type":"thread.started","thread_')
    parser.feed('id":"codex-thread"}\n{"type":"turn.started"}\n')

    assert events == [
        {"type": "session", "sessionId": "codex-thread"},
        {"type": "status", "label": "initializing"},
        {"type": "status", "label": "thinking"},
    ]


def test_emits_real_mcp_tool_names_once_and_preserves_message_boundaries():
    events, parser = harness("codex")
    tool = {
        "id": "tool-1",
        "type": "mcp_tool_call",
        "server": "boppai",
        "tool": "get_profile",
        "arguments": {},
        "status": "in_progress",
    }

    parser.feed(json.dumps({"type": "item.started", "item": tool}) + "\n")
    parser.feed(
        json.dumps(
            {
                "type": "item.completed",
                "item": {**tool, "status": "completed", "result": {"content": []}},
            }
        )
        + "\n"
    )
    parser.feed(
        json.dumps(
            {"type": "item.completed", "item": {"id": "message-1", "type": "agent_message", "text": "Hello"}}
        )
        + "\n"
    )
    parser.feed(
        json.dumps(
            {"type": "item.completed", "item": {"id": "message-2", "type": "agent_message", "text": "there"}}
        )
        + "\n"
    )
    parser.feed('{"type":"turn.completed"}\n')

    assert events == [
        {"type": "tool", "name": "get_profile", "input": {}},
        {"type": "delta", "text": "Hello"},
        {"type": "delta", "text": "\nthere"},
        {"type": "done", "costUsd": None},
    ]


def test_extracts_nested_codex_failure_messages():
    events, parser = harness("codex")
    parser.feed(
        json.dumps({"type": "turn.failed", "error": {"error": {"detail": "MCP failed to initialize"}}})
        + "\n"
    )
    parser.flush()

    assert events == [{"type": "error", "message": "MCP failed to initialize"}]


def test_codex_skips_non_json_log_noise():
    events, parser = harness("codex")
    parser.feed("2026-09-18 INFO refreshing token\n")
    parser.feed('{"type":"turn.completed"}\n')
    assert events == [{"type": "done", "costUsd": None}]


def test_codex_labels_shell_commands_as_bash():
    events, parser = harness("codex")
    parser.feed(
        json.dumps({"type": "item.started", "item": {"id": "c1", "type": "command_execution", "command": "ls"}})
        + "\n"
    )
    assert events[0]["type"] == "tool"
    assert events[0]["name"] == "Bash"


# --- Claude ----------------------------------------------------------------


def test_claude_init_emits_session_then_thinking():
    events, parser = harness("claude")
    parser.feed(
        json.dumps(
            {"type": "system", "subtype": "init", "session_id": "claude-uuid", "model": "sonnet"}
        )
        + "\n"
    )
    assert events == [
        {"type": "session", "sessionId": "claude-uuid", "model": "sonnet"},
        {"type": "status", "label": "thinking"},
    ]


def test_claude_streams_text_deltas_word_by_word():
    events, parser = harness("claude")
    for text in ("Hel", "lo "):
        parser.feed(
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": text},
                    },
                }
            )
            + "\n"
        )
    assert events == [
        {"type": "delta", "text": "Hel"},
        {"type": "delta", "text": "lo "},
    ]


def test_claude_strips_the_mcp_namespace_from_tool_names():
    events, parser = harness("claude")
    parser.feed(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "mcp__boppai__show_basket",
                            "input": {"items": []},
                        }
                    ]
                },
            }
        )
        + "\n"
    )
    assert events == [{"type": "tool", "name": "show_basket", "input": {"items": []}}]


def test_claude_falls_back_to_wrapper_text_when_no_deltas_streamed():
    events, parser = harness("claude")
    parser.feed(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}})
        + "\n"
    )
    assert events == [{"type": "delta", "text": "Hi"}]


def test_claude_does_not_duplicate_text_that_already_streamed():
    events, parser = harness("claude")
    parser.feed(
        json.dumps(
            {
                "type": "stream_event",
                "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
            }
        )
        + "\n"
    )
    parser.feed(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}})
        + "\n"
    )
    assert events == [{"type": "delta", "text": "Hi"}]


def test_claude_result_reports_error_then_done():
    events, parser = harness("claude")
    parser.feed(
        json.dumps({"type": "result", "is_error": True, "result": "boom", "total_cost_usd": 0.01})
        + "\n"
    )
    assert events == [
        {"type": "error", "message": "boom"},
        {"type": "done", "costUsd": 0.01},
    ]


def test_normalize_tool_name_is_generic():
    assert normalize_tool_name("mcp__boppai__get_profile") == "get_profile"
    assert normalize_tool_name("mcp__swiggy-instamart__search_products") == "search_products"
    assert normalize_tool_name("Read") == "Read"
    assert normalize_tool_name(None) is None
