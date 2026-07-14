"""Parse a raw RFC 822 message into displayable text/HTML and attachments."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import message_from_bytes
from email.message import Message
from email.policy import default as default_policy
from email.utils import getaddresses, parsedate_to_datetime


@dataclass(slots=True)
class ParsedAttachment:
    filename: str
    content_type: str
    size: int
    payload: bytes
    is_inline: bool = False
    content_id: str = ""


@dataclass(slots=True)
class ParsedMessage:
    text: str = ""
    html: str = ""
    attachments: list[ParsedAttachment] = field(default_factory=list)

    @property
    def has_attachments(self) -> bool:
        return any(not a.is_inline for a in self.attachments)


def _content(part: Message) -> str:
    try:
        return str(part.get_content())  # type: ignore[attr-defined]  # EmailMessage under default policy
    except (LookupError, ValueError, UnicodeDecodeError):
        payload = part.get_payload(decode=True) or b""
        if isinstance(payload, bytes):
            return payload.decode("utf-8", "replace")
        return str(payload)


@dataclass(slots=True)
class RawHeaders:
    """Header-level fields extracted directly from raw RFC 822 bytes.

    Used when importing local stores (mbox/maildir/eml/dbx), where messages come
    as full raw bytes rather than an IMAP ENVELOPE. Mirrors the columns of
    :class:`~corvid.domain.entities.Message`.
    """

    message_id: str = ""
    subject: str = ""
    from_name: str = ""
    from_addr: str = ""
    to_addrs: str = ""
    cc_addrs: str = ""
    date_utc: datetime | None = None
    size: int = 0
    has_attachments: bool = False


def _format_addr_list(raw_value: str) -> str:
    """Normalize a To/Cc header into 'Name <addr>, ...' display text."""
    parts = []
    for name, addr in getaddresses([raw_value]):
        if not addr and not name:
            continue
        parts.append(f"{name} <{addr}>" if name else addr)
    return ", ".join(parts)


def header_fields_from_raw(raw: bytes) -> RawHeaders:
    """Extract Message-shaped header fields from raw bytes, tolerant of junk.

    Never raises on malformed input: unparseable dates become ``None`` and
    missing headers become empty strings.
    """
    msg = message_from_bytes(raw, policy=default_policy)

    from_pairs = getaddresses([str(msg.get("From", ""))])
    from_name, from_addr = (from_pairs[0] if from_pairs else ("", ""))

    date_utc: datetime | None = None
    date_hdr = msg.get("Date")
    if date_hdr:
        try:
            parsed = parsedate_to_datetime(str(date_hdr))
            if parsed is not None:
                date_utc = (
                    parsed.replace(tzinfo=UTC)
                    if parsed.tzinfo is None
                    else parsed.astimezone(UTC)
                )
        except (TypeError, ValueError):
            date_utc = None

    has_attachments = any(
        part.get_content_disposition() == "attachment" for part in msg.walk()
    )

    return RawHeaders(
        message_id=str(msg.get("Message-ID", "")).strip(),
        subject=str(msg.get("Subject", "")),
        from_name=from_name,
        from_addr=from_addr,
        to_addrs=_format_addr_list(str(msg.get("To", ""))),
        cc_addrs=_format_addr_list(str(msg.get("Cc", ""))),
        date_utc=date_utc,
        size=len(raw),
        has_attachments=has_attachments,
    )


def parse_message(raw: bytes) -> ParsedMessage:
    """Extract the best text body, HTML body, and attachments from raw bytes."""
    msg = message_from_bytes(raw, policy=default_policy)
    result = ParsedMessage()

    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disposition = part.get_content_disposition()  # 'attachment' | 'inline' | None
        ctype = part.get_content_type()
        filename = part.get_filename()

        if disposition == "attachment" or (filename and ctype not in ("text/plain", "text/html")):
            payload = part.get_payload(decode=True) or b""
            result.attachments.append(
                ParsedAttachment(
                    filename=filename or "attachment",
                    content_type=ctype,
                    size=len(payload) if isinstance(payload, bytes) else 0,
                    payload=payload if isinstance(payload, bytes) else b"",
                    is_inline=disposition == "inline",
                    content_id=(part.get("Content-ID") or "").strip("<>"),
                )
            )
        elif ctype == "text/plain" and not result.text and disposition != "attachment":
            result.text = _content(part)
        elif ctype == "text/html" and not result.html and disposition != "attachment":
            result.html = _content(part)

    return result
