"""
The user's profile — a single markdown file, per user, durable across sessions.

It's a plain file (not a DB row) on purpose: the Profile page shows it in a textarea
and lets the user hand-edit it. The agent reads/writes the SAME file through the
`get_profile` / `save_profile` MCP tools. One file, two editors (human + agent), no
sync problem.
"""

from __future__ import annotations

import re

from ..core.config import PROFILE_PATH
from ..models.profile import ProfileState
from ..persistence import files

# The user's display name is just the first markdown H1 ("# Farhaan"). We tell the
# agent to keep the name as the top heading, so we can pull it back out cheaply.
_NAME_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def derive_name(markdown: str | None) -> str | None:
    match = _NAME_RE.search(markdown or "")
    return match.group(1).strip() if match else None


def read() -> ProfileState:
    markdown = files.read_text(PROFILE_PATH)
    if markdown is None:
        return ProfileState(exists=False, markdown="", name=None)
    return ProfileState(exists=True, markdown=markdown, name=derive_name(markdown))


def write(markdown: str | None) -> str | None:
    """Persist the profile and return the derived display name."""
    files.write_text(PROFILE_PATH, markdown or "")
    return derive_name(markdown)
