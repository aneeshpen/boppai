"""
Boppai MCP -- the tool catalog (single source of truth).

This is the ONE list of tools the agent can call. Add a new tool here and it shows up in
TWO places automatically:
  1. The MCP server (server.py) registers each entry so the CLI can call it.
  2. The backend serves the name/description of each at GET /api/tools, which the
     frontend "Tools" panel renders.

Keep entries plain and readable: a stable `name`, a human `title`, a `description` (what
the agent reads to decide when to call it -- this is also what users see in the UI), the
Pydantic-typed signature, and the handler that does the work.
`headless_approval="approve"` is a deliberate security allow-list for tools the
non-interactive CLIs may run without pausing. Do not copy it onto sensitive future tools
until their human-approval design is implemented.

The handlers call back into the Express-equivalent FastAPI backend over localhost so
there is a SINGLE write path both CLIs share (see server.py's header for the why). This
module runs inside the MCP subprocess, NOT the API process -- so it reads BOPPAI_API_URL
from the environment rather than importing app config.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel

from ..models.mcp_tools import BasketItem, CalendarUi, MerchantOutcome, PravaProduct, Week

API = os.environ.get("BOPPAI_API_URL") or "http://localhost:8787"

_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


def _dump(value: Any) -> Any:
    """Pydantic model (or list of them) -> plain JSON, with omitted fields left out.

    `exclude_none=True` matters: Zod stripped unknown keys and simply never emitted the
    optional ones, so this keeps the payload byte-comparable with the Node build.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value


async def _request(method: str, path: str, payload: Any = None) -> tuple[int, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.request(method, f"{API}{path}", json=payload)
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, (data if isinstance(data, dict) else {})


class ToolError(Exception):
    """Raised so the MCP SDK returns an isError result carrying this text."""


# --- profile ---------------------------------------------------------------


async def get_profile() -> str:
    status, data = await _request("GET", "/internal/profile")
    if data.get("exists"):
        return str(data.get("markdown") or "")
    return "(No profile saved yet — this user has not been onboarded.)"


async def save_profile(markdown: str) -> str:
    status, data = await _request("POST", "/internal/profile", {"markdown": markdown})
    if status >= 400:
        raise ToolError(f"Failed to save profile (HTTP {status}).")
    who = f" for {data['name']}" if data.get("name") else ""
    return f"Profile saved{who}."


# --- surfaces --------------------------------------------------------------


async def show_chat() -> str:
    status, data = await _request("POST", "/internal/surface", {"activeSurface": "chat"})
    if status >= 400:
        raise ToolError(data.get("error") or f"Failed to show chat (HTTP {status}).")
    return "Chat shown."


async def show_calendar(weeks: list[Week], ui: CalendarUi | None = None) -> str:
    status, data = await _request(
        "POST", "/internal/calendar", {"ui": _dump(ui), "weeks": _dump(weeks)}
    )
    if status >= 400:
        raise ToolError(data.get("error") or f"Failed to save calendar (HTTP {status}).")
    count = len((data.get("calendar") or {}).get("weeks") or [])
    return f"Calendar saved with {count} week(s)."


async def show_basket(items: list[BasketItem]) -> str:
    status, data = await _request("POST", "/internal/basket", {"items": _dump(items)})
    if status >= 400:
        raise ToolError(data.get("error") or f"Failed to save Basket (HTTP {status}).")
    count = len((data.get("basket") or {}).get("items") or [])
    return f"Basket updated with {count} item(s)."


# --- Prava -----------------------------------------------------------------


async def start_prava_checkout(
    totalAmount: str,
    currency: str | None = None,
    description: str | None = None,
    products: list[PravaProduct] | None = None,
) -> str:
    status, data = await _request(
        "POST",
        "/internal/prava/start-checkout",
        {
            "totalAmount": totalAmount,
            "currency": currency or "INR",
            "description": description or f"Swiggy Instamart payment for {totalAmount} INR",
            "products": _dump(products),
        },
    )
    if status >= 400:
        raise ToolError(data.get("error") or f"Failed to start Prava checkout (HTTP {status}).")
    checkout = data.get("checkout") or {}
    amount = checkout.get("totalAmount") or totalAmount
    return f"Prava checkout started for {amount} {checkout.get('currency') or 'INR'}."


async def get_prava_checkout_credential(
    waitForReady: bool = True, timeoutSeconds: int = 90
) -> str:
    started = time.monotonic()
    last_error: str | None = None
    data: dict[str, Any] = {}

    while True:
        status, data = await _request("GET", "/internal/prava/checkout-credential")
        if status < 400:
            break

        last_error = data.get("error") or f"Prava credential not ready (HTTP {status})."
        elapsed = time.monotonic() - started
        should_retry = waitForReady and status == 409 and elapsed < timeoutSeconds
        if not should_retry:
            raise ToolError(last_error)
        await asyncio.sleep(3)
        if time.monotonic() - started >= timeoutSeconds:
            break

    credential = data.get("credential")
    if not credential:
        raise ToolError(last_error or "Prava credential was not ready before the wait timed out.")

    return "\n".join(
        [
            "Prava credential ready for BrowserClaw merchant handoff.",
            f"Card Number: {credential.get('cardNumber')}",
            f"Expiry Date (MM/YY): {credential.get('expiry')}",
            f"CVV: {credential.get('cvv')}",
            f"Cardholder Name: {credential.get('nameOnCard') or 'Prava User'}",
            f"Card Nickname: {credential.get('cardNickname') or 'Prava'}",
            f"Transaction Ref: {credential.get('txnRefId')}",
            "Do not reveal these values in chat. Fill them into https://instamart.in/payment only.",
        ]
    )


async def report_prava_merchant_outcome(
    txnStatus: MerchantOutcome,
    observation: str | None = None,
    buttonState: str | None = None,
    pageState: str | None = None,
) -> str:
    status, data = await _request(
        "POST",
        "/internal/prava/report-merchant-outcome",
        {
            "txnStatus": txnStatus,
            "observation": observation,
            "buttonState": buttonState,
            "pageState": pageState,
        },
    )
    if status >= 400:
        raise ToolError(
            data.get("error") or f"Failed to report Prava merchant outcome (HTTP {status})."
        )
    return f"Reported Swiggy merchant outcome to Prava: {data.get('status')}."


# --- Razorpay (test mode) --------------------------------------------------


async def start_razorpay_checkout(
    totalAmount: str,
    description: str | None = None,
    currency: str | None = None,
    products: list[PravaProduct] | None = None,
) -> str:
    status, data = await _request(
        "POST",
        "/internal/razorpay/start-checkout",
        {
            "totalAmount": totalAmount,
            "currency": currency or "INR",
            "description": description,
            "products": _dump(products),
        },
    )
    if status >= 400:
        raise ToolError(data.get("error") or f"Failed to start Razorpay checkout (HTTP {status}).")

    checkout = data.get("checkout") or {}
    mode = "TEST MODE - no real money moves" if checkout.get("testMode") else "LIVE"
    return "\n".join(
        [
            f"Razorpay payment link created for {totalAmount} "
            f"{checkout.get('currency') or 'INR'} ({mode}).",
            f"Payment link: {checkout.get('shortUrl')}",
            "Give this link to the user as a Markdown link and tell them to complete payment there.",
            "When they say they have paid, call get_razorpay_payment_status to confirm before",
            "claiming the payment succeeded.",
        ]
    )


async def get_razorpay_payment_status() -> str:
    status, data = await _request("GET", "/internal/razorpay/payment-status")
    if status >= 400:
        raise ToolError(data.get("error") or f"Failed to read Razorpay payment status (HTTP {status}).")

    state = data.get("status")
    if data.get("paid"):
        return f"Razorpay reports the payment link is PAID (status={state}). The order is paid for."
    return (
        f"Razorpay reports status={state} - NOT yet paid. Do not tell the user the payment "
        "succeeded. Ask them to complete the link, then check again."
    )


# --- the catalog -----------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    fn: Callable[..., Any]
    headless_approval: str | None = None


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_profile",
        title="Read the user profile",
        headless_approval="approve",
        description=(
            "Read the user's current saved profile (markdown). Call this BEFORE save_profile "
            "so you can merge new information into what already exists instead of losing it."
        ),
        fn=get_profile,
    ),
    ToolSpec(
        name="save_profile",
        title="Save the user profile",
        headless_approval="approve",
        description=(
            "Save the user profile. This REPLACES THE ENTIRE profile file - it does NOT merge. "
            "So ALWAYS call get_profile first, apply the requested change to that content yourself "
            "(add, edit, or remove), and pass back the COMPLETE updated markdown. To wipe the "
            "profile and start over, pass only what should remain. Keep it clean, readable markdown "
            "with the user's name as a top-level `#` heading when known."
        ),
        fn=save_profile,
    ),
    ToolSpec(
        name="show_chat",
        title="Return to chat",
        headless_approval="approve",
        description=(
            "Return the workspace to the plain chat surface without deleting calendar or Basket "
            "data. Call this when the user asks to go back to chat, close the Basket, or close "
            "the calendar."
        ),
        fn=show_chat,
    ),
    ToolSpec(
        name="show_calendar",
        title="Show or update the meal planner calendar",
        headless_approval="approve",
        description=(
            "Open or refresh the meal planner calendar. Call this when the user asks for a "
            "multi-day meal plan, or when updating an existing planner. Always pass the full "
            "current calendar JSON, not a partial edit. Keep the same schema and edit only "
            "values inside weeks/days/meals/disabled."
        ),
        fn=show_calendar,
    ),
    ToolSpec(
        name="show_basket",
        title="Show or update the Basket",
        headless_approval="approve",
        description=(
            "Open or refresh the app Basket canvas. The Basket is the app-side list of chosen "
            "grocery products - it is NOT the user's real Swiggy/Zepto cart and this NEVER "
            "touches the store. Pass the FULL current list of Basket items every time - both "
            "found products and not-found ingredients - exactly like show_calendar: each call "
            "REPLACES the displayed Basket, it is not a partial edit. Call this as you fill the "
            "Basket from a shopping list, and whenever the user asks to change the Basket (add, "
            "remove, swap, or adjust the quantity of an item)."
        ),
        fn=show_basket,
    ),
    ToolSpec(
        name="start_prava_checkout",
        title="Start Prava checkout",
        headless_approval="approve",
        description=(
            "Start a Prava payment approval for the already-staged Swiggy Instamart cart. "
            "Call this ONLY after the user has explicitly confirmed they want to pay with Prava. "
            "Before calling it, use the Swiggy Instamart get_cart tool to read the live cart, "
            "then pass the exact final payable total and cart products here. This creates a "
            "Prava session server-side and opens the Prava iframe in Boppai for the user to "
            "approve. It does NOT call Swiggy checkout and does NOT place the order."
        ),
        fn=start_prava_checkout,
    ),
    ToolSpec(
        name="get_prava_checkout_credential",
        title="Get Prava card credential",
        headless_approval="approve",
        description=(
            "Fetch the active Prava one-time card credential after the user has completed the "
            "Prava approval panel. Use this ONLY for the Prava merchant browser handoff. The "
            "returned card number is a Prava/Visa one-time network token and the CVV is dynamic. "
            "Do NOT paste these values into normal chat; use them only to fill the Swiggy "
            "Instamart card form through BrowserClaw. By default this waits and polls briefly so "
            "the user can finish the iframe/passkey approval."
        ),
        fn=get_prava_checkout_credential,
    ),
    ToolSpec(
        name="report_prava_merchant_outcome",
        title="Report Prava merchant outcome",
        headless_approval="approve",
        description=(
            "Report the final Swiggy Instamart browser outcome back to Prava for the active "
            "checkout. Call this after BrowserClaw fills the Prava one-time credential on "
            "https://instamart.in/payment and observes the page. Use DECLINED when the button "
            "remains loading/stuck after the 5 second wait, or when Swiggy shows a decline/error. "
            "Use APPROVED only when the page clearly indicates success."
        ),
        fn=report_prava_merchant_outcome,
    ),
    ToolSpec(
        name="start_razorpay_checkout",
        title="Start Razorpay checkout (test mode)",
        headless_approval="approve",
        description=(
            "Create a Razorpay payment link for the already-staged grocery cart. Call this "
            "ONLY after the user has explicitly confirmed they want to pay. Before calling "
            "it, use the grocery service's get_cart tool to read the LIVE cart, then pass the "
            "exact final payable total and cart products here. Returns a payment link to give "
            "the user. It does NOT place the order and does NOT confirm payment - poll with "
            "get_razorpay_payment_status for that. Only usable when the session's payment "
            "provider is Razorpay."
        ),
        fn=start_razorpay_checkout,
    ),
    ToolSpec(
        name="get_razorpay_payment_status",
        title="Check Razorpay payment status",
        headless_approval="approve",
        description=(
            "Check whether this session's Razorpay payment link has actually been paid. Call "
            "this before telling the user their payment went through - never assume it "
            "succeeded because they said so. Returns the live link status from Razorpay."
        ),
        fn=get_razorpay_payment_status,
    ),
]
