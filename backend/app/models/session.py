"""The Session domain object — one typed view over a `sessions` row."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Session:
    """A session is a folder we spawn the CLI in, plus a DB row.

    `id` is always Boppai's UUID. `runtime_session_id` is the selected CLI's native
    resume handle, captured through the normalized stream event for every agent.
    """

    id: str
    folder: Path
    name: str | None
    title: str | None
    agent: str | None
    runtime_session_id: str | None
    active_surface: str
    status: str
    started: bool
    created_at: str
    ended_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Session:
        return cls(
            id=row["id"],
            folder=Path(row["folder"]),
            name=row["name"],
            title=row["title"],
            agent=row["agent"],
            runtime_session_id=row["runtime_session_id"],
            active_surface=row["active_surface"] or "chat",
            status=row["status"],
            started=bool(row["started"]),
            created_at=row["created_at"],
            ended_at=row["ended_at"],
        )
