"""
Small request helpers shared by the routers.

`json_body` exists to reproduce one specific Express habit: every Node route read
`req.body || {}` and then hand-checked the fields it cared about. Declaring those
bodies as required Pydantic models instead would turn a missing or malformed body
into a 422 with a different JSON shape, so the routers take the raw request and
validate exactly where — and how — the Node code did.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request


async def json_body(request: Request) -> dict[str, Any]:
    """The parsed JSON object, or {} when the body is absent, empty, or not an object."""
    try:
        raw = await request.body()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        import json

        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}
