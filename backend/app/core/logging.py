"""
Logging setup — everything goes to stderr, deliberately.

The Node backend used console.log (stdout) for its Prava request/response trace.
Here we send every log to stderr instead, for one reason that matters: the bundled
MCP server (app/mcp/server.py) speaks JSON-RPC over stdout, and a single stray
write there corrupts the stream. Using one stderr-only setup for the whole package
means no module can ever be moved into the MCP process and quietly break it.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Install a single stderr handler. Safe to call more than once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    # Windows consoles default to cp1252, and this app logs product names and
    # prices full of characters like "₹". Node's console handled those natively;
    # Python would raise UnicodeEncodeError mid-log. Force UTF-8 and never let a
    # log line be the thing that takes the backend down.
    for stream in (sys.stderr, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger("boppai")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"boppai.{name}")
