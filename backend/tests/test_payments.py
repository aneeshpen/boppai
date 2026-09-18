"""
Payment-rail selection, the Razorpay test-mode client, and the two session-capability
blocks that keep the agent honest about what it can actually do.

No network: the Razorpay client is exercised through a stubbed transport, so amount
conversion and payload shape are pinned without a live account.
"""

from __future__ import annotations

import httpx
import pytest

from app.payments import DEFAULT_PAYMENT_PROVIDER, PAYMENT_PROVIDERS, payment_provider
from app.services import razorpay as razorpay_service
from app.services import razorpay_checkout as checkout_state
from app.services.razorpay import RazorpayError


# --- provider registry -----------------------------------------------------


def test_both_rails_are_registered_and_prava_stays_the_default():
    assert set(PAYMENT_PROVIDERS) == {"prava", "razorpay"}
    # The hackathon integration remains the out-of-the-box default.
    assert DEFAULT_PAYMENT_PROVIDER == "prava"


def test_unknown_rail_falls_back_rather_than_raising():
    assert payment_provider("nope").name == "prava"
    assert payment_provider(None).name == "prava"


def test_razorpay_agent_note_forbids_the_prava_tools():
    note = PAYMENT_PROVIDERS["razorpay"].agent_note
    assert "do not call any `*_prava_*` tool" in note
    assert "start_razorpay_checkout" in note
    assert "get_razorpay_payment_status" in note


def test_payment_provider_setting_roundtrip(temp_db):
    from app.services import settings as settings_service

    assert settings_service.get_payment_provider() == "prava"
    settings_service.set_payment_provider("razorpay")
    assert settings_service.get_payment_provider() == "razorpay"

    # A stale/garbage stored value must not leave the session with no rail.
    temp_db.set_setting("payment_provider", "bitcoin")
    assert settings_service.get_payment_provider() == "prava"


# --- amount conversion (the classic 100x bug) ------------------------------


@pytest.mark.parametrize(
    "rupees,paise",
    [("119.00", 11900), ("119", 11900), ("0.50", 50), (250, 25000), ("1234.56", 123456)],
)
def test_rupees_convert_to_integer_paise(rupees, paise):
    assert razorpay_service.to_paise(rupees) == paise


@pytest.mark.parametrize("bad", ["free", "", None, "0", "-5"])
def test_bad_amounts_are_rejected(bad):
    with pytest.raises(RazorpayError):
        razorpay_service.to_paise(bad)


# --- configuration guards --------------------------------------------------


def test_razorpay_is_unconfigured_without_keys():
    assert razorpay_service.is_configured() is False


@pytest.mark.asyncio
async def test_calls_fail_closed_without_keys():
    with pytest.raises(RazorpayError, match="RAZORPAY_KEY_ID"):
        await razorpay_service.create_payment_link(total_amount="10.00", description="x")


def test_test_mode_is_detected_from_the_key_prefix(monkeypatch):
    monkeypatch.setattr(razorpay_service.settings, "razorpay_key_id", "rzp_test_abc")
    assert razorpay_service.is_test_mode() is True
    monkeypatch.setattr(razorpay_service.settings, "razorpay_key_id", "rzp_live_abc")
    assert razorpay_service.is_test_mode() is False


# --- payment link creation (stubbed transport) -----------------------------


@pytest.fixture
def stub_razorpay(monkeypatch):
    """Capture the outgoing request and reply with a canned Razorpay payload."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = __import__("json").loads(request.content or b"{}")
        return httpx.Response(
            200,
            json={
                "id": "plink_123",
                "short_url": "https://rzp.io/i/abc",
                "status": "created",
                "amount": 11900,
                "currency": "INR",
                "description": "Boppai grocery order",
            },
        )

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    monkeypatch.setattr(razorpay_service.settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(razorpay_service.settings, "razorpay_key_secret", "secret")
    return captured


@pytest.mark.asyncio
async def test_create_payment_link_sends_paise_and_returns_the_url(stub_razorpay):
    link = await razorpay_service.create_payment_link(
        total_amount="119.00",
        description="Boppai grocery order",
        products=[{"description": "Paneer 200 g", "quantity": 2}],
    )

    sent = stub_razorpay["json"]
    assert sent["amount"] == 11900, "amount must be integer paise, not rupees"
    assert sent["currency"] == "INR"
    assert sent["accept_partial"] is False
    # We have no verified sender identity, so Razorpay should not message the user.
    assert sent["notify"] == {"sms": False, "email": False}
    assert "Paneer 200 g x2" in sent["notes"]["items"]
    assert stub_razorpay["headers"]["authorization"].startswith("Basic ")

    assert link["id"] == "plink_123"
    assert link["shortUrl"] == "https://rzp.io/i/abc"
    assert link["testMode"] is True


@pytest.mark.asyncio
async def test_checkout_state_roundtrip(session, stub_razorpay):
    link = await razorpay_service.create_payment_link(total_amount="119.00", description="x")
    checkout_state.start(session, link, total_amount="119.00")

    exists, stored = checkout_state.read(session)
    assert exists
    assert stored["id"] == "plink_123"
    assert stored["totalAmount"] == "119.00"
    assert stored["status"] == "created"

    checkout_state.record_status(session, {"status": "paid", "paid": True})
    _, updated = checkout_state.read(session)
    assert updated["paid"] is True
    assert updated["id"] == "plink_123", "existing fields must survive a status update"


# --- session capability blocks --------------------------------------------


def test_payment_block_names_the_active_rail_and_warns_when_unconfigured(temp_db):
    from app.api.routes.chat import _build_payment_block
    from app.services import settings as settings_service

    settings_service.set_payment_provider("razorpay")
    block = _build_payment_block()
    assert "Razorpay (test mode)" in block
    assert "do not call any `*_prava_*` tool" in block
    # No keys in this environment, so it must say so rather than send the user to a
    # checkout that cannot complete.
    assert "NO credentials configured" in block

    settings_service.set_payment_provider("prava")
    assert "Prava" in _build_payment_block()


def test_browser_block_forbids_pretending_when_no_browser_is_wired():
    from app.api.routes.chat import _build_browser_block

    block = _build_browser_block()
    assert "NOT connected" in block
    assert "Never describe browser actions as though you performed them." in block
    # It must give the agent something it CAN do instead.
    assert "instamart.in/payment" in block
    assert "report_prava_merchant_outcome" in block


def test_browser_block_names_the_tool_when_one_is_wired(monkeypatch):
    from app.api.routes import chat as chat_routes
    from app.mcp.servers import create_browserclaw_mcp_server

    monkeypatch.setattr(
        chat_routes,
        "browserclaw_mcp_server",
        lambda: create_browserclaw_mcp_server("http://127.0.0.1:9010/mcp"),
    )
    block = chat_routes._build_browser_block()
    assert "BrowserClaw** is connected" in block
    assert "NOT connected" not in block
