"""
Session lifecycle + transcript endpoints (state lives in services/sessions.py).

  GET   /api/session/current        -> the active session + its transcript
  POST  /api/session/new            -> archive the current session, start a fresh one
  PATCH /api/session/surface        -> the browser switching surface
  POST  /internal/surface           -> the same, for the MCP tools
  GET   /api/sessions               -> list every session (history/debug view)
  GET   /api/sessions/{id}/messages -> one session's full transcript (read-only)
  GET   /api/sessions/{id}/attachments/{file} -> a saved image attachment
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ...core.deps import json_body
from ...core.errors import BoppaiError
from ...models.session import Session
from ...services import attachments as attachments_service
from ...services import profile as profile_service
from ...services import sessions as sessions_service

router = APIRouter()


def session_payload(session: Session) -> dict[str, Any]:
    """The shape both current + new return: the session plus whether a profile exists."""
    return {
        "sessionId": session.id,
        "agentSessionId": session.runtime_session_id,
        "name": session.name,
        "agent": session.agent,
        "activeSurface": session.active_surface or "chat",
        "profileExists": profile_service.read().exists,
        "messages": sessions_service.messages_for(session.id),
    }


@router.get("/api/session/current")
async def current() -> dict[str, Any]:
    return session_payload(sessions_service.get_or_create_active())


@router.post("/api/session/new")
async def new() -> dict[str, Any]:
    return session_payload(sessions_service.start_new())


@router.patch("/api/session/surface")
async def patch_surface(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    session = sessions_service.get_or_create_active()
    try:
        sessions_service.set_active_surface(session.id, body.get("activeSurface"))
    except ValueError as exc:
        raise BoppaiError(str(exc)) from exc

    updated = sessions_service.get_by_id(session.id)
    assert updated is not None
    return session_payload(updated)


@router.post("/internal/surface")
async def internal_surface(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    session = sessions_service.get_or_create_active()
    active_surface = body.get("activeSurface")
    try:
        sessions_service.set_active_surface(session.id, active_surface)
    except ValueError as exc:
        raise BoppaiError(str(exc)) from exc
    return {"ok": True, "activeSurface": active_surface}


@router.get("/api/sessions")
async def list_sessions() -> dict[str, Any]:
    return {"sessions": sessions_service.list_all()}


@router.get("/api/sessions/{session_id}/messages")
async def session_messages(session_id: str) -> dict[str, Any]:
    return {"messages": sessions_service.messages_for(session_id)}


@router.get("/api/sessions/{session_id}/attachments/{filename}")
async def session_attachment(session_id: str, filename: str) -> FileResponse:
    session = sessions_service.get_by_id(session_id)
    if session is None:
        raise BoppaiError("Session not found", status=404)

    path = attachments_service.attachment_file(session, filename)
    if path is None:
        raise BoppaiError("Attachment not found", status=404)

    return FileResponse(path)
