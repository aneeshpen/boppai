"""
Razorpay test-mode payment endpoints.

  GET  /api/razorpay/config                  -> is the rail usable, and is it test mode
  GET  /api/session/razorpay-checkout        -> the session's active payment link
  GET  /api/razorpay/payment-status/{id}     -> poll one link
  POST /internal/razorpay/start-checkout     -> start_razorpay_checkout (MCP tool)
  GET  /internal/razorpay/payment-status     -> get_razorpay_payment_status (MCP tool)

Boppai never touches card data on this rail: the user pays on Razorpay's hosted page, and
all we hold is the link id and its status.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...core.config import settings
from ...core.deps import json_body
from ...core.errors import BoppaiError
from ...models.session import Session
from ...services import razorpay as razorpay_service
from ...services import razorpay_checkout as checkout_state
from ...services import sessions as sessions_service
from ...services.razorpay import RazorpayError

router = APIRouter()


def _active() -> Session:
    return sessions_service.get_or_create_active()


def _as_boppai_error(exc: RazorpayError) -> BoppaiError:
    return BoppaiError(exc.message, status=exc.status or 500)


@router.get("/api/razorpay/config")
async def razorpay_config() -> dict[str, Any]:
    return {
        "configured": razorpay_service.is_configured(),
        "testMode": razorpay_service.is_test_mode(),
        "keyId": settings.razorpay_key_id,  # publishable half only; the secret never leaves
    }


@router.get("/api/session/razorpay-checkout")
async def session_razorpay_checkout() -> dict[str, Any]:
    exists, checkout = checkout_state.read(_active())
    return {"exists": exists, "checkout": checkout}


@router.get("/api/razorpay/payment-status/{link_id}")
async def razorpay_payment_status(link_id: str) -> dict[str, Any]:
    try:
        return await razorpay_service.fetch_payment_link(link_id)
    except RazorpayError as exc:
        raise _as_boppai_error(exc) from exc


@router.post("/internal/razorpay/start-checkout")
async def internal_start_checkout(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    session = _active()
    total_amount = body.get("totalAmount")

    try:
        link = await razorpay_service.create_payment_link(
            total_amount=total_amount,
            description=body.get("description") or f"Boppai grocery order ({total_amount} INR)",
            currency=body.get("currency") or "INR",
            products=body.get("products"),
            customer_email=settings.boppai_user_email or None,
        )
    except RazorpayError as exc:
        raise _as_boppai_error(exc) from exc

    checkout = checkout_state.start(session, link, total_amount=str(total_amount))
    return {"ok": True, "checkout": checkout}


@router.get("/internal/razorpay/payment-status")
async def internal_payment_status() -> dict[str, Any]:
    session = _active()
    exists, current = checkout_state.read(session)
    link_id = (current or {}).get("id")
    if not exists or not link_id:
        raise BoppaiError("No Razorpay checkout has been started for this session.", status=404)

    try:
        status = await razorpay_service.fetch_payment_link(link_id)
    except RazorpayError as exc:
        raise _as_boppai_error(exc) from exc

    checkout_state.record_status(session, status)
    return {"ok": True, **status}
