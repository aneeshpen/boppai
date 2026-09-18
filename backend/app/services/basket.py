"""
Per-session Basket state.

The Basket is deliberately lazy: sessions do not get a basket.json until something
writes one (the fill run or an agent's show_basket call). The browser reads it through
routes; the show_basket MCP tool writes it through the same backend path, so there is a
single normalizing writer.

A Basket item is one shopping line: the ingredient it fulfills, whether a product was
found, and -- when found -- the chosen product plus how many packs to buy. basket.json
is just `{"items": [...]}`; the UI derives its "still processing" and "not found" groups
from these items (see the frontend BasketBoard), so no UI flags live on disk.

NOTE: this is the app-side Basket only -- NOT the user's real Swiggy/Zepto cart. That
store cart is a separate thing, managed by the grocery service's own tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models.session import Session
from ..persistence import files

_PRODUCT_KEYS = ("packSize", "price", "rating", "imageUrl", "productId")


def basket_path(session: Session) -> Path:
    return session.folder / "basket.json"


def _clean_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _opt_string(value: Any) -> str | None:
    """A trimmed string, or None when empty/missing -- used for optional fields so an
    empty value never survives onto disk."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalize_product(value: Any) -> dict[str, str] | None:
    """The chosen product for a found line.

    `name` is required; everything else is best-effort from a live search, so we keep
    whatever fields came back.
    """
    if not isinstance(value, dict):
        return None
    name = _opt_string(value.get("name"))
    if not name:
        return None

    product: dict[str, str] = {"name": name}
    for key in _PRODUCT_KEYS:
        found = _opt_string(value.get(key))
        if found:
            product[key] = found
    return product


def _normalize_item(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"items[{index}] must be an object")

    item: dict[str, Any] = {
        "ingredient": _clean_string(value.get("ingredient"), f"items[{index}].ingredient")
    }
    quantity = _opt_string(value.get("quantity"))
    if quantity:
        item["quantity"] = quantity

    # A line is "found" only if it actually carries a usable product; a "found" marker
    # with no product is downgraded to not_found so the UI stays honest.
    product = None if value.get("status") == "not_found" else _normalize_product(value.get("product"))
    if product:
        item["status"] = "found"
        item["product"] = product
        try:
            count = int(float(value.get("count")))
        except (TypeError, ValueError):
            count = 0
        item["count"] = count if count > 0 else 1
    else:
        item["status"] = "not_found"

    return item


def normalize_basket(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("basket must be an object")
    if not isinstance(value.get("items"), list):
        raise ValueError("items must be an array")

    return {"items": [_normalize_item(item, i) for i, item in enumerate(value["items"])]}


def read(session: Session) -> tuple[bool, dict[str, Any] | None]:
    """Returns (exists, basket)."""
    raw = files.read_json(basket_path(session))
    if raw is None:
        return False, None
    return True, normalize_basket(raw)


def write(session: Session, basket: Any) -> dict[str, Any]:
    normalized = normalize_basket(basket)
    session.folder.mkdir(parents=True, exist_ok=True)
    files.write_json(basket_path(session), normalized)
    return normalized


def set_count(session: Session, ingredient: Any, count: Any) -> dict[str, Any]:
    """Direct UI edit: set how many packs of a found item to buy (min 1).

    Matches a line by its ingredient name.
    """
    exists, current = read(session)
    if not exists or current is None:
        raise ValueError("No basket exists for this session yet")

    target = _clean_string(ingredient, "ingredient")
    try:
        parsed = int(float(count))
    except (TypeError, ValueError):
        parsed = 1
    next_count = max(1, parsed or 1)

    found = False
    items: list[dict[str, Any]] = []
    for item in current["items"]:
        if item["ingredient"] != target or item["status"] != "found":
            items.append(item)
            continue
        found = True
        items.append({**item, "count": next_count})

    if not found:
        raise ValueError(f'Basket item "{target}" was not found')

    return write(session, {"items": items})


def remove_item(session: Session, ingredient: Any) -> dict[str, Any]:
    """Direct UI edit: drop a line from the basket by ingredient name."""
    exists, current = read(session)
    if not exists or current is None:
        raise ValueError("No basket exists for this session yet")

    target = _clean_string(ingredient, "ingredient")
    items = [item for item in current["items"] if item["ingredient"] != target]
    return write(session, {"items": items})
