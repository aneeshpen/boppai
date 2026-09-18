"""Image attachment decoding and the path-traversal guard on attachment serving."""

from __future__ import annotations

import base64

import pytest

from app.services import attachments

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"x" * 32


def data_url(raw: bytes = PNG_BYTES, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def test_saves_images_and_returns_metadata_plus_paths(session):
    saved, paths = attachments.save_image_attachments(
        session, [{"name": "shelf.png", "data": data_url()}]
    )

    assert len(saved) == 1 and len(paths) == 1
    item = saved[0]
    assert item["kind"] == "image"
    assert item["mimeType"] == "image/png"
    assert item["name"] == "shelf.png"
    assert item["file"].endswith(".png")
    assert item["url"] == f"/api/sessions/{session.id}/attachments/{item['file']}"
    assert (session.folder / "attachments" / item["file"]).read_bytes() == PNG_BYTES


def test_no_images_is_a_no_op(session):
    assert attachments.save_image_attachments(session, []) == ([], [])
    assert attachments.save_image_attachments(session, None) == ([], [])


def test_rejects_more_than_four_images(session):
    images = [{"data": data_url()} for _ in range(5)]
    with pytest.raises(ValueError, match="up to 4 images"):
        attachments.save_image_attachments(session, images)


def test_rejects_non_image_data_urls(session):
    with pytest.raises(ValueError, match="PNG, JPEG, WebP, or GIF"):
        attachments.save_image_attachments(session, [{"data": "data:text/plain;base64,aGk="}])


def test_rejects_oversized_images(session):
    huge = base64.b64encode(b"x" * (attachments.MAX_IMAGE_BYTES + 1)).decode()
    with pytest.raises(ValueError, match="8 MB or smaller"):
        attachments.save_image_attachments(
            session, [{"data": f"data:image/png;base64,{huge}"}]
        )


def test_missing_data_is_reported(session):
    with pytest.raises(ValueError, match="Image data is missing"):
        attachments.save_image_attachments(session, [{"name": "x.png"}])


def test_attachment_lookup_refuses_paths_outside_the_session(session):
    saved, _ = attachments.save_image_attachments(session, [{"data": data_url()}])
    good = attachments.attachment_file(session, saved[0]["file"])
    assert good is not None and good.exists()

    # Node did `path.basename(...)` then verified containment; both must hold here.
    assert attachments.attachment_file(session, "../../../etc/passwd") is None
    assert attachments.attachment_file(session, "nope.png") is None
