"""
Lazy per-day meal details -- ingredients + nutrition for the dishes on one day.

The calendar stores only name + calories + servings up front (cheap; the conductor
writes them when it builds the plan). Everything heavier -- the ingredient list with
quantities, the macro breakdown, and YouTube recipe videos -- is generated the FIRST
time a user opens that day's card, then cached back into calendar.json so re-opening is
instant. This module owns that one real agent call.

Batching: the same dish name in two slots on the same day is ONE cooked batch.
`servings` is the batch SIZE (not per-slot consumption), so slots that share a dish carry
the same number. We group a day's meals by dish name, take that batch size ONCE (the max
across its slots, robust to a sloppy 1-vs-2), ask for the whole batch's ingredient
quantities, then write the one list to every shared slot. That way "cook once, eat lunch
+ dinner" is never double-counted. Nutrition is asked per single serving
(calories/macros describe one plate).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..agents.base import AgentDef
from .calendar import is_youtube_video_url
from .oneshot import extract_json, spawn_one_shot

MEALS = ["breakfast", "lunch", "dinner"]


def pending_for_day(day_obj: Any, force: bool = False) -> list[dict[str, Any]]:
    """Which of a day's dishes still need lazy details, as [{meal, name, servings}].

    The rule that matters: when ANY slot of a shared dish is missing ingredients, we
    pull the WHOLE dish-group in (every slot with that name), so a cook-once dish
    regenerates together and both cards land one consistent batch list. Returns an empty
    list when the day is already fully generated. Shared by the /details route (one day,
    on open) and the grocery-list consolidator (every day).
    """
    day_obj = day_obj if isinstance(day_obj, dict) else {}
    named = [meal for meal in MEALS if (day_obj.get(meal) or {}).get("name")]

    def entry(meal: str) -> dict[str, Any]:
        dish = day_obj[meal]
        return {"meal": meal, "name": dish["name"], "servings": dish.get("servings") or 1}

    if force:
        return [entry(meal) for meal in named]

    stale_names = {
        day_obj[meal]["name"]
        for meal in named
        if not isinstance(day_obj[meal].get("ingredients"), list)
    }
    return [entry(meal) for meal in named if day_obj[meal]["name"] in stale_names]


def group_by_dish(meals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse slots into one entry per distinct dish.

    `servings` is the batch SIZE shared across the slots, so take it ONCE (the max
    guards against an inconsistent 1-vs-2 from the model) rather than summing --
    summing would double-count a cook-once dish.
    """
    by_name: dict[str, dict[str, Any]] = {}
    for meal in meals:
        raw = meal.get("servings")
        servings = raw if isinstance(raw, int) and raw > 0 else 1
        group = by_name.setdefault(meal["name"], {"name": meal["name"], "servings": 1, "mealKeys": []})
        group["servings"] = max(group["servings"], servings)
        group["mealKeys"].append(meal["meal"])
    return list(by_name.values())


def build_prompt(dishes: list[dict[str, Any]]) -> str:
    """`dishes` is [{name, servings}] -- one entry per distinct dish, batch size taken once."""
    listing = "\n".join(
        f"- {dish['name']} (cook a batch of {dish['servings']} "
        f"serving{'s' if dish['servings'] > 1 else ''})"
        for dish in dishes
    )
    return "\n".join(
        [
            "You are a nutrition and grocery assistant. For each dish below, list the raw",
            "ingredients needed to cook the FULL batch of the given number of servings (with",
            "short, human quantities), estimate the nutrition for ONE single serving, and",
            "include 2-3 useful YouTube recipe videos for that dish.",
            "",
            "For youtubeVideos, include only real YouTube watch links from youtube.com or",
            "youtu.be. Do not include generic search links, blogs, Instagram, TikTok, or",
            "non-YouTube URLs.",
            "",
            "Dishes:",
            listing,
            "",
            "Respond with ONLY a JSON object - no prose, no code fences - mapping each dish",
            "name EXACTLY as written above to its details, in this shape:",
            "{",
            '  "<dish name>": {',
            '    "ingredients": [{ "name": "Onion", "quantity": "2 medium" }],',
            '    "nutrition": { "protein": "12 g", "carbs": "45 g", "fat": "8 g", "fiber": "6 g" },',
            '    "youtubeVideos": [{ "title": "Recipe video title", "url": "https://www.youtube.com/watch?v=VIDEO_ID" }]',
            "  }",
            "}",
        ]
    )


def shape_entry(entry: Any) -> dict[str, Any]:
    """Sanitize one dish's generated detail into the shape the calendar stores."""
    if not isinstance(entry, dict):
        return {"ingredients": [], "nutrition": None, "youtubeVideos": []}

    raw_ingredients = entry.get("ingredients")
    ingredients = (
        [
            item
            for item in (
                {
                    "name": str((raw or {}).get("name") or "").strip(),
                    "quantity": str((raw or {}).get("quantity") or "").strip(),
                }
                for raw in raw_ingredients
                if isinstance(raw, dict) or raw is None
            )
            if item["name"]
        ]
        if isinstance(raw_ingredients, list)
        else []
    )

    raw_nutrition = entry.get("nutrition")
    nutrition = (
        {
            "protein": str(raw_nutrition.get("protein") or "").strip(),
            "carbs": str(raw_nutrition.get("carbs") or "").strip(),
            "fat": str(raw_nutrition.get("fat") or "").strip(),
            "fiber": str(raw_nutrition.get("fiber") or "").strip(),
        }
        if isinstance(raw_nutrition, dict)
        else None
    )

    raw_videos = entry.get("youtubeVideos")
    videos = (
        [
            video
            for video in (
                {
                    "title": str((raw or {}).get("title") or "").strip(),
                    "url": str((raw or {}).get("url") or "").strip(),
                }
                for raw in raw_videos
                if isinstance(raw, dict) or raw is None
            )
            if video["url"] and is_youtube_video_url(video["url"])
        ]
        if isinstance(raw_videos, list)
        else []
    )

    return {"ingredients": ingredients, "nutrition": nutrition, "youtubeVideos": videos}


_BATCH_SUFFIX_RE = re.compile(r"\s*\(cook a batch of .*?\)\s*$", re.IGNORECASE)


def _lookup_entry(parsed: dict[str, Any], name: str) -> Any:
    """Find a dish's entry in the model's reply, tolerating how it echoed the key.

    The prompt lists each dish as "- Oats (cook a batch of 1 serving)" and asks for keys
    "EXACTLY as written above", which the model reads two ways: sometimes the bare dish
    name, sometimes the whole bullet including the batch parenthetical. A strict
    `parsed[name]` lookup therefore misses intermittently and the day's card silently
    renders with no ingredients at all.

    (The Node build had the same strict lookup and the same intermittent empty cards --
    this is a latent bug carried over from it, fixed here rather than reproduced.)
    """
    if not isinstance(parsed, dict):
        return None

    if name in parsed:
        return parsed[name]

    # Strip the batch suffix off the model's keys and match on the dish name alone.
    for key, value in parsed.items():
        if not isinstance(key, str):
            continue
        if _BATCH_SUFFIX_RE.sub("", key).strip().casefold() == name.strip().casefold():
            return value

    return None


def fan_out(dishes: list[dict[str, Any]], parsed: dict[str, Any]) -> dict[str, Any]:
    """Fan the one per-dish result back out to every slot that dish fills."""
    out: dict[str, Any] = {}
    for dish in dishes:
        shaped = shape_entry(_lookup_entry(parsed or {}, dish["name"]))
        for meal_key in dish["mealKeys"]:
            out[meal_key] = shaped
    return out


async def generate_day_details(
    agent: AgentDef, meals: list[dict[str, Any]], *, cwd: Path | str
) -> dict[str, Any]:
    """Generate details for the slots that still need them.

    `meals` is [{meal, name, servings}]. Returns
    {meal: {ingredients: [{name, quantity}], nutrition: {...}|None, youtubeVideos: [...]}},
    with slots that share a dish name receiving the same batch-scaled list.
    """
    if not meals:
        return {}

    dishes = group_by_dish(meals)
    raw = await spawn_one_shot(agent, build_prompt(dishes), cwd=cwd)
    parsed = extract_json(raw)
    return fan_out(dishes, parsed)
