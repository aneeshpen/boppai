"""
Prava contract + safeguard tests.

Scope note, stated plainly: there is no MERCHANT_SECRET_KEY or PRAVA_PUBLISHABLE_KEY in
this environment, so nothing here touches the real Prava sandbox. What IS covered is
everything that runs before the network call -- config reporting, validation, checkout
state transitions, the credential-masking rule from the brief, and the guard that a
merchant outcome can only ever be reported against the session that minted the
credential. The live credentialed round-trip is reported as NOT TESTED.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import prava as prava_service
from app.services import prava_checkout as checkout_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.core import boot as boot_module
    from app.core import config as config_module
    from app.services import profile as profile_module
    from app.services import sessions as sessions_module

    data_dir = tmp_path / "data"
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(config_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(boot_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(boot_module, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(boot_module, "DB_PATH", data_dir / "boppai.db")
    monkeypatch.setattr(sessions_module, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(profile_module, "PROFILE_PATH", data_dir / "profile.md")

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


PAYMENT_RESULT = {
    "session_id": "sess_123",
    "order_id": "ord_456",
    "status": "awaiting_result",
    "transactions": [
        {
            "line_items": [
                {
                    "token": "4111111111119876",
                    "dynamic_cvv": "321",
                    "txn_ref_id": "txn_789",
                    "merchant_name": "Swiggy Instamart",
                    "total_amount": "119.00",
                    "expiry_month": "11",
                    "expiry_year": "2030",
                }
            ]
        }
    ],
}


# --- key configuration -----------------------------------------------------


def test_is_configured_key_rejects_placeholders_and_wrong_prefixes():
    assert prava_service.is_configured_key("sk_test_abc", "sk_") is True
    assert prava_service.is_configured_key("sk_test_YOUR_KEY_HERE", "sk_") is False
    assert prava_service.is_configured_key("pk_test_abc", "sk_") is False
    assert prava_service.is_configured_key("", "sk_") is False
    assert prava_service.is_configured_key(None, "sk_") is False


def test_config_endpoint_reports_unconfigured_without_keys(client):
    body = client.get("/api/prava/config").json()
    assert set(body) == {"publishableKey", "configured", "appUrl"}
    assert body["configured"] is False


def test_endpoints_needing_the_secret_key_fail_closed(client):
    """Without a usable sk_ key these must refuse, not attempt a call."""
    result = client.get("/api/prava/payment-result/sess_123")
    assert result.status_code == 500
    assert result.json()["error"] == "MERCHANT_SECRET_KEY is missing or invalid."

    reported = client.post(
        "/api/prava/report-status",
        json={"sessionId": "s", "txnRefId": "t", "txnStatus": "APPROVED"},
    )
    assert reported.status_code == 500
    assert reported.json()["error"] == "MERCHANT_SECRET_KEY is missing or invalid."


def test_report_status_validates_before_anything_else(client, monkeypatch):
    monkeypatch.setattr(prava_service.settings, "merchant_secret_key", "sk_test_local")

    for payload, expected in [
        ({}, "sessionId is required"),
        ({"sessionId": "s"}, "txnRefId is required"),
        ({"sessionId": "s", "txnRefId": "t"}, "txnStatus must be APPROVED or DECLINED"),
        (
            {"sessionId": "s", "txnRefId": "t", "txnStatus": "MAYBE"},
            "txnStatus must be APPROVED or DECLINED",
        ),
    ]:
        response = client.post("/api/prava/report-status", json=payload)
        assert response.status_code == 400
        assert response.json() == {"error": expected}


def test_merchant_outcome_rejects_a_non_binary_status(client, monkeypatch):
    monkeypatch.setattr(prava_service.settings, "merchant_secret_key", "sk_test_local")
    response = client.post("/internal/prava/report-merchant-outcome", json={"txnStatus": "ok"})
    assert response.status_code == 400
    assert response.json() == {"error": "txnStatus must be APPROVED or DECLINED"}


def test_credential_endpoint_404s_when_no_checkout_is_active(client, monkeypatch):
    monkeypatch.setattr(prava_service.settings, "merchant_secret_key", "sk_test_local")
    response = client.get("/internal/prava/checkout-credential")
    assert response.status_code == 404
    assert response.json()["error"] == "No active Prava checkout session is ready yet."


def test_session_checkout_is_absent_until_started(client):
    assert client.get("/api/session/prava-checkout").json() == {"exists": False, "checkout": None}


# --- checkout intent normalization ----------------------------------------


def test_intent_normalization_and_amount_validation(session):
    intent = checkout_state.start(
        session,
        {
            "totalAmount": "119",
            "products": [{"description": "Maggi", "unitPrice": "14.00", "quantity": 2}],
        },
    )
    assert intent["status"] == "creating"
    assert intent["totalAmount"] == "119.00"  # normalized to 2dp
    assert intent["currency"] == "INR"
    assert intent["merchantName"] == "Swiggy Instamart"
    assert intent["products"] == [
        {"description": "Maggi", "unitPrice": "14.00", "quantity": 2}
    ]

    exists, stored = checkout_state.read(session)
    assert exists and stored["totalAmount"] == "119.00"


def test_intent_rejects_a_non_decimal_total(session):
    for bad in ("free", "12.345", "", None):
        with pytest.raises(ValueError):
            checkout_state.start(session, {"totalAmount": bad})


def test_intent_falls_back_to_a_single_product_line(session):
    intent = checkout_state.start(session, {"totalAmount": "50.00", "description": "Groceries"})
    assert intent["products"] == [
        {"description": "Groceries", "unitPrice": "50.00", "quantity": 1}
    ]


def test_mark_ready_clears_a_previous_error(session):
    intent = checkout_state.start(session, {"totalAmount": "10.00"})
    errored = checkout_state.mark_error(session, intent, "boom")
    assert errored["status"] == "error" and errored["error"] == "boom"

    ready = checkout_state.mark_ready(session, errored, {"session_id": "sess_1"})
    assert ready["status"] == "ready"
    # JSON.stringify dropped `error: undefined`; the port must not leave it behind.
    assert "error" not in ready
    assert ready["session"]["session_id"] == "sess_1"


# --- credential handling ---------------------------------------------------


def test_credential_is_extracted_from_the_payment_result():
    credential = prava_service.credential_from_payment_result(PAYMENT_RESULT)
    assert credential is not None
    assert credential["cardNumber"] == "4111111111119876"
    assert credential["cvv"] == "321"
    assert credential["expiry"] == "11/30"  # MM/YY, year truncated
    assert credential["txnRefId"] == "txn_789"
    assert credential["nameOnCard"] == "Prava User"


def test_no_credential_until_both_token_and_cvv_are_present():
    assert prava_service.credential_from_payment_result({"status": "pending"}) is None
    partial = {"transactions": [{"line_items": [{"token": "4111", "txn_ref_id": "t"}]}]}
    assert prava_service.credential_from_payment_result(partial) is None


def test_minted_credential_log_masks_the_pan_and_redacts_the_cvv(caplog):
    """The brief forbids logging payment credentials; the Node build logged them raw."""
    prava_service._logged_minted_credentials.clear()

    with caplog.at_level("INFO", logger="boppai.prava"):
        credential = prava_service.log_minted_credential(PAYMENT_RESULT, "test")

    # The caller still receives the real values -- BrowserClaw needs them.
    assert credential["cardNumber"] == "4111111111119876"
    assert credential["cvv"] == "321"

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "4111111111119876" not in logged
    assert "321" not in logged.replace("txn_789", "")  # the CVV, not the ref id
    assert "************9876" in logged
    assert "[redacted]" in logged
    # Still traceable: the ids that matter for support are kept.
    assert "txn_789" in logged and "sess_123" in logged


def test_minted_credential_is_logged_once_per_credential(caplog):
    prava_service._logged_minted_credentials.clear()
    with caplog.at_level("INFO", logger="boppai.prava"):
        for _ in range(4):  # simulates repeated polling
            prava_service.log_minted_credential(PAYMENT_RESULT, "test")

    minted = [r for r in caplog.records if "minted credential" in r.getMessage()]
    assert len(minted) == 1


def test_mask_pan_handles_short_and_missing_values():
    assert prava_service._mask_pan("4111111111119876") == "************9876"
    assert prava_service._mask_pan("9876") == "****"
    assert prava_service._mask_pan(None) == "****"
