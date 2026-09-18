"""
SQLite for the harness: sessions, message transcripts, and tiny settings.

The user's profile deliberately lives outside SQLite in `data/profile.md`. This
database stays boring on purpose: it remembers conversations and the selected agent,
while "New session" archives the old active session forever.

Threading note: better-sqlite3 was fully synchronous, so the Node build got
serialization for free. Here a single connection is shared with
`check_same_thread=False` and guarded by a lock. Every statement is a microsecond-scale
local operation, so holding the lock inline in an async handler is cheaper than
hopping to a thread pool — and it keeps the MCP tool callbacks, the SSE writers, and
the browser's own requests from interleaving mid-write.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_conn: sqlite3.Connection | None = None
_lock = threading.RLock()

SCHEMA = """
    CREATE TABLE IF NOT EXISTS sessions (
      id                 TEXT PRIMARY KEY,   -- Boppai UUID: folder + transcript identity
      folder             TEXT NOT NULL,      -- cwd we spawn the CLI in ("session = folder")
      name               TEXT,               -- user's display name (denormalized from profile)
      title              TEXT,               -- first user message, for the history list
      agent              TEXT,               -- which agent owns this session ('claude' | 'codex')
      runtime_session_id TEXT,               -- native Claude/Codex resume handle
      active_surface     TEXT NOT NULL DEFAULT 'chat', -- chat | calendar | basket
      status             TEXT NOT NULL DEFAULT 'active',  -- active | ended
      started            BOOLEAN NOT NULL DEFAULT FALSE,   -- did the CLI emit a session id?
      created_at         TEXT NOT NULL,
      ended_at           TEXT
    );

    CREATE TABLE IF NOT EXISTS messages (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      role       TEXT NOT NULL,      -- user | assistant
      content    TEXT NOT NULL,
      attachments_json TEXT,          -- optional JSON array of session-local image attachments
      created_at TEXT NOT NULL
    );

    -- Generic key-value prefs. First user: the chosen agent ('claude' | 'codex'),
    -- so a returning user lands straight in chat instead of the picker each time.
    CREATE TABLE IF NOT EXISTS settings (
      key   TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
"""


def init(file: str | Path) -> sqlite3.Connection:
    """Open the DB, apply the schema, and run the small explicit migrations."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = sqlite3.connect(str(file), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode = WAL")  # concurrent reads while a turn is written
        _conn.executescript(SCHEMA)
        _conn.executescript("DROP TABLE IF EXISTS research; DROP TABLE IF EXISTS meals;")
        _migrate(_conn)
        _conn.commit()
        return _conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    """`CREATE TABLE IF NOT EXISTS` does not add columns to an existing DB, so keep
    the tiny schema migrations explicit and safe to run on every boot."""
    session_columns = _columns(conn, "sessions")
    if "agent" not in session_columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN agent TEXT")
    if "runtime_session_id" not in session_columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN runtime_session_id TEXT")
    if "active_surface" not in session_columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN active_surface TEXT NOT NULL DEFAULT 'chat'")

    message_columns = _columns(conn, "messages")
    if "attachments_json" not in message_columns:
        conn.execute("ALTER TABLE messages ADD COLUMN attachments_json TEXT")

    # Before runtime_session_id existed, a started Claude session always used the
    # Boppai UUID as its native `--session-id`. Preserve resumability after upgrade.
    conn.execute(
        """UPDATE sessions
              SET runtime_session_id = id
            WHERE (agent = 'claude' OR agent IS NULL)
              AND started = 1
              AND runtime_session_id IS NULL"""
    )


def get() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("database.init() must run before database.get()")
    return _conn


def close() -> None:
    global _conn
    with _lock:
        if _conn is None:
            return
        _conn.close()
        _conn = None


@contextmanager
def write() -> Iterator[sqlite3.Connection]:
    """A locked, committing transaction. Use for anything that mutates."""
    with _lock:
        conn = get()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    with _lock:
        return list(get().execute(sql, params))


def query_one(sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    with _lock:
        return get().execute(sql, params).fetchone()


def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    with write() as conn:
        conn.execute(sql, params)


# --- settings: tiny key-value prefs (see the table comment above) ---


def get_setting(key: str) -> str | None:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
