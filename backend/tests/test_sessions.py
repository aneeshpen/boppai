"""Port of backend/test/runtime-session.test.js.

Proves the schema migrations still run against a pre-runtime_session_id database, so
an existing user's boppai.db keeps working after the Python backend takes over.
"""

from __future__ import annotations

import sqlite3

from app.persistence import database as db
from app.services import sessions

LEGACY_SCHEMA = """
    CREATE TABLE sessions (
      id TEXT PRIMARY KEY,
      folder TEXT NOT NULL,
      name TEXT,
      title TEXT,
      agent TEXT,
      status TEXT NOT NULL DEFAULT 'active',
      started BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TEXT NOT NULL,
      ended_at TEXT
    );
    CREATE TABLE messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    INSERT INTO sessions
      (id, folder, agent, status, started, created_at)
    VALUES
      ('claude-old', '/tmp/claude-old', 'claude', 'active', TRUE, '2026-01-01'),
      ('claude-before-agent', '/tmp/claude-before-agent', NULL, 'ended', TRUE, '2026-01-01'),
      ('codex-old', '/tmp/codex-old', 'codex', 'ended', TRUE, '2026-01-01');
"""


def test_migrates_old_sessions_and_stores_runtime_ids_symmetrically(tmp_path):
    file = tmp_path / "legacy.db"
    legacy = sqlite3.connect(file)
    legacy.executescript(LEGACY_SCHEMA)
    legacy.commit()
    legacy.close()

    try:
        db.init(file)

        session_columns = {r["name"] for r in db.get().execute("PRAGMA table_info(sessions)")}
        assert "runtime_session_id" in session_columns
        assert "active_surface" in session_columns

        message_columns = {r["name"] for r in db.get().execute("PRAGMA table_info(messages)")}
        assert "attachments_json" in message_columns

        def row(session_id):
            return db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))

        # Started Claude sessions (including ones predating the `agent` column) used
        # the Boppai UUID as their native --session-id, so they stay resumable.
        assert row("claude-old")["runtime_session_id"] == "claude-old"
        assert row("claude-before-agent")["runtime_session_id"] == "claude-before-agent"
        # Codex mints its own thread id, so there is nothing to backfill.
        assert row("codex-old")["runtime_session_id"] is None

        sessions.set_runtime_session_id("codex-old", "codex-thread")
        sessions.set_active_surface("codex-old", "calendar")

        updated = row("codex-old")
        assert updated["runtime_session_id"] == "codex-thread"
        assert updated["started"] == 1
        assert updated["active_surface"] == "calendar"
    finally:
        db.close()


def test_runtime_session_id_rejects_blank_values(temp_db):
    session = sessions.create("claude")
    for bad in ("", "   "):
        try:
            sessions.set_runtime_session_id(session.id, bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_starting_a_new_session_archives_the_previous_one(temp_db):
    first = sessions.create("claude")
    second = sessions.start_new("codex")

    assert sessions.get_by_id(first.id).status == "ended"
    assert sessions.get_by_id(first.id).ended_at is not None
    assert sessions.get_active().id == second.id
    assert second.agent == "codex"


def test_title_is_only_set_once(temp_db):
    session = sessions.create("claude")
    sessions.set_title_if_empty(session.id, "first message")
    sessions.set_title_if_empty(session.id, "second message")
    assert sessions.get_by_id(session.id).title == "first message"


def test_message_roundtrip_preserves_attachments(temp_db):
    session = sessions.create("claude")
    sessions.add_message(session.id, "user", "look at this", [{"id": "a1", "kind": "image"}])
    sessions.add_message(session.id, "assistant", "nice")

    messages = sessions.messages_for(session.id)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["attachments"] == [{"id": "a1", "kind": "image"}]
    assert messages[1]["attachments"] == []
    # Node emitted `new Date().toISOString()` -- millisecond precision, trailing Z.
    assert messages[0]["created_at"].endswith("Z")
    assert len(messages[0]["created_at"]) == len("2026-01-01T00:00:00.000Z")
