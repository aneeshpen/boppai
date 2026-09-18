"""
Server-Sent Events -- the exact wire format the Node build produced.

The frontend hand-parses this stream (frontend/src/api.js `readSseStream`): it splits on
a blank line and takes the first line starting with `data:`. So the contract is narrow
and worth stating explicitly:

  * one JSON object per frame, written as `data: {...}\\n\\n`
  * no `event:` or `id:` fields, and no heartbeat/ping comments
  * `ensure_ascii=False`, because JSON.stringify left characters like "\\u20b9" intact
    and the frontend renders prices straight from these payloads

That is why this uses a plain StreamingResponse rather than a library like
sse-starlette: the library's default keep-alive comments would add frames the Node
backend never sent.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse

Event = dict[str, Any]

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}


def sse_frame(event: Event) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def sse_response(events: AsyncIterator[Event]) -> StreamingResponse:
    """Wrap an async event iterator as an SSE response."""

    async def body() -> AsyncIterator[str]:
        async for event in events:
            yield sse_frame(event)

    return StreamingResponse(body(), media_type="text/event-stream", headers=SSE_HEADERS)
