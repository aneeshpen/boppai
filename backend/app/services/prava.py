"""
Prava payments -- the merchant-side client and credential handling.

The browser only ever receives the publishable key and the session token/iframe URL.
MERCHANT_SECRET_KEY stays server-side, used here for session creation, payment-result
polling, and outcome reporting.

SECURITY NOTE -- one deliberate deviation from the Node build. `routes/prava.js` logged
the full PAN and the dynamic CVV in cleartext under "[Prava DEBUG minted credential]".
This module keeps that trace (same trigger, same dedupe, same `source` tag) but masks the
card number to its last four digits and redacts the CVV entirely. Nothing functional
changes: the unmasked credential still flows to the MCP tool and on to BrowserClaw, which
is what actually completes the merchant handoff. Only the log line is redacted.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger("prava")

DEFAULT_MERCHANT = {
    "name": "Swiggy Instamart",
    "url": "https://www.swiggy.com/",
    "country_code_iso2": "IN",
}

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# One log line per minted credential, not one per poll.
_logged_minted_credentials: set[str] = set()


class PravaError(Exception):
    """A Prava API failure, carrying the status/code/responseId the routes echo back."""

    def __init__(
        self,
        message: str,
        status: int = 500,
        *,
        code: str | None = None,
        response_id: str | None = None,
        result_status: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.response_id = response_id
        self.result_status = result_status


def trim_slash(value: Any) -> str:
    return str(value or "").rstrip("/")


def is_configured_key(value: Any, prefix: str) -> bool:
    """A key is usable only if it's present, correctly prefixed, and not a placeholder."""
    return isinstance(value, str) and value.startswith(prefix) and "YOUR_" not in value


def require_prava_server_config() -> str | None:
    if not is_configured_key(settings.merchant_secret_key, "sk_"):
        return "MERCHANT_SECRET_KEY is missing or invalid. Add your sk_test_* key to backend/.env."
    if not settings.boppai_user_email:
        return "BOPPAI_USER_EMAIL is missing. Add the payer email to backend/.env."
    return None


async def fetch_prava(
    path: str,
    *,
    method: str = "GET",
    json_body: Any = None,
    authorized: bool = True,
) -> tuple[httpx.Response, dict[str, Any]]:
    """One Prava API call, with the request/response trace the Node build emitted."""
    url = f"{trim_slash(settings.prava_backend_url)}{path}"
    headers: dict[str, str] = {}
    if authorized:
        headers["Authorization"] = f"Bearer {settings.merchant_secret_key}"
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    log.info(
        "[Prava API] request %s",
        json.dumps({"method": method, "path": path, "body": json_body}, default=str),
    )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.request(method, url, headers=headers, json=json_body)
    except httpx.HTTPError as exc:
        log.info(
            "[Prava API] error %s",
            json.dumps({"method": method, "path": path, "error": str(exc)}),
        )
        raise PravaError(str(exc) or "Prava request failed") from exc

    try:
        data = response.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    log.info(
        "[Prava API] response %s",
        json.dumps(
            {
                "method": method,
                "path": path,
                "status": response.status_code,
                "ok": response.is_success,
                "responseId": response.headers.get("x-response-id"),
                "body": data,
            },
            default=str,
        ),
    )
    return response, data


# --- credentials -----------------------------------------------------------


def first_credential_line_item(result: Any) -> dict[str, Any] | None:
    for transaction in (result or {}).get("transactions") or []:
        for line_item in (transaction or {}).get("line_items") or []:
            if line_item and line_item.get("token") and line_item.get("dynamic_cvv"):
                return line_item
    return None


def expiry_value(line_item: dict[str, Any] | None) -> str:
    if not line_item or not line_item.get("expiry_month") or not line_item.get("expiry_year"):
        return ""
    return f"{line_item['expiry_month']}/{str(line_item['expiry_year'])[-2:]}"


def credential_from_payment_result(result: Any) -> dict[str, Any] | None:
    line_item = first_credential_line_item(result)
    if not line_item:
        return None

    return {
        "sessionId": (result or {}).get("session_id"),
        "orderId": (result or {}).get("order_id"),
        "txnRefId": line_item.get("txn_ref_id"),
        "merchantName": line_item.get("merchant_name") or DEFAULT_MERCHANT["name"],
        "amountPaid": line_item.get("total_amount"),
        "cardNumber": line_item.get("token"),
        "expiryMonth": line_item.get("expiry_month"),
        "expiryYear": line_item.get("expiry_year"),
        "expiry": expiry_value(line_item),
        "cvv": line_item.get("dynamic_cvv"),
        "nameOnCard": "Prava User",
        "cardNickname": "Prava",
        "status": (result or {}).get("status"),
    }


def _mask_pan(card_number: Any) -> str:
    digits = str(card_number or "")
    if len(digits) <= 4:
        return "****"
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"


def log_minted_credential(result: Any, source: str) -> dict[str, Any] | None:
    """Trace that a credential was minted, without writing the credential itself.

    Deduped by (session, txn, card) so repeated polling logs once. See the module
    docstring for why the PAN is masked and the CVV redacted.
    """
    credential = credential_from_payment_result(result)
    if not credential:
        return None

    key = f"{credential['sessionId']}:{credential['txnRefId']}:{credential['cardNumber']}"
    if key not in _logged_minted_credentials:
        _logged_minted_credentials.add(key)
        log.info(
            "[Prava minted credential] %s",
            json.dumps(
                {
                    "source": source,
                    "sessionId": credential["sessionId"],
                    "orderId": credential["orderId"],
                    "txnRefId": credential["txnRefId"],
                    "merchantName": credential["merchantName"],
                    "amountPaid": credential["amountPaid"],
                    "cardNumber": _mask_pan(credential["cardNumber"]),
                    "expiry": credential["expiry"],
                    "dynamicCvv": "[redacted]",
                    "nameOnCard": credential["nameOnCard"],
                },
                default=str,
            ),
        )

    return credential


# --- sessions --------------------------------------------------------------


def product_details_from_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    products = body.get("products")
    if isinstance(products, list) and products:
        return [
            {
                "description": product["description"].strip(),
                "unit_price": str(
                    product.get("unitPrice")
                    or product.get("unit_price")
                    or body.get("totalAmount")
                    or "20.00"
                ),
                "quantity": int(product.get("quantity") or 1),
            }
            for product in products
            if isinstance(product, dict) and isinstance(product.get("description"), str)
        ]

    return [
        {
            "description": body.get("description") or "Boppai sandbox grocery test",
            "unit_price": str(body.get("totalAmount") or "20.00"),
            "quantity": 1,
        }
    ]


async def create_prava_session(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    config_error = require_prava_server_config()
    if config_error:
        raise PravaError(config_error, status=500)

    total_amount = str(body.get("totalAmount") or "20.00")
    merchant = {
        "name": body.get("merchantName") or DEFAULT_MERCHANT["name"],
        "url": body.get("merchantUrl") or DEFAULT_MERCHANT["url"],
        "country_code_iso2": body.get("countryCode") or DEFAULT_MERCHANT["country_code_iso2"],
    }

    payload: dict[str, Any] = {
        "user_id": body.get("userId") or settings.boppai_user_id,
        "user_email": body.get("userEmail") or settings.boppai_user_email,
        "total_amount": total_amount,
        "currency": body.get("currency") or "INR",
        "description": body.get("description") or "Boppai grocery payment",
        "integration_type": "embedding",
        "purchase_context": [
            {
                "merchant_details": merchant,
                "product_details": product_details_from_body({**body, "totalAmount": total_amount}),
                "effective_until_minutes": int(body.get("effectiveUntilMinutes") or 15),
            }
        ],
    }
    if settings.boppai_public_app_url:
        payload["callback_url"] = settings.boppai_public_app_url

    response, data = await fetch_prava("/v1/sessions", method="POST", json_body=payload)
    if not response.is_success:
        raise PravaError(
            (data.get("error") or {}).get("message")
            or f"Prava session creation failed (HTTP {response.status_code})",
            status=response.status_code,
            code=(data.get("error") or {}).get("code"),
            response_id=response.headers.get("x-response-id"),
        )

    return {**data, "responseId": response.headers.get("x-response-id")}


async def fetch_payment_result(session_id: str) -> tuple[httpx.Response, dict[str, Any]]:
    """Poll one session's payment result. The cache-buster mirrors the Node client."""
    import time

    return await fetch_prava(f"/v1/sessions/{session_id}/payment-result?_t={int(time.time() * 1000)}")


async def report_status_to_prava(
    *,
    session_id: str,
    txn_ref_id: str,
    txn_status: str,
    txn_type: str = "PURCHASE",
    authorization_code: Any = None,
    response_code: Any = None,
    amount_paid: Any = None,
) -> tuple[httpx.Response, dict[str, Any]]:
    payload: dict[str, Any] = {
        "txn_ref_id": txn_ref_id,
        "txn_status": txn_status,
        "txn_type": txn_type,
    }
    if authorization_code:
        payload["authorization_code"] = str(authorization_code)
    if response_code:
        payload["response_code"] = str(response_code)
    if amount_paid:
        payload["amount_paid"] = str(amount_paid)

    return await fetch_prava(
        f"/v1/sessions/{session_id}/report-status", method="POST", json_body=payload
    )
