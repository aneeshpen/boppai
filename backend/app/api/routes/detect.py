"""GET /api/detect -- which agents are installed + logged in."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...agents.detect import detect_agents
from ...core.errors import BoppaiError

router = APIRouter()


@router.get("/api/detect")
async def detect() -> dict[str, Any]:
    try:
        return {"agents": await detect_agents()}
    except Exception as exc:  # noqa: BLE001 - mirrors the Express catch-all 500
        raise BoppaiError(str(exc) or "detect failed", status=500) from exc
