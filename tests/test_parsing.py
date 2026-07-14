from __future__ import annotations

from email.message import EmailMessage

from corvid.infra.mail.parsing import parse_message


def _build(*, text: str = "", html: str = "", attachment: tuple[str, bytes] | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"] = "a@x"
    msg["To"] = "b@y"
    msg["Subject"] = "hi"
    if text:
        msg.set_content(text)
    if html:
        if text:
            msg.add_alternative(html, subtype="html")
        else:
            msg.set_content(html, subtype="html")
    if attachment is not None:
        name, data = attachment
        msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return msg.as_bytes()


def test_parse_plain() -> None:
    parsed = parse_message(_build(text="Hello there"))
    assert parsed.text.strip() == "Hello there"
    assert parsed.html == ""
    assert parsed.attachments == []


def test_parse_html_alternative() -> None:
    parsed = parse_message(_build(text="plain", html="<p>rich</p>"))
    assert parsed.text.strip() == "plain"
    assert "rich" in parsed.html


def test_parse_attachment() -> None:
    parsed = parse_message(_build(text="see attached", attachment=("report.bin", b"\x00\x01data")))
    assert parsed.has_attachments
    att = parsed.attachments[0]
    assert att.filename == "report.bin"
    assert att.payload == b"\x00\x01data"
    assert att.size == 6
    assert not att.is_inline


def test_parse_html_only() -> None:
    parsed = parse_message(_build(html="<b>bold</b>"))
    assert "bold" in parsed.html
    assert parsed.text == ""
