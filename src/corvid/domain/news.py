"""Building outbound NNTP articles (pure, storage-agnostic)."""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate, make_msgid


def build_article(
    *,
    from_addr: str,
    from_name: str,
    newsgroups: str,
    subject: str,
    body: str,
    references: str = "",
    date: str | None = None,
    message_id: str | None = None,
) -> bytes:
    """Assemble a postable RFC 5536 news article as raw bytes.

    ``newsgroups`` is a comma-separated list of groups. ``references`` carries the
    parent article's Message-ID(s) for a follow-up so threading works.
    """
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    msg["Newsgroups"] = newsgroups
    msg["Subject"] = subject
    msg["Date"] = date or formatdate(localtime=True)
    msg["Message-ID"] = message_id or make_msgid()
    if references.strip():
        msg["References"] = references.strip()
    msg.set_content(body)
    return msg.as_bytes()
