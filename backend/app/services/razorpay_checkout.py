"""
Per-session Razorpay checkout state.

Mirrors prava_checkout.py: the agent starts a checkout through its MCP tool, and the
browser (or a later tool call) needs to read back what was started without depending on
the tool result still being in the SSE stream.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.session import Session
from ..persistence import files


def checkout_path(session: Session) -> Path:
    return session.folder / "razorpay-checkout.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read(session: Session) -> tuple[bool, dict[str, Any] | None]:
    raw = files.read_json(checkout_path(session))
    if raw is None:
        return False, None
    return True, raw


def write(session: Session, checkout: dict[str, Any]) -> dict[str, Any]:
    session.folder.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in checkout.items() if v is not None}
    payload["updatedAt"] = _now()
    files.write_json(checkout_path(session), payload)
    return payload


def start(session: Session, link: dict[str, Any], *, total_amount: str) -> dict[str, Any]:
    return write(
        session,
        {**link, "status": link.get("status") or "created", "totalAmount": total_amount,
         "createdAt": _now()},
    )


def record_status(session: Session, status: dict[str, Any]) -> dict[str, Any]:
    exists, current = read(session)
    return write(session, {**(current or {}), **status})
