"""
Boppai harness backend — entry point.

This file does three things and nothing else: run one-time boot side-effects on
startup, assemble the FastAPI app from the router modules, and expose `app`. Each
concern lives in its own file so this stays a readable table of contents.

  api/routes/health.py    GET  /api/health
  api/routes/detect.py    GET  /api/detect                 -> which agents are installed + logged in
  api/routes/tools.py     GET  /api/tools                  -> the tools our bundled (local) MCP exposes
  api/routes/mcp.py       GET  /api/mcp/remote             -> list the remote MCP servers (Zepto, Swiggy Instamart)
                       GET  /api/mcp/remote/{name}/tools -> live status + tool catalog for one remote MCP
  api/routes/chat.py      POST /api/chat/opening           -> let the selected CLI write the first assistant message
                       POST /api/chat                   -> talk to the active session (spawns the CLI, streams SSE)
  api/routes/sessions.py  GET  /api/session/current        -> the active session + its transcript
                       POST /api/session/new            -> archive the current session, start a fresh one
                       GET  /api/sessions               -> list every session (history/debug view)
  api/routes/calendar.py  GET/PATCH /api/session/calendar  -> active session meal planner
                       GET/POST  /internal/calendar     -> MCP-facing planner read/write
  api/routes/basket.py    GET  /api/session/basket         -> active session Basket
                       GET/POST  /internal/basket       -> MCP-facing Basket read/write
  api/routes/prava.py     GET/POST /api/prava/*            -> Prava embedded payment session + polling
  api/routes/profile.py   GET/PUT  /api/profile            -> read / save the user's profile.md
                       GET/POST /internal/profile       -> the same, for the MCP tool
  api/routes/settings.py  GET/PUT  /api/settings/agent     -> the remembered agent pick

The core trick is unchanged from the Node build: we don't call any AI API with a key.
We spawn the user's already-logged-in CLI as a subprocess and parse its stream.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import (
    basket,
    chat,
    calendar,
    detect,
    health,
    mcp,
    prava,
    profile,
    razorpay,
    sessions,
    settings as settings_routes,
    tools,
)
from .core.boot import boot, shutdown
from .core.config import settings
from .core.errors import register_error_handlers
from .core.logging import get_logger, setup_logging

log = get_logger("main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Make sure our folders + DB exist, and materialize the MCP configs, before serving.
    setup_logging()
    boot()
    log.info("[boppai] backend ready")
    try:
        yield
    finally:
        shutdown()


app = FastAPI(title="Boppai backend", lifespan=lifespan)

# The Node build used cors({ origin: '*' }) with no credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

# Each router declares its own full paths, so they all mount at the root.
for router in (
    health.router,
    detect.router,
    tools.router,
    mcp.router,
    profile.router,
    settings_routes.router,
    sessions.router,
    calendar.router,
    basket.router,
    prava.router,
    razorpay.router,
    chat.router,
):
    app.include_router(router)
