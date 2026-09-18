"""
Active-session meal planner endpoints.

  GET   /api/session/calendar  -> read the current session's planner, if any
  PATCH /api/session/calendar  -> V1 manual edits: clear one day / select a week
  GET/POST /internal/calendar  -> MCP-facing read/write for show_calendar

The lazy day-details and whole-plan grocery-list endpoints live here too once the
agent runtime is wired; they are the only routes in this file that spawn a CLI.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...agents import registry
from ...core.deps import json_body
from ...core.errors import BoppaiError
from ...models.session import Session
from ...core.logging import get_logger
from ...services import calendar as calendar_service
from ...services import sessions as sessions_service
from ...services.grocery import build_grocery_list
from ...services.ingredients import generate_day_details, pending_for_day

log = get_logger("calendar-routes")

router = APIRouter()


def _active() -> Session:
    return sessions_service.get_or_create_active()


def _payload(session: Session) -> dict[str, Any]:
    exists, calendar = calendar_service.read(session)
    return {"exists": exists, "calendar": calendar}


@router.get("/api/session/calendar")
async def get_calendar() -> dict[str, Any]:
    return _payload(_active())


@router.patch("/api/session/calendar")
async def patch_calendar(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    action = body.get("action")
    session = _active()

    try:
        if action == "clear_day":
            updated = calendar_service.clear_day(session, body.get("weekId"), body.get("day"))
        elif action == "select_week":
            updated = calendar_service.select_week(session, body.get("weekId"))
        else:
            raise BoppaiError("action must be clear_day or select_week")
        sessions_service.set_active_surface(session.id, "calendar")
        return {"exists": True, "calendar": updated}
    except ValueError as exc:
        raise BoppaiError(str(exc)) from exc


@router.get("/internal/calendar")
async def internal_get_calendar() -> dict[str, Any]:
    return _payload(_active())


@router.post("/internal/calendar")
async def internal_post_calendar(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    session = _active()
    try:
        updated = calendar_service.write(session, body)
    except ValueError as exc:
        raise BoppaiError(str(exc)) from exc
    sessions_service.set_active_surface(session.id, "calendar")
    return {"ok": True, "calendar": updated}


@router.post("/api/session/calendar/details")
async def calendar_details(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    """Lazily generate (and cache) ingredients + nutrition for one day's meals.

    This is the real agent call behind the day-detail card: idempotent -- meals that
    already have an `ingredients` array are skipped, so a re-open returns instantly.
    """
    week_id = body.get("weekId")
    day = body.get("day")
    force = body.get("force", False) is True

    try:
        session = _active()
        exists, current = calendar_service.read(session)
        if not exists or current is None:
            raise BoppaiError("No calendar exists for this session yet")

        week = next((item for item in current["weeks"] if item["id"] == week_id), None)
        if week is None:
            raise BoppaiError(f'Week "{week_id}" was not found')
        day_obj = next((item for item in week["days"] if item["day"] == day), None)
        if day_obj is None:
            raise BoppaiError(f'Day "{day}" was not found')

        # Which dishes still need details -- pulls the whole dish-group when any slot of
        # a cook-once dish is pending, so both cards regenerate to one consistent batch.
        pending = pending_for_day(day_obj, force=force)
        if not pending:
            return {"exists": True, "calendar": current}

        agent = registry.get_or_default(session.agent)
        details = await generate_day_details(agent, pending, cwd=session.folder)
        updated = calendar_service.set_day_details(session, week_id, day, details)
        return {"exists": True, "calendar": updated}
    except BoppaiError:
        raise
    except Exception as exc:  # noqa: BLE001 - Express returned 400 for any failure here
        log.info("[calendar] details failed: %s", exc)
        raise BoppaiError(str(exc) or "Failed to generate day details") from exc


@router.post("/api/session/calendar/grocery-list")
async def calendar_grocery_list() -> dict[str, Any]:
    """Consolidate the WHOLE calendar into one grocery list.

    Ensures every day's ingredients exist (generating the missing ones), dedups shared
    cook-once batches, merges quantities, and saves ingredient-list.json. Returns the
    consolidated items; the frontend then redirects to the Basket and fills it from this
    list. Can take a while when many days still need generating.
    """
    try:
        session = _active()
        agent = registry.get_or_default(session.agent)
        items, updated = await build_grocery_list(session, agent)
        return {"items": items, "calendar": updated}
    except Exception as exc:  # noqa: BLE001 - matches the Express catch -> 400
        log.info("[calendar] grocery list failed: %s", exc)
        raise BoppaiError(str(exc) or "Failed to build grocery list") from exc
