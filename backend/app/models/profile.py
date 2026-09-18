"""Wire models for the profile endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class ProfileState(BaseModel):
    """The exact body GET /api/profile and GET /internal/profile return."""

    exists: bool
    markdown: str
    name: str | None = None


class ProfileSaved(BaseModel):
    """The body returned after a successful profile write."""

    ok: bool = True
    name: str | None = None
