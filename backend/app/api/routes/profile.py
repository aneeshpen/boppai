"""
The user's profile.md -- read/written by both the human (Profile page) and the agent
(the save_profile MCP tool, over localhost via /internal).

  GET/PUT  /api/profile        -> the browser-facing endpoints
  GET/POST /internal/profile   -> the MCP tool subprocess
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...core.deps import json_body
from ...core.errors import BoppaiError
from ...models.profile import ProfileSaved, ProfileState
from ...services import profile as profile_service
from ...services import sessions as sessions_service

router = APIRouter()


def _apply_profile_write(markdown: Any) -> ProfileSaved:
    """Write the profile file AND keep the active session's denormalized name in sync.

    Used by both the human edit (PUT /api/profile) and the agent tool (POST /internal).
    """
    if not isinstance(markdown, str):
        raise BoppaiError("markdown (string) required")

    name = profile_service.write(markdown)
    active = sessions_service.get_active()
    if active and name:
        sessions_service.set_name(active.id, name)
    return ProfileSaved(ok=True, name=name)


@router.get("/api/profile")
async def get_profile() -> ProfileState:
    return profile_service.read()


@router.put("/api/profile")
async def put_profile(body: dict[str, Any] = Depends(json_body)) -> ProfileSaved:
    return _apply_profile_write(body.get("markdown"))


# Called by the MCP tool subprocess over localhost -- not meant for the browser.
@router.get("/internal/profile")
async def internal_get_profile() -> ProfileState:
    return profile_service.read()


@router.post("/internal/profile")
async def internal_post_profile(body: dict[str, Any] = Depends(json_body)) -> ProfileSaved:
    return _apply_profile_write(body.get("markdown"))
