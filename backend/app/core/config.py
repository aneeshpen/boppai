"""
Configuration — every environment variable the Node backend read, with the same
names, meanings, and defaults.

Two decisions worth explaining:

1. JavaScript falsy semantics. The Node code read every setting as
   `process.env.X || 'default'`, and in JS an empty string is falsy. The shipped
   .env.example sets several keys to empty values, so `PRAVA_BACKEND_URL=` meant
   "use the sandbox default". `_drop_blanks` reproduces that by removing blank
   values before validation so the field default applies. Doing the obvious Python
   thing instead would silently change behavior for anyone using the example .env.

2. Pure module. This file only computes values; it never touches the disk. The
   folders and files these paths point at are created by core/boot.py, so importing
   a path can't have a side effect.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CORE_DIR = Path(__file__).resolve().parent
APP_DIR = CORE_DIR.parent
BACKEND_ROOT = APP_DIR.parent


class Settings(BaseSettings):
    """Environment-backed settings. Field names map to the Node env var names."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    port: int = 8787

    prava_backend_url: str = "https://sandbox.api.prava.space"
    prava_publishable_key: str = ""
    merchant_secret_key: str = ""
    boppai_public_app_url: str = ""
    boppai_user_id: str = "boppai-local-user"
    boppai_user_email: str = ""
    browserclaw_mcp_url: str = ""

    # Razorpay test mode -- the free, no-cost payment path that works without the
    # hackathon-era Prava credentials. Test keys look like `rzp_test_*`; nothing here
    # ever moves real money.
    razorpay_api_url: str = "https://api.razorpay.com"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""

    # The Node build hardcoded cors({ origin: '*' }) because this is a local,
    # single-user harness the Vite dev server talks to. Kept as the default for
    # behavioral parity, but overridable (comma-separated) rather than hardcoded.
    cors_allow_origins: str = "*"

    @model_validator(mode="before")
    @classmethod
    def _drop_blanks(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not (isinstance(v, str) and not v.strip())}
        return data

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def api_url(self) -> str:
        """The URL the MCP tool subprocess calls back into (single write path)."""
        return f"http://localhost:{self.port}"


settings = Settings()

# --- paths -----------------------------------------------------------------

DATA_DIR = BACKEND_ROOT / "data"
SESSIONS_DIR = BACKEND_ROOT / "sessions"
DB_PATH = DATA_DIR / "boppai.db"
PROFILE_PATH = DATA_DIR / "profile.md"
AGENT_PROMPT = BACKEND_ROOT / "prompts" / "boppai.md"
BASKET_FILL_PROMPT = BACKEND_ROOT / "prompts" / "basket-fill.md"

# How the bundled MCP server is launched. The Node build used `process.execPath`
# plus a script path; the Python equivalent is this interpreter (so the venv that
# has `mcp` installed is the one that runs) plus `-m`, with PYTHONPATH pointing at
# BACKEND_ROOT so `app.mcp.server` resolves in the child.
MCP_SERVER_COMMAND = sys.executable
MCP_SERVER_ARGS = ["-m", "app.mcp.server"]
