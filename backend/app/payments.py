"""
The payment rails Boppai can drive, and what each one needs to be usable.

Two on purpose:

* **Prava** — the original hackathon integration. Kept exactly as it was, because it is
  what the award was won with and it demonstrates the agentic one-time-credential flow.
  It needs merchant credentials that are no longer available, so it will usually report
  itself unconfigured.
* **Razorpay (test mode)** — the free path. Test keys (`rzp_test_*`) cost nothing and
  move no real money, so the payment flow stays demoable by anyone who clones this repo.
  It works through Payment Links, which means the agent can hand the user a URL in chat
  and poll for the result — no card data ever touches Boppai.

Registry-shaped like `mcp/servers.py` so adding a third rail later is a descriptor plus a
service, not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass

from .core.config import settings


@dataclass(frozen=True)
class PaymentProvider:
    name: str
    label: str
    description: str
    # What the agent is told it can do with this rail, injected into the system prompt.
    agent_note: str


PRAVA = PaymentProvider(
    name="prava",
    label="Prava",
    description=(
        "Prava agentic payments — the original hackathon integration. Mints a one-time "
        "card credential the agent hands to browser automation for the merchant form."
    ),
    agent_note=(
        "Payment goes through **Prava**. Follow the Prava section above exactly: read the "
        "live cart, get explicit confirmation, then `start_prava_checkout`. Never offer "
        "UPI, QR, or cash on delivery."
    ),
)

RAZORPAY = PaymentProvider(
    name="razorpay",
    label="Razorpay (test mode)",
    description=(
        "Razorpay Payment Links in test mode. Free, no real money, no card data handled "
        "by Boppai — the user pays on Razorpay's own hosted page."
    ),
    agent_note=(
        "Payment goes through **Razorpay test mode**, NOT Prava. Ignore the Prava section "
        "above — do not call any `*_prava_*` tool.\n"
        "The flow is:\n"
        "1. Read the live cart with the grocery service's `get_cart` tool.\n"
        "2. Summarize the exact items, delivery address and final payable total.\n"
        "3. Ask for explicit confirmation to pay. Wait for a clear yes.\n"
        "4. Call `start_razorpay_checkout` with that exact total and the cart lines.\n"
        "5. Give the user the returned payment link as a Markdown link and tell them it is "
        "a TEST payment — no real money moves.\n"
        "6. When they say they have paid, call `get_razorpay_payment_status` to confirm, "
        "and only report success if it actually comes back paid."
    ),
)

PAYMENT_PROVIDERS: dict[str, PaymentProvider] = {
    PRAVA.name: PRAVA,
    RAZORPAY.name: RAZORPAY,
}

# Prava stays the default so the original hackathon demo is unchanged out of the box.
DEFAULT_PAYMENT_PROVIDER = PRAVA.name


def payment_provider(name: str | None) -> PaymentProvider:
    return PAYMENT_PROVIDERS.get(name or "", PAYMENT_PROVIDERS[DEFAULT_PAYMENT_PROVIDER])


def is_configured(name: str | None) -> bool:
    """Whether the named rail actually has usable credentials right now."""
    provider = payment_provider(name)
    if provider.name == "razorpay":
        return bool(settings.razorpay_key_id and settings.razorpay_key_secret)
    return settings.merchant_secret_key.startswith("sk_") and bool(settings.boppai_user_email)
