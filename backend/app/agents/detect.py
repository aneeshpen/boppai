"""
Detection -- for each agent def, answer two questions:
  1. Is the CLI installed?  (can we run `<bin> --version`?)
  2. Is it logged in?       (run the auth probe, parse the result)

The frontend uses this to paint the "we detected you have Claude" tiles.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..core.logging import get_logger
from .base import AgentDef
from .executable import resolve_executable
from .registry import AGENTS

log = get_logger("detect")

VERSION_TIMEOUT = 4.0
AUTH_TIMEOUT = 6.0


async def _run(argv: list[str], timeout: float) -> tuple[int, str, str]:
    """Run to completion, returning (returncode, stdout, stderr).

    Unlike Node's promisified execFile this does not raise on a non-zero exit -- the
    caller decides, because the auth probes legitimately exit non-zero when signed out.
    """
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise

    return (
        process.returncode or 0,
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
    )


async def probe(agent: AgentDef) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": agent.id,
        "name": agent.name,
        "tagline": agent.tagline,
        "bin": agent.bin,
        "supportsImages": agent.supports_images is True,
    }
    missing = {**base, "installed": False, "loggedIn": False, "account": None, "version": None}

    launcher = resolve_executable(agent.bin)
    if launcher is None:
        return missing

    # 1. Installed? -- a successful --version means the binary is on PATH.
    try:
        _, stdout, _ = await _run([*launcher, *agent.version_args], VERSION_TIMEOUT)
    except (OSError, asyncio.TimeoutError) as exc:
        log.info("[detect] %s version probe failed: %s", agent.bin, exc)
        return missing

    version = (stdout.strip().split("\n")[0] or None) if stdout.strip() else None

    # 2. Logged in? -- probe auth. Some CLIs exit non-zero when signed out, so we parse
    # the captured output regardless of the exit code.
    logged_in = False
    account = None
    try:
        _, auth_stdout, auth_stderr = await _run([*launcher, *agent.auth_probe_args], AUTH_TIMEOUT)
        status = agent.parse_auth(f"{auth_stdout}\n{auth_stderr}")
        logged_in, account = status.logged_in, status.account
    except (OSError, asyncio.TimeoutError) as exc:
        log.info("[detect] %s auth probe failed: %s", agent.bin, exc)

    return {**base, "installed": True, "version": version, "loggedIn": logged_in, "account": account}


async def detect_agents() -> list[dict[str, Any]]:
    """Probe every registered agent concurrently."""
    return list(await asyncio.gather(*(probe(agent) for agent in AGENTS.values())))
