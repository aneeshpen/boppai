"""
File-backed state helpers.

Boppai keeps several things outside SQLite on purpose — the profile is markdown the
user hand-edits, and each session folder holds calendar.json, basket.json,
ingredient-list.json and prava-checkout.json. These helpers centralize the read/write
so every writer produces the same bytes the Node build did:
`JSON.stringify(value, null, 2) + "\n"`.

`ensure_ascii=False` matters — JSON.stringify leaves non-ASCII characters intact, and
the data is full of things like "₹120".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any | None:
    """Parsed JSON, or None when the file does not exist."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    """Write pretty JSON with a trailing newline, matching the Node writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, ensure_ascii=False)
    path.write_text(f"{text}\n", encoding="utf-8")


def read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")
