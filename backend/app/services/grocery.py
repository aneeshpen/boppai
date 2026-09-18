"""
Whole-calendar grocery list -- consolidate every planned day's ingredients into one
combined shopping list.

The flow, and why each step is shaped this way:

1. ENSURE GENERATED. Ingredients are lazy (generated on card-open), so most days won't
   have them yet. We find every non-disabled day with pending dishes and generate them,
   reusing the exact same per-day path the card uses (`pending_for_day` +
   `generate_day_details`) so the batch rules stay identical. The agent calls run
   bounded-parallel (each is a CLI subprocess -- don't fan out unbounded); the
   `set_day_details` writes run SEQUENTIALLY afterward because each rewrites the whole
   calendar.json and parallel writes would clobber each other.

2. DEDUP BY COOK-EVENT, NOT BY SLOT. This is the crux. `servings` models "cook once, eat
   twice": a batch that feeds lunch + dinner is the SAME dish name in both slots, and
   generation writes the SAME whole-batch ingredient list into each. So walking every
   slot and summing would double-count that batch. We dedup by (week, day, dish name) --
   one batch per cook-event -- and take its list once. The batch quantity is already
   baked into the stored list, so `servings` never enters the math here. Different days =
   different cook-events, counted separately.

3. MERGE. One agent call reconciles duplicate ingredient lines across all batches into
   sensible combined quantities (the fuzzy "2 onions + 200 g onion" part). A naive code
   merge is the fallback if the model's JSON can't be parsed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..agents.base import AgentDef
from ..core.logging import get_logger
from ..models.session import Session
from ..persistence import files
from . import calendar as calendar_service
from .ingredients import MEALS, generate_day_details, pending_for_day
from .oneshot import extract_json, spawn_one_shot

log = get_logger("grocery")

# How many day-generation agent calls to run at once. Each spawns the user's CLI, so keep
# it modest.
CONCURRENCY = 3


def ingredient_list_path(session: Session) -> Path:
    """The consolidated ingredient list lives here -- the shopping list the Basket is
    filled from. Named "ingredient-list" (not "grocery-list") because that is what it
    is: the whole plan's ingredients merged into buy-once quantities, before any product
    lookup."""
    return session.folder / "ingredient-list.json"


def read_ingredient_list(session: Session) -> list[dict[str, Any]]:
    """The saved consolidated ingredient list ([{name, quantity, category}]), or []."""
    try:
        parsed = files.read_json(ingredient_list_path(session))
    except ValueError:
        return []
    if not isinstance(parsed, dict):
        return []
    items = parsed.get("items")
    return items if isinstance(items, list) else []


async def _map_limit(
    items: list[Any], limit: int, fn: Callable[[Any], Awaitable[Any]]
) -> list[Any]:
    """Minimal bounded-parallel map -- run `fn` over `items` at most `limit` at a time."""
    if not items:
        return []
    semaphore = asyncio.Semaphore(limit)

    async def guarded(item: Any) -> Any:
        async with semaphore:
            return await fn(item)

    return list(await asyncio.gather(*(guarded(item) for item in items)))


def _build_consolidate_prompt(flat: list[dict[str, Any]]) -> str:
    listing = "\n".join(
        f"- {item['name']}" + (f" - {item['quantity']}" if item.get("quantity") else "")
        for item in flat
    )
    return "\n".join(
        [
            "You are a grocery assistant. Below is a combined list of ingredients pulled from",
            "a full meal plan - the SAME ingredient often appears several times with different",
            "units. Merge duplicates into ONE line each, summing/reconciling their quantities",
            "into a single sensible shopping quantity (e.g. round to how you would actually buy",
            "it). Keep names simple and shopping-friendly. Do NOT add anything not listed.",
            "",
            'Also CLASSIFY each merged item with a "category":',
            '- "basket" - fresh / perishable / frequently re-bought items you get most grocery',
            "             runs: vegetables, fruits, dairy, eggs, meat, fish, paneer, bread,",
            "             fresh herbs, tofu.",
            '- "pantry" - long shelf-life staples most kitchens keep stocked and rarely re-buy:',
            "             cooking oil, ghee, butter, salt, sugar, flour/atta, rice, lentils/dal,",
            "             spices & whole/ground masalas, sauces, vinegar, honey, baking staples.",
            'When unsure, default to "basket".',
            "",
            "Ingredients:",
            listing,
            "",
            "Respond with ONLY a JSON object - no prose, no code fences - in this shape:",
            '{ "items": [{ "name": "Onion", "quantity": "1 kg", "category": "basket" }] }',
        ]
    )


def _shape_items(items: Any) -> list[dict[str, Any]]:
    shaped = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        shaped.append(
            {
                "name": name,
                "quantity": str(item.get("quantity") or "").strip(),
                # Long shelf-life staples go to the pantry group; everything else is the
                # Basket.
                "category": "pantry" if item.get("category") == "pantry" else "basket",
            }
        )
    return shaped


def naive_merge(flat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback when the agent's JSON can't be parsed: group by name (case-insensitive)
    and string-join the quantities. Not smart about units, but never loses an item."""
    by_name: dict[str, dict[str, Any]] = {}
    for item in flat:
        key = item["name"].lower()
        existing = by_name.get(key)
        if existing:
            if item.get("quantity"):
                existing["quantity"] = (
                    f"{existing['quantity']} + {item['quantity']}"
                    if existing["quantity"]
                    else item["quantity"]
                )
        else:
            # The fallback path can't classify intelligently -- default everything to the
            # Basket so nothing is hidden in the pantry group by accident.
            by_name[key] = {
                "name": item["name"],
                "quantity": item.get("quantity") or "",
                "category": "basket",
            }
    return list(by_name.values())


async def _consolidate(
    agent: AgentDef, flat: list[dict[str, Any]], cwd: Path
) -> list[dict[str, Any]]:
    raw = await spawn_one_shot(agent, _build_consolidate_prompt(flat), cwd=cwd)
    items = _shape_items(extract_json(raw).get("items"))
    return items if items else naive_merge(flat)


async def build_grocery_list(
    session: Session, agent: AgentDef
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build (or rebuild) the grocery list for the WHOLE calendar.

    Returns (items, calendar) -- the calendar being the now-complete one, with any
    newly-generated day details cached in.
    """
    exists, current = calendar_service.read(session)
    if not exists or current is None:
        raise ValueError("No calendar exists for this session yet")

    # 1. Find every non-disabled day that still needs details, then generate.
    pending_days = []
    for week in current["weeks"]:
        for day in week["days"]:
            if day.get("disabled"):
                continue
            pending = pending_for_day(day)
            if pending:
                pending_days.append({"weekId": week["id"], "day": day["day"], "pending": pending})

    async def generate(entry: dict[str, Any]) -> dict[str, Any] | None:
        try:
            details = await generate_day_details(agent, entry["pending"], cwd=session.folder)
            return {**entry, "detailsByMeal": details}
        except Exception as exc:  # noqa: BLE001 - one bad day must not sink the run
            log.info("[grocery] day details failed for %s: %s", entry["day"], exc)
            return None

    generated = await _map_limit(pending_days, CONCURRENCY, generate)

    # Writes are sequential on purpose (each rewrites the whole calendar.json).
    for entry in generated:
        if entry and entry.get("detailsByMeal"):
            calendar_service.set_day_details(
                session, entry["weekId"], entry["day"], entry["detailsByMeal"]
            )

    # 2. Re-read the now-complete calendar and flatten, one batch per (day, dish).
    _, current = calendar_service.read(session)
    assert current is not None

    flat: list[dict[str, Any]] = []
    for week in current["weeks"]:
        for day in week["days"]:
            if day.get("disabled"):
                continue
            taken_dishes: set[str] = set()  # one cook-event per dish name per day
            for meal in MEALS:
                dish = day.get(meal)
                if not dish or not dish.get("name") or dish["name"] in taken_dishes:
                    continue
                ingredients = dish.get("ingredients")
                if not isinstance(ingredients, list) or not ingredients:
                    continue
                taken_dishes.add(dish["name"])
                flat.extend(ingredients)

    # 3. Merge duplicate lines into combined quantities, then save.
    items: list[dict[str, Any]] = []
    if flat:
        try:
            items = await _consolidate(agent, flat, session.folder)
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail the request
            log.info("[grocery] consolidation failed, using naive merge: %s", exc)
            items = naive_merge(flat)

    files.write_json(ingredient_list_path(session), {"items": items})

    return items, current
