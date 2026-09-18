"""
Session lifecycle + message persistence.

Model: each session is a folder we spawn the CLI in, plus a DB row. Exactly ONE
session is `active` at a time (single user). Starting a new session archives the
current one — it drops into the history view for free.

The CLI session is disposable; the durable state is the DB + the profile file.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ..core.config import SESSIONS_DIR
from ..models.session import Session
from ..persistence import database as db
from . import profile

ACTIVE_SURFACES = frozenset({"chat", "calendar", "basket"})

_UNSET = object()


def _now() -> str:
    """Node's `new Date().toISOString()` — millisecond precision, trailing Z."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --- messages ---------------------------------------------------------------


def _parse_attachments(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def add_message(
    session_id: str,
    role: str,
    content: str,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    clean = attachments if isinstance(attachments, list) else []
    db.execute(
        "INSERT INTO messages (session_id, role, content, attachments_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            session_id,
            role,
            content,
            json.dumps(clean, ensure_ascii=False) if clean else None,
            _now(),
        ),
    )


def messages_for(session_id: str) -> list[dict[str, Any]]:
    rows = db.query_all(
        "SELECT role, content, attachments_json, created_at FROM messages "
        "WHERE session_id = ? ORDER BY id",
        (session_id,),
    )
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
            "attachments": _parse_attachments(row["attachments_json"]),
        }
        for row in rows
    ]


# --- sessions ---------------------------------------------------------------


def get_active() -> Session | None:
    row = db.query_one(
        "SELECT * FROM sessions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
    )
    return Session.from_row(row) if row else None


def get_by_id(session_id: str) -> Session | None:
    row = db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    return Session.from_row(row) if row else None


def create(agent: str | None | Any = _UNSET) -> Session:
    """Open a fresh active session.

    Stamped with the agent that owns it. Defaults to the currently remembered pick
    (the agent the user is on when the conversation begins), but callers can pass one
    explicitly — e.g. when a switch forces a fresh session.
    """
    owner = db.get_setting("agent") if agent is _UNSET else agent
    session_id = str(uuid.uuid4())
    folder = SESSIONS_DIR / session_id
    folder.mkdir(parents=True, exist_ok=True)

    db.execute(
        "INSERT INTO sessions (id, folder, name, agent, status, started, created_at) "
        "VALUES (?, ?, ?, ?, 'active', 0, ?)",
        (session_id, str(folder), profile.read().name, owner, _now()),
    )
    created = get_by_id(session_id)
    assert created is not None
    return created


def get_or_create_active() -> Session:
    return get_active() or create()


def start_new(agent: str | None | Any = _UNSET) -> Session:
    """End the current session (into history) and open a fresh one."""
    active = get_active()
    if active:
        db.execute(
            "UPDATE sessions SET status = 'ended', ended_at = ? WHERE id = ?",
            (_now(), active.id),
        )
    return create(agent)


def set_runtime_session_id(session_id: str, runtime_session_id: str) -> None:
    """Record the native resume handle only after the CLI has actually initialized
    and emitted it. This keeps a failed first spawn retryable instead of leaving a
    phantom "started" session behind."""
    if not isinstance(runtime_session_id, str) or not runtime_session_id.strip():
        raise ValueError("runtimeSessionId must be a non-empty string")
    db.execute(
        "UPDATE sessions SET runtime_session_id = ?, started = 1 WHERE id = ?",
        (runtime_session_id.strip(), session_id),
    )


def set_title_if_empty(session_id: str, title: str) -> None:
    db.execute(
        "UPDATE sessions SET title = COALESCE(title, ?) WHERE id = ?",
        (str(title)[:80], session_id),
    )


def set_name(session_id: str, name: str) -> None:
    db.execute("UPDATE sessions SET name = ? WHERE id = ?", (name, session_id))


def set_active_surface(session_id: str, surface: str) -> None:
    if surface not in ACTIVE_SURFACES:
        raise ValueError("active surface must be chat, calendar, or basket")
    db.execute("UPDATE sessions SET active_surface = ? WHERE id = ?", (surface, session_id))


def list_all() -> list[dict[str, Any]]:
    rows = db.query_all(
        """SELECT s.id, s.title, s.name, s.status, s.created_at, s.ended_at,
                  (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count
             FROM sessions s
         ORDER BY s.created_at DESC"""
    )
    return [dict(row) for row in rows]
