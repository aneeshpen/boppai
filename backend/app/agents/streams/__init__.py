"""
Stream parsers, keyed by an agent's `stream_format`.

Both parsers emit the SAME normalized event vocabulary, which is the whole reason the
layers above never branch on which CLI is running:

    session | status | delta | tool | error | done

The chat route adds a final `end` event when the process exits.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .claude import create_claude_parser
from .codex import create_codex_parser

Event = dict[str, Any]

PARSERS: dict[str, Callable[[Callable[[Event], None]], Any]] = {
    "claude": create_claude_parser,
    "codex": create_codex_parser,
}


def create_parser(stream_format: str, on_event: Callable[[Event], None]) -> Any:
    return PARSERS[stream_format](on_event)
