"""
One-shot agent calls -- spawn the user's CLI as a throwaway, tool-less process that
answers a single prompt and exits.

Unlike the chat route this does NOT resume a session, wire up the Boppai MCP, or persist
anything to the transcript. It reuses each agent's OWN stream parser (the same one chat
uses) to accumulate the assistant's text, then hands the raw text back. That makes it the
shared primitive for backend-triggered generation: lazy per-day meal details and
whole-plan grocery-list consolidation both just take a prompt and want JSON back.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..agents.base import AgentDef, ChatArgs
from ..agents.runner import run_agent_once


async def spawn_one_shot(agent: AgentDef, prompt: str, *, cwd: Path | str) -> str:
    """Run `prompt` through `agent`'s CLI once and return the full visible reply text.

    `cwd` (a session folder) contains the run so nothing leaks into the repo. Raises
    RuntimeError on launch failure or a non-zero exit.
    """
    # No session ids  -> fresh ephemeral runtime (no transcript pollution).
    # No mcp wiring   -> no tools; the prompt itself is the whole instruction.
    argv = agent.build_chat_args(
        ChatArgs(model=agent.model, reasoning_effort=agent.reasoning_effort)
    )
    return await run_agent_once(agent, argv, cwd=cwd, prompt=agent.build_prompt(prompt, []))


def extract_json(text: Any) -> Any:
    """Pull a JSON object out of a model reply that may wrap it in prose or ``` fences.

    Grabs the outermost {...} span and parses it. Raises ValueError if nothing parses.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty response from agent")

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in agent response")

    return json.loads(text[start : end + 1])
