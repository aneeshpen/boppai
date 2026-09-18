"""
Persisted app settings — thin typed accessors over the key/value table.

Kept as a service so app code shares one definition of each key and its encoding,
instead of sprinkling raw get_setting('...') calls and magic strings.
"""

from __future__ import annotations

from ..mcp.servers import DEFAULT_PROVIDER
from ..payments import DEFAULT_PAYMENT_PROVIDER, PAYMENT_PROVIDERS
from ..persistence import database as db


def get_agent() -> str | None:
    """The remembered agent pick ('claude' | 'codex' | None)."""
    return db.get_setting("agent")


def set_agent(agent: str) -> None:
    db.set_setting("agent", agent)


def get_provider() -> str:
    """The remembered grocery provider pick.

    Unlike the agent, this always resolves to a usable value: a first-time user has
    no stored pick, so we fall back to the working default rather than returning None.
    """
    return db.get_setting("provider") or DEFAULT_PROVIDER


def set_provider(provider: str) -> None:
    db.set_setting("provider", provider)


def get_payment_provider() -> str:
    """Which payment rail this session uses ('prava' | 'razorpay').

    Same shape as the grocery provider: always resolves to something usable. Prava is
    the hackathon integration and stays the default so the original demo still works;
    Razorpay test mode is the free path for everyone else.
    """
    stored = db.get_setting("payment_provider")
    return stored if stored in PAYMENT_PROVIDERS else DEFAULT_PAYMENT_PROVIDER


def set_payment_provider(provider: str) -> None:
    db.set_setting("payment_provider", provider)
