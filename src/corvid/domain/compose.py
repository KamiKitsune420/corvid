"""Outbound message composition model and RFC 822 builder."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from ..errors import ValidationError


@dataclass(slots=True)
class DraftMessage:
    """An in-progress or ready-to-send message."""

    from_addr: str
    from_name: str = ""
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    attachments: list[str] = field(default_factory=list)  # filesystem paths
    in_reply_to: str = ""
    references: str = ""
    # Persistence metadata (set when stored as a draft):
    id: int | None = None
    account_id: int | None = None
    identity_id: int | None = None

    def recipients(self) -> list[str]:
        return [*self.to, *self.cc, *self.bcc]


def _split(value: str) -> list[str]:
    """Parse a comma/semicolon-separated address string into a clean list."""
    parts = value.replace(";", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def parse_address_list(value: str) -> list[str]:
    return _split(value)


def build_email_message(draft: DraftMessage) -> EmailMessage:
    """Build a fully-formed :class:`EmailMessage` from a draft.

    Bcc is set as a header; ``smtplib.SMTP.send_message`` uses it for the envelope
    and strips it before transmission.
    """
    if not draft.from_addr:
        raise ValidationError("A sender address is required.")
    if not draft.recipients():
        raise ValidationError("At least one recipient is required.")

    msg = EmailMessage()
    msg["From"] = formataddr((draft.from_name, draft.from_addr))
    msg["To"] = ", ".join(draft.to)
    if draft.cc:
        msg["Cc"] = ", ".join(draft.cc)
    if draft.bcc:
        msg["Bcc"] = ", ".join(draft.bcc)
    msg["Subject"] = draft.subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    if draft.in_reply_to:
        msg["In-Reply-To"] = draft.in_reply_to
        msg["References"] = draft.references or draft.in_reply_to

    msg.set_content(draft.body_text or "")
    if draft.body_html:
        msg.add_alternative(draft.body_html, subtype="html")

    for raw_path in draft.attachments:
        path = Path(raw_path)
        if not path.is_file():
            raise ValidationError(f"Attachment not found: {raw_path}")
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )
    return msg
