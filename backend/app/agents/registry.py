"""
Agent registry -- the ONE file you touch to add or switch a brain.

Each brain's adapter (how to check auth, build the chat command, and which stream
parser reads its output) lives in its own module. This file just assembles them into
the lookup the rest of the app uses, so the upper layer stays symmetric: any
brain-specific quirk is sealed in its file.

Add a brain = write ./<name>.py and add it to AGENTS below. Switch brains = pick a
different key; nothing else in the app knows the difference.
"""

from __future__ import annotations

from .base import AgentDef
from .claude import claude
from .codex import codex

AGENTS: dict[str, AgentDef] = {"claude": claude, "codex": codex}

DEFAULT_AGENT_ID = "claude"


def get(agent_id: str | None) -> AgentDef | None:
    return AGENTS.get(agent_id or "")


def get_or_default(agent_id: str | None) -> AgentDef:
    """The named agent, falling back to Claude.

    Mirrors the Node routes' `AGENTS[session.agent] || AGENTS.claude`, used by the
    backend-triggered runs (day details, grocery list, basket fill) where a session
    may predate the `agent` column.
    """
    return AGENTS.get(agent_id or "", AGENTS[DEFAULT_AGENT_ID])
