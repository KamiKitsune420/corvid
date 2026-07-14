"""Store a full raw message into a local folder, header-first with cached body.

Shared by the importer and the POP3 receiver: both obtain complete RFC 822 bytes
(rather than an IMAP header envelope) and need them stored so the message reads
and searches like synced mail. The message is inserted with ``uid = NULL`` (so
IMAP sync ignores it) and ``body_fetched = True`` with the raw bytes cached under
``messages_dir``.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.entities import Message, MessageFlags
from ..infra.mail.parsing import header_fields_from_raw
from ..infra.repositories import MessageRepository


def deliver_raw(
    messages: MessageRepository,
    messages_dir: Path,
    *,
    folder_id: int,
    account_id: int,
    raw: bytes,
    seen: bool = True,
    flagged: bool = False,
    answered: bool = False,
) -> Message | None:
    """Persist ``raw`` into ``folder_id`` and cache its body. ``None`` on failure."""
    headers = header_fields_from_raw(raw)
    stored = messages.insert_header(
        Message(
            id=None,
            folder_id=folder_id,
            account_id=account_id,
            uid=None,
            message_id=headers.message_id,
            subject=headers.subject,
            in_reply_to=headers.in_reply_to,
            references=headers.references,
            from_name=headers.from_name,
            from_addr=headers.from_addr,
            to_addrs=headers.to_addrs,
            cc_addrs=headers.cc_addrs,
            date_utc=headers.date_utc,
            size=headers.size,
            has_attachments=headers.has_attachments,
            flags=MessageFlags(seen=seen, flagged=flagged, answered=answered),
        )
    )
    if stored.id is None:
        return None
    path = messages_dir / f"{stored.id}.eml"
    path.write_bytes(raw)
    messages.mark_body_fetched(stored.id, str(path))
    return stored
