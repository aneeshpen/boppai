"""Shared fixtures.

The Node tests built a throwaway `{ folder }` object and passed it straight into the
calendar/basket modules. Here the equivalent is a real `Session` dataclass pointed at a
tmp_path, which also type-checks the service signatures while we're at it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.session import Session
from app.persistence import database as db


def make_session(folder: Path) -> Session:
    folder.mkdir(parents=True, exist_ok=True)
    return Session(
        id="test-session",
        folder=folder,
        name=None,
        title=None,
        agent="claude",
        runtime_session_id=None,
        active_surface="chat",
        status="active",
        started=False,
        created_at="2026-01-01T00:00:00.000Z",
        ended_at=None,
    )


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return make_session(tmp_path / "session")


@pytest.fixture
def temp_db(tmp_path: Path):
    """A fresh SQLite database for tests that touch sessions/settings."""
    db.init(tmp_path / "boppai.db")
    yield db
    db.close()
