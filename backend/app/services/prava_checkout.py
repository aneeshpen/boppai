"""
Per-session Prava checkout intent.

This is the bridge between an agent tool call and the browser UI. The tool can start a
Prava session server-side, while the frontend can later read the session-scoped iframe
URL and payment context without relying on tool results being present in the SSE stream.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.session import Session
from ..persistence import files

_AMOUNT_RE = re.compile(r"^\d+(\.\d{1,2})?$")


def checkout_path(session: Session) -> Path:
    return session.folder / "prava-checkout.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clean_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _opt_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clean_amount(value: Any) -> str:
    text = _clean_string("" if value is None else str(value), "totalAmount")
    if not _AMOUNT_RE.match(text):
        raise ValueError('totalAmount must be a decimal string, e.g. "119.00"')
    return f"{float(text):.2f}"


def _normalize_product(value: Any, index: int, total_amount: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"products[{index}] must be an object")

    description = _clean_string(
        value.get("description") or value.get("name"), f"products[{index}].description"
    )
    unit_price = (
        _opt_string(value.get("unitPrice"))
        or _opt_string(value.get("unit_price"))
        or _opt_string(value.get("price"))
        or total_amount
    )
    try:
        quantity = int(float(value.get("quantity") or 1))
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, quantity or 1)

    product: dict[str, Any] = {
        "description": description,
        "unitPrice": str(unit_price),
        "quantity": quantity,
    }
    product_id = _opt_string(value.get("productId")) or _opt_string(value.get("product_id"))
    if product_id:
        product["productId"] = product_id
    return product


def normalize_intent(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("checkout intent must be an object")

    total_amount = _clean_amount(value.get("totalAmount") or value.get("total_amount"))
    currency = _opt_string(value.get("currency")) or "INR"

    raw_products = value.get("products")
    if isinstance(raw_products, list) and raw_products:
        products = [
            _normalize_product(product, index, total_amount)
            for index, product in enumerate(raw_products)
        ]
    else:
        products = [
            {
                "description": _opt_string(value.get("description"))
                or "Swiggy Instamart order",
                "unitPrice": total_amount,
                "quantity": 1,
            }
        ]

    return {
        "status": _opt_string(value.get("status")) or "creating",
        "totalAmount": total_amount,
        "currency": currency,
        "description": _opt_string(value.get("description"))
        or f"Swiggy Instamart payment for {total_amount} {currency}",
        "merchantName": _opt_string(value.get("merchantName")) or "Swiggy Instamart",
        "merchantUrl": _opt_string(value.get("merchantUrl")) or "https://www.swiggy.com/",
        "countryCode": _opt_string(value.get("countryCode")) or "IN",
        "products": products,
        "createdAt": _opt_string(value.get("createdAt")) or _now(),
        "updatedAt": _now(),
    }


def read(session: Session) -> tuple[bool, dict[str, Any] | None]:
    """Returns (exists, checkout)."""
    raw = files.read_json(checkout_path(session))
    if raw is None:
        return False, None
    return True, raw


def write(session: Session, checkout: dict[str, Any]) -> dict[str, Any]:
    session.folder.mkdir(parents=True, exist_ok=True)
    # JSON.stringify drops keys whose value is undefined; mirror that so a cleared
    # error never lingers in the file.
    cleaned = {key: value for key, value in checkout.items() if value is not None}
    files.write_json(checkout_path(session), cleaned)
    return cleaned


def start(session: Session, intent: Any) -> dict[str, Any]:
    payload = dict(intent) if isinstance(intent, dict) else {}
    payload["status"] = "creating"
    return write(session, normalize_intent(payload))


def mark_ready(
    session: Session, current: dict[str, Any], prava_session: dict[str, Any]
) -> dict[str, Any]:
    return write(
        session,
        {
            **current,
            "status": "ready",
            "session": prava_session,
            "error": None,  # dropped by write(), matching `error: undefined`
            "updatedAt": _now(),
        },
    )


def mark_error(session: Session, current: dict[str, Any], message: str | None) -> dict[str, Any]:
    return write(
        session,
        {
            **current,
            "status": "error",
            "error": message or "Failed to create Prava checkout",
            "updatedAt": _now(),
        },
    )
