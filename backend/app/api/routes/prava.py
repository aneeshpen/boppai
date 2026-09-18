"""
Prava payment endpoints.

The browser only receives the publishable key and the session token/iframe URL.
MERCHANT_SECRET_KEY stays server-side for session creation and result polling.

The safeguards this file must preserve, because they are the payment flow's whole point:

* `start_prava_checkout` is only ever reached from the MCP tool, which boppai.md gates on
  an explicit user confirmation after reading the LIVE merchant cart. Nothing here
  short-circuits that.
* The one-time credential is never returned to the browser. It goes to
  /internal/prava/checkout-credential, which only the MCP tool subprocess calls, and on
  to BrowserClaw.
* A merchant outcome can only be reported for the session that actually minted the
  credential -- the session id and txn ref come from the payment result, not the caller.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from ...core.config import settings
from ...core.deps import json_body
from ...core.errors import BoppaiError
from ...models.session import Session
from ...services import prava as prava_service
from ...services import prava_checkout as checkout_state
from ...services import sessions as sessions_service
from ...services.prava import PravaError, is_configured_key

router = APIRouter()


def _active() -> Session:
    return sessions_service.get_or_create_active()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _as_boppai_error(exc: PravaError) -> BoppaiError:
    return BoppaiError(
        exc.message,
        status=exc.status or 500,
        code=exc.code,
        response_id=exc.response_id,
        extra={"resultStatus": exc.result_status},
    )


def _require_secret_key() -> None:
    if not is_configured_key(settings.merchant_secret_key, "sk_"):
        raise BoppaiError("MERCHANT_SECRET_KEY is missing or invalid.", status=500)


async def _get_active_checkout_credential(source: str) -> dict[str, Any]:
    """Poll the active checkout's payment result and return its minted credential.

    Deliberately reads the session id from the stored checkout rather than from the
    caller, so a tool call can only ever act on the checkout this session started.
    """
    if not is_configured_key(settings.merchant_secret_key, "sk_"):
        raise PravaError("MERCHANT_SECRET_KEY is missing or invalid.", status=500)

    active = _active()
    exists, current = checkout_state.read(active)
    session_id = ((current or {}).get("session") or {}).get("session_id")
    if not exists or not session_id:
        raise PravaError("No active Prava checkout session is ready yet.", status=404)

    response, data = await prava_service.fetch_payment_result(session_id)
    if not response.is_success:
        raise PravaError(
            (data.get("error") or {}).get("message")
            or f"Prava payment result failed (HTTP {response.status_code})",
            status=response.status_code,
            code=(data.get("error") or {}).get("code"),
            response_id=response.headers.get("x-response-id"),
        )

    credential = prava_service.log_minted_credential(data, source)
    if not credential:
        raise PravaError(
            f"Prava credential is not ready yet. Current status: {data.get('status') or 'unknown'}.",
            status=409,
            result_status=data.get("status"),
        )

    checkout_state.write(
        active,
        {
            **current,
            "credentialReadyAt": current.get("credentialReadyAt") or _now(),
            "updatedAt": _now(),
        },
    )

    return {
        "active": active,
        "checkout": current,
        "credential": credential,
        "paymentResult": data,
        "responseId": response.headers.get("x-response-id"),
    }


# --- browser-facing --------------------------------------------------------


@router.get("/api/prava/config")
async def prava_config() -> dict[str, Any]:
    return {
        "publishableKey": settings.prava_publishable_key,
        "configured": is_configured_key(settings.prava_publishable_key, "pk_"),
        "appUrl": settings.boppai_public_app_url,
    }


@router.get("/api/prava/health")
async def prava_health() -> dict[str, Any]:
    try:
        response, _ = await prava_service.fetch_prava("/health", authorized=False)
        return {"healthy": response.is_success}
    except PravaError as exc:
        return {"healthy": False, "error": exc.message}


@router.post("/api/prava/create-session")
async def prava_create_session(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    try:
        return await prava_service.create_prava_session(body)
    except PravaError as exc:
        raise _as_boppai_error(exc) from exc


@router.get("/api/session/prava-checkout")
async def session_prava_checkout() -> dict[str, Any]:
    exists, checkout = checkout_state.read(_active())
    return {"exists": exists, "checkout": checkout}


@router.get("/api/prava/payment-result/{session_id}")
async def prava_payment_result(session_id: str) -> dict[str, Any]:
    _require_secret_key()

    try:
        response, data = await prava_service.fetch_payment_result(session_id)
    except PravaError as exc:
        raise BoppaiError(
            exc.message or "Failed to poll Prava payment result", status=500
        ) from exc

    if not response.is_success:
        raise BoppaiError(
            (data.get("error") or {}).get("message")
            or f"Prava payment result failed (HTTP {response.status_code})",
            status=response.status_code,
            code=(data.get("error") or {}).get("code"),
            response_id=response.headers.get("x-response-id"),
        )

    prava_service.log_minted_credential(data, "api/payment-result")
    return {**data, "responseId": response.headers.get("x-response-id")}


@router.post("/api/prava/report-status")
async def prava_report_status(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    _require_secret_key()

    raw_session_id = body.get("sessionId")
    raw_txn_ref_id = body.get("txnRefId")
    session_id = raw_session_id.strip() if isinstance(raw_session_id, str) else ""
    txn_ref_id = raw_txn_ref_id.strip() if isinstance(raw_txn_ref_id, str) else ""
    txn_status = body.get("txnStatus") if body.get("txnStatus") in ("APPROVED", "DECLINED") else ""

    if not session_id:
        raise BoppaiError("sessionId is required")
    if not txn_ref_id:
        raise BoppaiError("txnRefId is required")
    if not txn_status:
        raise BoppaiError("txnStatus must be APPROVED or DECLINED")

    try:
        response, data = await prava_service.report_status_to_prava(
            session_id=session_id,
            txn_ref_id=txn_ref_id,
            txn_status=txn_status,
            txn_type=body.get("txnType") or "PURCHASE",
            authorization_code=body.get("authorizationCode"),
            response_code=body.get("responseCode"),
            amount_paid=body.get("amountPaid"),
        )
    except PravaError as exc:
        raise BoppaiError(exc.message or "Failed to report Prava status", status=500) from exc

    if not response.is_success:
        raise BoppaiError(
            (data.get("error") or {}).get("message")
            or f"Prava report-status failed (HTTP {response.status_code})",
            status=response.status_code,
            code=(data.get("error") or {}).get("code"),
            response_id=response.headers.get("x-response-id"),
        )

    active = _active()
    exists, current = checkout_state.read(active)
    if exists and current:
        checkout_state.write(
            active,
            {**current, "reported": {**data, "at": _now()}, "updatedAt": _now()},
        )

    return {**data, "responseId": response.headers.get("x-response-id")}


# --- MCP-facing (localhost only) -------------------------------------------


@router.post("/internal/prava/start-checkout")
async def internal_start_checkout(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    session = _active()
    current: dict[str, Any] | None = None

    try:
        current = checkout_state.start(session, body)
        prava_session = await prava_service.create_prava_session(current)
        checkout = checkout_state.mark_ready(session, current, prava_session)
        return {"ok": True, "checkout": checkout}
    except (PravaError, ValueError) as exc:
        message = getattr(exc, "message", None) or str(exc)
        if current:
            checkout_state.mark_error(session, current, message)
        status = getattr(exc, "status", None) or (400 if isinstance(exc, ValueError) else 500)
        raise BoppaiError(
            message or "Failed to start Prava checkout",
            status=status,
            code=getattr(exc, "code", None),
            response_id=getattr(exc, "response_id", None),
        ) from exc


@router.get("/internal/prava/checkout-credential")
async def internal_checkout_credential() -> dict[str, Any]:
    try:
        result = await _get_active_checkout_credential("internal/checkout-credential")
    except PravaError as exc:
        raise _as_boppai_error(exc) from exc

    return {
        "ok": True,
        "status": result["paymentResult"].get("status"),
        "credential": result["credential"],
        "responseId": result["responseId"],
    }


@router.post("/internal/prava/report-merchant-outcome")
async def internal_report_merchant_outcome(
    body: dict[str, Any] = Depends(json_body),
) -> dict[str, Any]:
    _require_secret_key()

    txn_status = body.get("txnStatus") if body.get("txnStatus") in ("APPROVED", "DECLINED") else ""
    if not txn_status:
        raise BoppaiError("txnStatus must be APPROVED or DECLINED")

    try:
        result = await _get_active_checkout_credential("internal/report-merchant-outcome")
        active, checkout, credential = result["active"], result["checkout"], result["credential"]

        response, data = await prava_service.report_status_to_prava(
            session_id=credential["sessionId"],
            txn_ref_id=credential["txnRefId"],
            txn_status=txn_status,
            txn_type=body.get("txnType") or "PURCHASE",
            authorization_code=body.get("authorizationCode"),
            response_code=body.get("responseCode"),
            amount_paid=body.get("amountPaid") or credential.get("amountPaid"),
        )
    except PravaError as exc:
        raise _as_boppai_error(exc) from exc

    if not response.is_success:
        raise BoppaiError(
            (data.get("error") or {}).get("message")
            or f"Prava report-status failed (HTTP {response.status_code})",
            status=response.status_code,
            code=(data.get("error") or {}).get("code"),
            response_id=response.headers.get("x-response-id"),
        )

    def _text(key: str) -> str:
        value = body.get(key)
        return value.strip() if isinstance(value, str) else ""

    merchant_outcome = {
        "status": txn_status,
        "observation": _text("observation"),
        "buttonState": _text("buttonState"),
        "pageState": _text("pageState"),
        "at": _now(),
    }

    checkout_state.write(
        active,
        {
            **checkout,
            "merchantOutcome": merchant_outcome,
            "reported": {**data, "status": txn_status, "at": _now()},
            "updatedAt": _now(),
        },
    )

    return {
        "ok": True,
        "status": txn_status,
        "merchantOutcome": merchant_outcome,
        "report": data,
        "responseId": response.headers.get("x-response-id"),
    }
