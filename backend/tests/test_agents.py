"""Port of backend/test/agents.test.js -- CLI argv construction for both brains.

This is where a port goes wrong invisibly: a flag in the wrong order, a TOML value
quoted differently, a resume id that isn't last. The assertions are deliberately literal.
"""

from __future__ import annotations

import json

from app.agents.base import ChatArgs
from app.agents.registry import AGENTS
from app.core.boot import build_mcp_config
from app.mcp.servers import McpServerDescriptor

MCP_SERVER = McpServerDescriptor(
    name="boppai",
    label="Boppai MCP",
    description="local tools",
    command="/path with spaces/node",
    args=["/repo/backend/src/mcp/boppai-mcp.js"],
    env={"BOPPAI_API_URL": "http://localhost:8787"},
    tool_approvals={
        "get_profile": "approve",
        "save_profile": "approve",
        "show_chat": "approve",
        "show_calendar": "approve",
    },
)

ZEPTO_MCP_SERVER = McpServerDescriptor(
    name="zepto",
    label="Zepto MCP",
    description="remote",
    command="npx",
    args=["mcp-remote", "https://mcp.zepto.co.in/mcp"],
    required=False,
)


def config_value(args: list[str], key: str) -> str | None:
    """The TOML literal Codex would parse for `-c key=<value>`, or None."""
    prefix = f"{key}="
    for index, token in enumerate(args):
        if token == "-c" and index + 1 < len(args) and args[index + 1].startswith(prefix):
            return args[index + 1][len(prefix) :]
    return None


# --- Claude ----------------------------------------------------------------


def test_claude_starts_and_resumes_through_the_same_contract():
    start = AGENTS["claude"].build_chat_args(
        ChatArgs(
            boppai_session_id="boppai-uuid",
            runtime_session_id=None,
            mcp_config_path="/tmp/boppai.mcp.json",
            system_prompt="You are Boppai.",
            model="sonnet",
        )
    )
    assert start[-2:] == ["--session-id", "boppai-uuid"]
    assert "--mcp-config" in start
    assert "--strict-mcp-config" not in start
    assert "--append-system-prompt" in start

    resume = AGENTS["claude"].build_chat_args(
        ChatArgs(boppai_session_id="boppai-uuid", runtime_session_id="claude-runtime-id")
    )
    assert resume[-2:] == ["--resume", "claude-runtime-id"]
    assert "--session-id" not in resume


def test_claude_mcp_config_includes_boppai_and_zepto_as_separate_servers():
    assert build_mcp_config([MCP_SERVER, ZEPTO_MCP_SERVER]) == {
        "mcpServers": {
            "boppai": {
                "command": MCP_SERVER.command,
                "args": MCP_SERVER.args,
                "env": MCP_SERVER.env,
            },
            "zepto": {
                "command": "npx",
                "args": ["mcp-remote", "https://mcp.zepto.co.in/mcp"],
            },
        }
    }


def test_claude_injects_image_paths_and_passes_text_through_untouched():
    with_images = AGENTS["claude"].build_prompt(
        "What can I cook with these?",
        ["/repo/sessions/s1/attachments/a.png", "/repo/sessions/s1/attachments/b.webp"],
    )
    assert "What can I cook with these?" in with_images
    assert "Read tool" in with_images
    assert "/repo/sessions/s1/attachments/a.png" in with_images
    assert "/repo/sessions/s1/attachments/b.webp" in with_images

    # No images -> prompt is returned verbatim (the opening turn must be unaffected).
    assert AGENTS["claude"].build_prompt("hi", []) == "hi"
    assert AGENTS["claude"].build_prompt("hi") == "hi"

    # Both brains advertise image support and expose the same-named hook.
    assert AGENTS["claude"].supports_images is True
    assert AGENTS["codex"].supports_images is True
    assert AGENTS["codex"].build_prompt("hi", ["/x.png"]) == "hi"


# --- Codex -----------------------------------------------------------------


def test_codex_starts_fresh_with_contained_prompt_and_mcp_configuration():
    prompt = 'You are "Boppai".\nProfile path: C:\\Users\\boppai'
    args = AGENTS["codex"].build_chat_args(
        ChatArgs(
            boppai_session_id="boppai-uuid",
            runtime_session_id=None,
            mcp_servers=[MCP_SERVER, ZEPTO_MCP_SERVER],
            system_prompt=prompt,
            model=AGENTS["codex"].model,
            reasoning_effort=AGENTS["codex"].reasoning_effort,
        )
    )

    assert args[:3] == ["exec", "--json", "--skip-git-repo-check"]
    assert "resume" not in args
    model_at = args.index("--model")
    assert args[model_at : model_at + 2] == ["--model", "gpt-5.6-terra"]

    assert config_value(args, "model_reasoning_effort") == '"medium"'
    assert "--ignore-user-config" in args
    assert "--ignore-rules" not in args
    assert "--disable" not in args
    assert config_value(args, "sandbox_mode") == '"read-only"'
    assert config_value(args, "approval_policy") is None
    assert config_value(args, "project_doc_max_bytes") == "0"

    # The system prompt must survive quotes, newlines and Windows backslashes intact.
    assert config_value(args, "developer_instructions") == json.dumps(prompt)

    assert config_value(args, "mcp_servers.boppai.command") == json.dumps(MCP_SERVER.command)
    assert config_value(args, "mcp_servers.boppai.args") == json.dumps(
        MCP_SERVER.args, separators=(",", ":")
    )
    assert config_value(args, "mcp_servers.boppai.env.BOPPAI_API_URL") == json.dumps(
        MCP_SERVER.env["BOPPAI_API_URL"]
    )
    assert config_value(args, "mcp_servers.boppai.required") == "true"
    for tool in ("get_profile", "save_profile", "show_chat", "show_calendar"):
        assert config_value(args, f"mcp_servers.boppai.tools.{tool}.approval_mode") == '"approve"'
    assert config_value(args, "mcp_servers.boppai.tools.create_cart.approval_mode") is None

    assert config_value(args, "mcp_servers.zepto.command") == json.dumps(ZEPTO_MCP_SERVER.command)
    assert config_value(args, "mcp_servers.zepto.args") == json.dumps(
        ZEPTO_MCP_SERVER.args, separators=(",", ":")
    )
    assert config_value(args, "mcp_servers.zepto.required") == "false"
    assert config_value(args, "mcp_servers.zepto.env.BOPPAI_API_URL") is None


def test_codex_resume_keeps_every_flag_before_the_runtime_id():
    args = AGENTS["codex"].build_chat_args(
        ChatArgs(
            runtime_session_id="codex-runtime-id",
            mcp_servers=[MCP_SERVER],
            system_prompt="Fresh profile",
            image_paths=["/tmp/first.png", "/tmp/second.webp"],
        )
    )

    assert args[:3] == ["exec", "resume", "--json"]
    assert args[-1] == "codex-runtime-id"

    image_at = args.index("--image")
    assert args[image_at : image_at + 4] == [
        "--image",
        "/tmp/first.png",
        "--image",
        "/tmp/second.webp",
    ]
    assert "--sandbox" not in args
    assert config_value(args, "sandbox_mode") == '"read-only"'
    assert args.index("-c") < args.index("codex-runtime-id")
    assert args.index("--image") < args.index("codex-runtime-id")


def test_codex_toml_literals_are_valid_toml_not_python_repr():
    from app.agents.codex import toml_literal

    # `bool` must render lowercase -- Python's str(True) would emit "True", which is not
    # valid TOML and would silently disable a required MCP server.
    assert toml_literal(True) == "true"
    assert toml_literal(False) == "false"
    assert toml_literal(0) == "0"
    assert toml_literal("a b") == '"a b"'
    assert toml_literal(["x", "y"]) == '["x","y"]'
    assert toml_literal("C:\\Users\\t") == '"C:\\\\Users\\\\t"'
