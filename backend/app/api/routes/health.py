"""GET /api/health — trivial liveness check."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}
