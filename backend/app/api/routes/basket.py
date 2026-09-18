"""
Active-session Basket endpoints.

  GET   /api/session/basket          -> read the current session's Basket, if any
  PATCH /api/session/basket          -> direct UI edits: set_count / remove
  GET   /api/session/ingredient-list -> the consolidated shopping list (for the
                                        Basket's "still processing" group)
  POST  /api/session/basket/fill     -> SSE: run the fill agent that sources each
                                        to-buy ingredient and calls show_basket
  POST  /api/session/basket/source-item -> SSE: source one item + upsert into the Basket
                                        (promote a pantry staple, or retry a miss)
  GET/POST /internal/basket          -> MCP-facing read/write for show_basket

The "Basket" here is the app-side canvas only -- NOT the user's real Swiggy/Zepto cart.
That store cart is managed separately by the grocery service's own tools.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...agents import registry
from ...agents.base import ChatArgs
from ...agents.runner import stream_agent_events
from ...core.config import BASKET_FILL_PROMPT
from ...core.deps import json_body
from ...core.errors import BoppaiError
from ...mcp.servers import (
    mcp_config_path_for_provider,
    mcp_servers_for_provider,
    provider_label,
)
from ...models.session import Session
from ...services import basket as basket_service
from ...services import grocery as grocery_service
from ...services import profile as profile_service
from ...services import sessions as sessions_service
from ...services import settings as settings_service
from ...sse import Event, sse_response

router = APIRouter()


def _active() -> Session:
    return sessions_service.get_or_create_active()


def _payload(session: Session) -> dict[str, Any]:
    exists, basket = basket_service.read(session)
    return {"exists": exists, "basket": basket}


@router.get("/api/session/basket")
async def get_basket() -> dict[str, Any]:
    return _payload(_active())


@router.get("/api/session/ingredient-list")
async def get_ingredient_list() -> dict[str, Any]:
    return {"items": grocery_service.read_ingredient_list(_active())}


@router.patch("/api/session/basket")
async def patch_basket(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    """Direct UI edits -- the +/- stepper and the X on a Basket card.

    These are the Basket's twin of the calendar's clear_day/select_week: small mutations
    the browser makes without going through the agent.
    """
    action = body.get("action")
    session = _active()

    try:
        if action == "set_count":
            updated = basket_service.set_count(session, body.get("ingredient"), body.get("count"))
        elif action == "remove":
            updated = basket_service.remove_item(session, body.get("ingredient"))
        else:
            raise BoppaiError("action must be set_count or remove")
        sessions_service.set_active_surface(session.id, "basket")
        return {"exists": True, "basket": updated}
    except ValueError as exc:
        raise BoppaiError(str(exc)) from exc


@router.get("/internal/basket")
async def internal_get_basket() -> dict[str, Any]:
    return _payload(_active())


@router.post("/internal/basket")
async def internal_post_basket(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    session = _active()
    try:
        updated = basket_service.write(session, {"items": body.get("items")})
    except ValueError as exc:
        raise BoppaiError(str(exc)) from exc
    sessions_service.set_active_surface(session.id, "basket")
    return {"ok": True, "basket": updated}


# --- the fill agent --------------------------------------------------------


def _format_item_lines(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{index + 1}. {item['name']}"
        + (f" — need {item['quantity']}" if item.get("quantity") else "")
        for index, item in enumerate(items)
    )


def _build_fill_prompt(items: list[dict[str, Any]], provider: str) -> str:
    """The bulk fill task: source the whole to-buy list into the Basket.

    Seeded with the items so the agent does not have to read the ingredient list file.
    """
    return "\n".join(
        [
            f"Fill the Basket from this shopping list using {provider_label(provider)}.",
            "",
            "Ingredients to source:",
            _format_item_lines(items),
        ]
    )


def _build_source_item_prompt(item: dict[str, Any], provider: str) -> str:
    """Source ONE item and upsert it into the Basket.

    Used both to promote a pantry staple and to retry a not-found item. The agent reads
    basket.json, keeps everything else, and replaces this ingredient's line if it already
    exists (else adds it).
    """
    return "\n".join(
        [
            f"Source ONE item and add it to the existing Basket using {provider_label(provider)}.",
            "",
            "Item to source:",
            _format_item_lines([item]),
            "",
            "Read basket.json first and keep every OTHER item exactly as it is. If a line for this",
            "same ingredient already exists (for example one marked not_found), REPLACE that line",
            "with the result; otherwise add it. Then call show_basket with the full updated Basket.",
        ]
    )


def _build_fill_system_prompt(provider: str) -> str:
    """An ephemeral agent's brain = a focused prompt file + which provider it's on + the
    profile (so product picks respect diet/allergies). Deliberately NOT the conductor
    persona."""
    base = BASKET_FILL_PROMPT.read_text(encoding="utf-8")
    label = provider_label(provider)
    provider_note = (
        "\n\n---\n## Connected grocery service\n\n"
        f"Use **{label}**'s product search tool ONLY. "
        "Do not use or mention any other grocery service."
    )
    saved = profile_service.read()
    profile_note = (
        "\n\n---\n## The user's saved profile (respect diet/allergies when picking products)"
        f"\n\n{saved.markdown}"
        if saved.exists
        else ""
    )
    return base + provider_note + profile_note


def _fill_events(session: Session, prompt: str, provider: str) -> AsyncIterator[Event]:
    """Run the fill agent and stream its events to the browser.

    This is a SEPARATE, ephemeral agent from the conductor: it has the provider + boppai
    MCP (so it can search and call show_basket) but does NOT resume the conversation and
    does NOT persist anything -- persisting its runtime id would clobber the conductor's
    resume handle. show_basket calls write basket.json through /internal/basket just like
    any other turn, so the Basket fills in as the agent works.
    """
    agent = registry.get_or_default(session.agent)
    argv = agent.build_chat_args(
        ChatArgs(
            # No session ids -> fresh ephemeral runtime. The MCP wiring still gives it
            # the boppai + provider tools, so this run CAN search and call show_basket.
            mcp_config_path=str(mcp_config_path_for_provider(provider)),
            mcp_servers=mcp_servers_for_provider(provider),
            system_prompt=_build_fill_system_prompt(provider),
            model=agent.model,
            reasoning_effort=agent.reasoning_effort,
        )
    )

    async def generate() -> AsyncIterator[Event]:
        async for event in stream_agent_events(
            agent, argv, cwd=session.folder, prompt=agent.build_prompt(prompt, [])
        ):
            yield event
        yield {"type": "end"}

    return generate()


def _sse_error(message: str) -> StreamingResponse:
    """The Node routes reported these as SSE frames, not an HTTP error, because the
    browser has already committed to reading a stream by this point."""

    async def generate() -> AsyncIterator[Event]:
        yield {"type": "error", "message": message}
        yield {"type": "end"}

    return sse_response(generate())


@router.post("/api/session/basket/fill")
async def basket_fill() -> StreamingResponse:
    """Bulk fill: source the whole to-buy (perishable) list into the Basket.

    Pantry staples are left out -- they show as tags the user can promote one at a time
    via /source-item.
    """
    session = _active()
    provider = settings_service.get_provider()
    items = [
        item
        for item in grocery_service.read_ingredient_list(session)
        if (item.get("category") or "basket") != "pantry"
    ]

    if not items:
        return _sse_error("No ingredient list to fill from yet.")

    return sse_response(_fill_events(session, _build_fill_prompt(items, provider), provider))


@router.post("/api/session/basket/source-item")
async def basket_source_item(body: dict[str, Any] = Depends(json_body)) -> StreamingResponse:
    """Source one item on demand and upsert it into the Basket.

    Both the + on a pantry staple tag and the retry on a not-found tag hit this -- it
    searches just that one item.
    """
    session = _active()
    provider = settings_service.get_provider()
    raw = body.get("ingredient")
    name = raw.strip() if isinstance(raw, str) else ""

    if not name:
        return _sse_error("ingredient is required.")

    # Pull the needed quantity from the saved list when we recognize the name.
    listed = next(
        (
            item
            for item in grocery_service.read_ingredient_list(session)
            if str(item.get("name", "")).lower() == name.lower()
        ),
        None,
    )
    item = {
        "name": (listed or {}).get("name") or name,
        "quantity": (listed or {}).get("quantity") or "",
    }

    return sse_response(_fill_events(session, _build_source_item_prompt(item, provider), provider))
