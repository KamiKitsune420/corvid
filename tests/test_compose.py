from __future__ import annotations

from pathlib import Path

import pytest

from corvid.domain.compose import (
    DraftMessage,
    build_email_message,
    parse_address_list,
)
from corvid.errors import ValidationError


def test_parse_address_list() -> None:
    assert parse_address_list("a@x, b@y; c@z") == ["a@x", "b@y", "c@z"]
    assert parse_address_list("  ") == []


def test_build_plain_message() -> None:
    draft = DraftMessage(
        from_addr="me@x", from_name="Me", to=["you@y"], subject="Hi", body_text="Hello"
    )
    msg = build_email_message(draft)
    assert msg["From"] == "Me <me@x>"
    assert msg["To"] == "you@y"
    assert msg["Subject"] == "Hi"
    assert msg["Message-ID"]
    assert msg.get_content().strip() == "Hello"
    assert not msg.is_multipart()


def test_build_html_alternative() -> None:
    draft = DraftMessage(
        from_addr="me@x", to=["you@y"], body_text="plain", body_html="<p>rich</p>"
    )
    msg = build_email_message(draft)
    types = {part.get_content_type() for part in msg.walk()}
    assert "text/plain" in types
    assert "text/html" in types


def test_build_with_attachment(tmp_path: Path) -> None:
    attachment = tmp_path / "note.txt"
    attachment.write_text("data", encoding="utf-8")
    draft = DraftMessage(
        from_addr="me@x", to=["you@y"], subject="files", attachments=[str(attachment)]
    )
    msg = build_email_message(draft)
    names = [part.get_filename() for part in msg.iter_attachments()]
    assert names == ["note.txt"]


def test_bcc_in_recipients_and_header() -> None:
    draft = DraftMessage(from_addr="me@x", to=["a@y"], cc=["b@y"], bcc=["c@y"])
    assert draft.recipients() == ["a@y", "b@y", "c@y"]
    msg = build_email_message(draft)
    assert msg["Bcc"] == "c@y"  # send_message strips this before transmission


def test_validation() -> None:
    with pytest.raises(ValidationError):
        build_email_message(DraftMessage(from_addr="", to=["a@y"]))
    with pytest.raises(ValidationError):
        build_email_message(DraftMessage(from_addr="me@x", to=[]))


def test_missing_attachment_raises(tmp_path: Path) -> None:
    draft = DraftMessage(
        from_addr="me@x", to=["you@y"], attachments=[str(tmp_path / "nope.bin")]
    )
    with pytest.raises(ValidationError):
        build_email_message(draft)
