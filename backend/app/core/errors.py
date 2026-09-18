"""
Error handling — keeps the wire shape Express produced.

The frontend reads `data.error` on every failed call (see frontend/src/api.js), so
FastAPI's defaults are a contract break on two counts: HTTPException serializes to
{"detail": ...}, and a Pydantic validation failure returns 422 where the Node code
returned a hand-written 400 {"error": "..."}.

So app code raises BoppaiError, and the handlers below render it exactly the way the
Express routes did. `code` and `responseId` are optional extras that only the Prava
routes populate — they are omitted entirely when unset, matching JSON.stringify
dropping undefined values.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import get_logger

log = get_logger("errors")


class BoppaiError(Exception):
    """An error that should reach the browser as {"error": ...} with a chosen status."""

    def __init__(
        self,
        message: str,
        status: int = 400,
        *,
        code: str | None = None,
        response_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.response_id = response_id
        self.extra = extra or {}

    def body(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.message}
        if self.code is not None:
            payload["code"] = self.code
        if self.response_id is not None:
            payload["responseId"] = self.response_id
        payload.update({k: v for k, v in self.extra.items() if v is not None})
        return payload


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BoppaiError)
    async def _boppai(_request: Request, exc: BoppaiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body())

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Express had no automatic body validation; its routes hand-checked and
        # returned 400. Mirror that rather than leaking FastAPI's 422 shape.
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        message = first.get("msg", "Invalid request body")
        return JSONResponse(
            status_code=400,
            content={"error": f"{field}: {message}" if field else message},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(status_code=exc.status_code, content={"error": detail})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("[boppai] unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"error": str(exc) or "Internal error"})
