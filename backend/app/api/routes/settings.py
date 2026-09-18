"""
Persisted settings the UI can read/flip.

  GET/PUT /api/settings/agent    -> the remembered agent pick ('claude' | 'codex' | null)
  GET/PUT /api/settings/provider -> the remembered grocery provider pick

The values themselves live in services/settings.py; this is just HTTP + validation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...agents.registry import AGENTS
from ...core.deps import json_body
from ...core.errors import BoppaiError
from ...mcp.servers import REMOTE_MCP_SERVERS
from ...payments import PAYMENT_PROVIDERS, is_configured, payment_provider
from ...services import settings as settings_service

router = APIRouter()

# The provider names we accept, taken straight from the remote MCP registry so this
# never drifts from what can actually be wired.
_PROVIDER_NAMES = {server.name for server in REMOTE_MCP_SERVERS}


@router.get("/api/settings/agent")
async def get_agent() -> dict[str, Any]:
    return {"agent": settings_service.get_agent()}


@router.put("/api/settings/agent")
async def put_agent(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    agent = body.get("agent")
    if agent not in AGENTS:
        raise BoppaiError(f"Unknown agent: {agent}")
    settings_service.set_agent(agent)
    return {"agent": agent}


@router.get("/api/settings/provider")
async def get_provider() -> dict[str, Any]:
    return {"provider": settings_service.get_provider()}


@router.put("/api/settings/provider")
async def put_provider(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    provider = body.get("provider")
    if provider not in _PROVIDER_NAMES:
        raise BoppaiError(f"Unknown provider: {provider}")
    settings_service.set_provider(provider)
    return {"provider": provider}


@router.get("/api/settings/payment-provider")
async def get_payment_provider() -> dict[str, Any]:
    """The payment rail, plus whether each one actually has credentials right now."""
    current = settings_service.get_payment_provider()
    return {
        "provider": current,
        "configured": is_configured(current),
        "providers": [
            {
                "name": provider.name,
                "label": provider.label,
                "description": provider.description,
                "configured": is_configured(provider.name),
            }
            for provider in PAYMENT_PROVIDERS.values()
        ],
    }


@router.put("/api/settings/payment-provider")
async def put_payment_provider(body: dict[str, Any] = Depends(json_body)) -> dict[str, Any]:
    provider = body.get("provider")
    if provider not in PAYMENT_PROVIDERS:
        raise BoppaiError(f"Unknown payment provider: {provider}")
    settings_service.set_payment_provider(provider)
    return {"provider": provider, "configured": is_configured(provider)}
