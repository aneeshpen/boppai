"""
Image attachments -- shared, agent-agnostic.

Turning a browser upload into files on disk is the same job for every brain: decode the
data-URL, drop it in the session's `attachments/` folder, and hand back (a) the metadata
the UI renders and (b) the absolute paths the CLI needs. How each brain then feeds those
paths to its runtime is the ONLY per-agent part, and that lives in each adapter's
`build_chat_args` / `build_prompt`.
"""

from __future__ import annotations

import base64
import binascii
import re
import uuid
from pathlib import Path
from typing import Any

from ..models.session import Session

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

_DATA_URL_RE = re.compile(
    r"^data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\s]+)$"
)


def _decode_image_data(data: Any) -> tuple[str, bytes, str]:
    if not isinstance(data, str) or not data.strip():
        raise ValueError("Image data is missing")

    match = _DATA_URL_RE.match(data)
    if not match:
        raise ValueError("Images must be PNG, JPEG, WebP, or GIF data URLs")

    mime_type = match.group(1)
    try:
        buffer = base64.b64decode(re.sub(r"\s", "", match.group(2)), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Image data is missing") from exc

    if not buffer:
        raise ValueError("Image data is empty")
    if len(buffer) > MAX_IMAGE_BYTES:
        raise ValueError("Each image must be 8 MB or smaller")

    return mime_type, buffer, IMAGE_TYPES[mime_type]


def save_image_attachments(
    session: Session, images: Any = None
) -> tuple[list[dict[str, str]], list[str]]:
    """Returns (attachments, image_paths).

    `attachments` is the metadata persisted with the message and rendered by the UI;
    `image_paths` are absolute paths handed to the agent adapter.
    """
    if not isinstance(images, list) or not images:
        return [], []
    if len(images) > MAX_IMAGES:
        raise ValueError(f"Attach up to {MAX_IMAGES} images at a time")

    directory = session.folder / "attachments"
    directory.mkdir(parents=True, exist_ok=True)

    decoded = []
    for image in images:
        image = image if isinstance(image, dict) else {}
        mime_type, buffer, ext = _decode_image_data(image.get("data"))
        attachment_id = str(uuid.uuid4())
        filename = f"{attachment_id}.{ext}"
        raw_name = image.get("name")
        name = (
            raw_name.strip()[:120]
            if isinstance(raw_name, str) and raw_name.strip()
            else filename
        )
        decoded.append((attachment_id, mime_type, buffer, filename, name))

    for _, _, buffer, filename, _ in decoded:
        # "xb" is Node's `{ flag: 'wx' }` -- never clobber an existing file.
        with open(directory / filename, "xb") as handle:
            handle.write(buffer)

    attachments = [
        {
            "id": attachment_id,
            "kind": "image",
            "mimeType": mime_type,
            "name": name,
            "file": filename,
            "url": f"/api/sessions/{session.id}/attachments/{filename}",
        }
        for attachment_id, mime_type, _, filename, name in decoded
    ]

    image_paths = [str(directory / attachment["file"]) for attachment in attachments]
    return attachments, image_paths


def attachment_file(session: Session, filename: str) -> Path | None:
    """Resolve a requested attachment, refusing anything outside the session folder."""
    directory = (session.folder / "attachments").resolve()
    candidate = (directory / Path(filename).name).resolve()
    if not candidate.is_relative_to(directory) or not candidate.exists():
        return None
    return candidate
