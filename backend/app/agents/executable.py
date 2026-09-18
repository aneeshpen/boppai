"""
Resolving a CLI name to something `asyncio.create_subprocess_exec` can actually launch.

Node's `child_process.spawn('claude', ...)` leaned on libuv's PATH lookup. Python's
`create_subprocess_exec` goes straight to CreateProcess on Windows, which has two
differences that bite:

  * it needs the PATHEXT-resolved path, so `shutil.which` does that lookup for us and
    also gives us a clean "is it installed?" answer, and
  * it cannot execute a `.cmd`/`.bat` shim at all.

That second point is a real production hazard, not a theoretical one. `codex` installs
via npm as `codex.CMD`, and Codex receives its whole MCP configuration as
`-c key="{...}"` TOML values packed with quotes, braces and Windows backslashes. Routing
those through `cmd.exe /c` re-parses the quoting and corrupts them -- the agent would
launch with silently mangled (or missing) MCP servers.

So instead of shelling out, we look inside the shim. An npm `.cmd` shim is a fixed
template whose payload line is just:

    "%_prog%" "%dp0%\\node_modules\\<pkg>\\bin\\<name>.js" %*

i.e. `node <script> <args>`. Extracting that script path lets us exec `node` directly
with an argv array -- no shell, no re-quoting, nothing to escape. `cmd.exe /c` remains
only as a last-resort fallback for shims we cannot parse.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from ..core.logging import get_logger

log = get_logger("executable")

_BATCH_SUFFIXES = {".cmd", ".bat"}

# The payload line of an npm-generated .cmd shim. `%dp0%` is the shim's own directory.
_NPM_SHIM_SCRIPT_RE = re.compile(r'"%dp0%\\(node_modules\\.+?\.js)"', re.IGNORECASE)


def _resolve_npm_shim(shim: Path) -> list[str] | None:
    """Turn an npm `.cmd` shim into the `[node, script]` argv it really runs."""
    try:
        text = shim.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    match = _NPM_SHIM_SCRIPT_RE.search(text)
    if not match:
        return None

    script = shim.parent / match.group(1).replace("\\", "/")
    if not script.exists():
        return None

    node = shutil.which("node")
    if node is None:
        return None

    return [node, str(script)]


def resolve_executable(name: str) -> list[str] | None:
    """The argv prefix to launch `name`, or None when it isn't on PATH."""
    resolved = shutil.which(name)
    if resolved is None:
        return None

    path = Path(resolved)
    if os.name == "nt" and path.suffix.lower() in _BATCH_SUFFIXES:
        direct = _resolve_npm_shim(path)
        if direct is not None:
            return direct

        # Unparseable shim. cmd.exe can run it, but it will re-parse argv quoting, so
        # say so loudly rather than letting a mangled MCP config look like a model bug.
        log.warning(
            "[executable] %s is a batch shim we could not resolve to a direct target; "
            "falling back to cmd.exe, which may mangle quoted arguments",
            resolved,
        )
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [comspec, "/c", resolved]

    return [resolved]


def is_batch_shim(name: str) -> bool:
    """True when `name` resolves to a Windows batch shim."""
    resolved = shutil.which(name)
    return bool(
        resolved and os.name == "nt" and Path(resolved).suffix.lower() in _BATCH_SUFFIXES
    )
