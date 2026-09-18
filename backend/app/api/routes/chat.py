"""
POST /api/chat -- talk to the active session (spawns the CLI, streams SSE).

The core trick: we don't call any AI API with a key. We spawn the user's already-logged-in
CLI as a subprocess and parse its stream, re-emitting each event to the browser as a
Server-Sent Event.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...agents.base import AgentDef, ChatArgs
from ...agents.registry import AGENTS
from ...agents.runner import stream_agent_events
from ...core.config import AGENT_PROMPT
from ...core.deps import json_body
from ...core.errors import BoppaiError
from ...mcp.servers import (
    browserclaw_mcp_server,
    mcp_config_path_for_provider,
    mcp_servers_for_provider,
    provider_label,
)
from ...models.session import Session
from ...payments import is_configured as is_payment_configured
from ...payments import payment_provider
from ...services import attachments as attachments_service
from ...services import profile as profile_service
from ...services import sessions as sessions_service
from ...services import settings as settings_service
from ...sse import Event, sse_response

router = APIRouter()


def _build_provider_block(provider: str) -> str:
    """The authoritative note about which grocery service this session can use.

    Appended AFTER the static prompt so it overrides boppai.md's generic "one of these"
    text -- keeping the prompt in lockstep with the MCP actually wired (both come from
    the same provider setting), so the agent never offers a service it can't reach.
    """
    label = provider_label(provider)
    return "\n".join(
        [
            "\n\n---",
            "## Grocery service connected this session",
            "",
            f"This session is connected to **{label}** ONLY. Its MCP tools are the only grocery",
            "tools you have. Do NOT mention, offer, or attempt any other grocery service (for",
            "example Zepto when it is not the one named here) — it is not connected right now.",
            f"When the user wants to search, add to their store cart, or order groceries, use the {label} tools.",
        ]
    )


def _build_browser_block() -> str:
    """State plainly whether this session can drive a browser.

    Without this the agent is in an impossible position: the prompt file tells it to use
    BrowserClaw for the final merchant handoff, but BrowserClaw is optional and unwired by
    default. Told to do something it has no tool for, a model will narrate the steps as if
    it had performed them -- in the middle of a payment, which is the worst possible place
    to hallucinate. So the capability is declared per-session, exactly like the grocery
    provider, and the no-browser branch gives the agent a real alternative (hand the steps
    to the user) instead of an instruction it cannot honour.
    """
    server = browserclaw_mcp_server()

    if server is not None:
        label = re.sub(r"\s*MCP$", "", server.label)
        return "\n".join(
            [
                "\n\n---",
                "## Browser automation connected this session",
                "",
                f"**{label}** is connected. Use its tools for the visible merchant handoff",
                "described in the Prava section above.",
            ]
        )

    return "\n".join(
        [
            "\n\n---",
            "## Browser automation is NOT connected this session",
            "",
            "You have NO browser automation tool. Ignore every instruction above that tells",
            "you to open a page, click, or fill a form yourself -- you cannot do any of it.",
            "Never describe browser actions as though you performed them.",
            "",
            "When a Prava credential is ready, instead: tell the user the approval succeeded,",
            "give them the card details to enter themselves at https://instamart.in/payment",
            "(Add New Card), ask them to tell you what the page showed afterwards, and only",
            "then call `report_prava_merchant_outcome` with what they report.",
        ]
    )


def _build_payment_block() -> str:
    """Which payment rail is live this session, and whether it is actually usable.

    boppai.md still documents the Prava flow in full (it is the hackathon integration and
    the reason the award exists), but it states "Prava is the ONLY payment method" — which
    stops being true the moment a second rail exists. This block is appended after the
    static prompt, so like the grocery provider it is the authoritative word and overrides
    that line when the session is on Razorpay.

    The unconfigured case matters just as much: with no credentials the agent must say so
    up front rather than walking the user to a checkout that cannot complete.
    """
    name = settings_service.get_payment_provider()
    provider = payment_provider(name)
    configured = is_payment_configured(name)

    lines = [
        "\n\n---",
        "## Payment method for this session",
        "",
        f"This session's payment rail is **{provider.label}**.",
        "",
        provider.agent_note,
    ]

    if not configured:
        lines += [
            "",
            f"WARNING: {provider.label} has NO credentials configured on this machine, so a",
            "payment CANNOT be completed right now. You may still plan, search, and build the",
            "cart. If the user asks to pay, tell them plainly that this rail is not configured",
            "and stop — do not start a checkout that cannot succeed.",
        ]

    return "\n".join(lines)


def build_system_prompt(provider: str) -> str:
    """The conductor's brain = the prompt file + the connected grocery provider + the
    browser capability + the payment rail + the current profile (or an onboarding note if
    there's no profile yet). Rebuilt every turn so all of them are always fresh."""
    base = AGENT_PROMPT.read_text(encoding="utf-8")
    saved = profile_service.read()
    dynamic = (
        f"\n\n---\n## The user's saved profile (current)\n\n{saved.markdown}"
        if saved.exists
        else (
            "\n\n---\n\nThe user has NO saved profile yet. This is onboarding — "
            "follow the onboarding section above."
        )
    )
    return (
        base
        + _build_provider_block(provider)
        + _build_payment_block()
        + _build_browser_block()
        + dynamic
    )


OPENING_PROMPT = "\n".join(
    [
        "Start this Boppai conversation now.",
        "Decide the first assistant message from the saved profile context in your system prompt.",
        "If the saved profile is missing or has no real name, ask for the name first in a natural, creative way.",
        "If the profile has a name but is thin, greet them by name and ask for a little stable food-profile context.",
        "If the profile is useful enough, greet them naturally and ask what they want to cook today.",
        "Write only the user-visible assistant message. Do not mention this instruction.",
    ]
)


def prepare_session(agent_id: Any) -> tuple[AgentDef, Session]:
    agent = AGENTS.get(agent_id) if isinstance(agent_id, str) else None
    if agent is None:
        raise BoppaiError(f"Unknown agent: {agent_id}")

    # Everything hangs off the ONE active session.
    session = sessions_service.get_or_create_active()

    # Safety net: a session belongs to the agent that started it. If a turn arrives for a
    # different agent (e.g. a switch that bypassed the confirm dialog), don't resume the
    # old agent's session -- archive it and open a fresh one for this agent.
    if session.agent and session.agent != agent_id:
        session = sessions_service.start_new(agent_id)

    return agent, session


def _turn_events(
    *,
    agent: AgentDef,
    session: Session,
    prompt: str,
    image_paths: list[str],
) -> AsyncIterator[Event]:
    """One conductor turn: spawn, stream, persist.

    Assistant text is persisted in a `finally` so a mid-turn browser disconnect still
    saves whatever was written -- the Node build behaved the same way, because its
    child 'close' handler ran even after the SIGTERM it sent on `res.close`.
    """
    # Which grocery provider this session is on decides both the MCP wired in and the
    # provider note in the system prompt -- read once here so the two can't disagree.
    provider = settings_service.get_provider()

    argv = agent.build_chat_args(
        ChatArgs(
            boppai_session_id=session.id,
            runtime_session_id=session.runtime_session_id,
            mcp_config_path=str(mcp_config_path_for_provider(provider)),
            mcp_servers=mcp_servers_for_provider(provider),
            system_prompt=build_system_prompt(provider),
            model=agent.model,
            reasoning_effort=agent.reasoning_effort,
            image_paths=image_paths,
        )
    )

    async def generate() -> AsyncIterator[Event]:
        assistant_text: list[str] = []
        persisted = False

        def persist() -> None:
            nonlocal persisted
            if persisted:
                return
            persisted = True
            text = "".join(assistant_text).strip()
            if text:
                sessions_service.add_message(session.id, "assistant", text)

        try:
            async for event in stream_agent_events(
                agent,
                argv,
                cwd=session.folder,
                # Each adapter decides how images reach its runtime: Codex feeds the saved
                # paths as `--image` argv; Claude appends them to the prompt for its Read
                # tool. build_prompt returns the prompt untouched when there are no images,
                # so the opening turn is unaffected.
                prompt=agent.build_prompt(prompt, image_paths),
            ):
                if event.get("type") == "delta" and event.get("text"):
                    assistant_text.append(event["text"])
                elif event.get("type") == "session" and event.get("sessionId"):
                    sessions_service.set_runtime_session_id(session.id, event["sessionId"])
                yield event

            persist()
            yield {"type": "end"}
        finally:
            # Covers the disconnect path, where yielding is no longer allowed.
            persist()

    return generate()


def _stream_turn(
    *,
    agent: AgentDef,
    session: Session,
    prompt: str,
    persist_user_message: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    image_paths: list[str] | None = None,
) -> StreamingResponse:
    if persist_user_message is not None:
        sessions_service.add_message(
            session.id, "user", persist_user_message, attachments or []
        )
        sessions_service.set_title_if_empty(
            session.id, persist_user_message.strip() or "Image attachment"
        )

    return sse_response(
        _turn_events(
            agent=agent, session=session, prompt=prompt, image_paths=image_paths or []
        )
    )


@router.post("/api/chat/opening")
async def chat_opening(body: dict[str, Any] = Depends(json_body)) -> StreamingResponse:
    agent, session = prepare_session(body.get("agent"))

    if sessions_service.messages_for(session.id):
        raise BoppaiError("Session already has messages", status=409)

    return _stream_turn(agent=agent, session=session, prompt=OPENING_PROMPT)


@router.post("/api/chat")
async def chat(body: dict[str, Any] = Depends(json_body)) -> StreamingResponse:
    agent, session = prepare_session(body.get("agent"))

    message = body.get("message")
    text = message.strip() if isinstance(message, str) else ""
    images = body.get("images") or []

    if not text and not (isinstance(images, list) and images):
        raise BoppaiError("Empty message")
    if isinstance(images, list) and images and not agent.supports_images:
        raise BoppaiError(f"Image chat isn't supported for {agent.name}.")

    try:
        saved_attachments, image_paths = attachments_service.save_image_attachments(
            session, images
        )
    except ValueError as exc:
        raise BoppaiError(str(exc)) from exc

    return _stream_turn(
        agent=agent,
        session=session,
        prompt=text or "Please respond to the attached image.",
        persist_user_message=text,
        attachments=saved_attachments,
        image_paths=image_paths,
    )


@router.post("/api/chat/internal-handoff")
async def chat_internal_handoff(
    body: dict[str, Any] = Depends(json_body),
) -> StreamingResponse:
    """The Prava credential handoff: the model gets browser instructions, while the
    transcript shows the short user-facing line instead."""
    agent, session = prepare_session(body.get("agent"))

    message = body.get("message")
    transcript_message = body.get("transcriptMessage")
    prompt = message.strip() if isinstance(message, str) else ""
    visible = transcript_message.strip() if isinstance(transcript_message, str) else ""

    if not prompt:
        raise BoppaiError("Empty internal handoff message")

    return _stream_turn(
        agent=agent,
        session=session,
        prompt=prompt,
        persist_user_message=visible or "Internal payment handoff.",
    )
