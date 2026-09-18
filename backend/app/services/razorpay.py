"""
Razorpay test-mode payments, via Payment Links.

Why Payment Links rather than an embedded checkout: Boppai never sees a card. The agent
creates a link, hands the user the URL, and the user pays on Razorpay's own hosted page.
That keeps the whole rail free (test keys move no money), needs no frontend SDK, and means
there is no PAN, CVV or token anywhere in this process to leak or log.

Amounts: Razorpay works in the smallest currency unit, so rupees are converted to paise as
an integer. `"119.00"` -> `11900`. Getting this wrong by 100x is the classic bug here, so
conversion lives in one tested function.
"""

from __future__ import annotations

import base64
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger("razorpay")

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class RazorpayError(Exception):
    def __init__(self, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def is_configured() -> bool:
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


def is_test_mode() -> bool:
    """Test keys are prefixed `rzp_test_`; live keys are `rzp_live_`."""
    return settings.razorpay_key_id.startswith("rzp_test_")


def require_config() -> None:
    if not is_configured():
        raise RazorpayError(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are missing. Add your rzp_test_* keys "
            "to backend/.env.",
            status=500,
        )


def to_paise(amount: Any) -> int:
    """Rupee string/number -> integer paise. `"119.00"` -> `11900`."""
    try:
        rupees = Decimal(str(amount).strip())
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise RazorpayError(f'totalAmount must be a decimal amount, got {amount!r}') from exc
    if rupees <= 0:
        raise RazorpayError("totalAmount must be greater than zero")
    return int((rupees * 100).quantize(Decimal("1")))


def _auth_header() -> str:
    raw = f"{settings.razorpay_key_id}:{settings.razorpay_key_secret}".encode()
    return f"Basic {base64.b64encode(raw).decode()}"


async def _request(method: str, path: str, json_body: Any = None) -> dict[str, Any]:
    require_config()
    url = f"{settings.razorpay_api_url.rstrip('/')}{path}"

    log.info("[Razorpay] request %s %s", method, path)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.request(
                method,
                url,
                headers={"Authorization": _auth_header(), "Content-Type": "application/json"},
                json=json_body,
            )
    except httpx.HTTPError as exc:
        log.info("[Razorpay] transport error on %s: %s", path, exc)
        raise RazorpayError(str(exc) or "Razorpay request failed") from exc

    try:
        data = response.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    log.info("[Razorpay] response %s %s -> %s", method, path, response.status_code)

    if not response.is_success:
        message = (data.get("error") or {}).get("description") or (
            f"Razorpay request failed (HTTP {response.status_code})"
        )
        raise RazorpayError(message, status=response.status_code)

    return data


def _line_items(products: Any, fallback_description: str) -> list[dict[str, Any]]:
    """Cart lines, kept only as `notes` — Razorpay Payment Links don't itemize, but
    carrying them makes the dashboard entry readable and aids reconciliation."""
    lines = []
    for product in products if isinstance(products, list) else []:
        if not isinstance(product, dict):
            continue
        description = str(product.get("description") or product.get("name") or "").strip()
        if not description:
            continue
        quantity = product.get("quantity") or 1
        lines.append({"description": description, "quantity": quantity})
    return lines or [{"description": fallback_description, "quantity": 1}]


async def create_payment_link(
    *,
    total_amount: Any,
    description: str,
    currency: str = "INR",
    products: Any = None,
    customer_email: str | None = None,
    callback_url: str | None = None,
) -> dict[str, Any]:
    """Create a Payment Link and return the bits the agent and UI need."""
    amount_paise = to_paise(total_amount)
    lines = _line_items(products, description)

    payload: dict[str, Any] = {
        "amount": amount_paise,
        "currency": currency or "INR",
        "description": description[:255],
        "accept_partial": False,
        "reminder_enable": False,
        # Boppai has no verified sender identity, so let Razorpay's page do the talking
        # rather than firing SMS/email at the user.
        "notify": {"sms": False, "email": False},
        "notes": {
            "source": "boppai",
            "items": "; ".join(f"{line['description']} x{line['quantity']}" for line in lines)[:490],
        },
    }
    if customer_email:
        payload["customer"] = {"email": customer_email}
    if callback_url:
        payload["callback_url"] = callback_url
        payload["callback_method"] = "get"

    data = await _request("POST", "/v1/payment_links", payload)

    return {
        "id": data.get("id"),
        "shortUrl": data.get("short_url"),
        "status": data.get("status"),
        "amount": data.get("amount"),
        "currency": data.get("currency"),
        "description": data.get("description"),
        "testMode": is_test_mode(),
    }


async def fetch_payment_link(link_id: str) -> dict[str, Any]:
    """Current state of a Payment Link. `status` is created|partially_paid|expired|cancelled|paid."""
    if not isinstance(link_id, str) or not link_id.strip():
        raise RazorpayError("payment link id is required", status=400)

    data = await _request("GET", f"/v1/payment_links/{link_id.strip()}")
    return {
        "id": data.get("id"),
        "status": data.get("status"),
        "amountPaid": data.get("amount_paid"),
        "amount": data.get("amount"),
        "currency": data.get("currency"),
        "shortUrl": data.get("short_url"),
        "paid": data.get("status") == "paid",
        "testMode": is_test_mode(),
    }
