"""Core domain entities.

These dataclasses are storage-agnostic: repositories in the ``infra`` layer map
them to and from SQLite rows. ``id is None`` means "not yet persisted". The shapes
here intentionally mirror the v1 database schema (see ``infra/db/migrations.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ConnectionSecurity(StrEnum):
    NONE = "none"
    STARTTLS = "starttls"
    TLS = "tls"


class AuthMethod(StrEnum):
    PASSWORD = "password"
    OAUTH2 = "oauth2"


class AccountKind(StrEnum):
    MAIL = "mail"
    NEWS = "news"


class ReceiveProtocol(StrEnum):
    IMAP = "imap"
    POP3 = "pop3"


class FolderType(StrEnum):
    INBOX = "inbox"
    SENT = "sent"
    DRAFTS = "drafts"
    TRASH = "trash"
    JUNK = "junk"
    ARCHIVE = "archive"
    OUTBOX = "outbox"
    NEWSGROUP = "newsgroup"
    CUSTOM = "custom"


@dataclass(slots=True)
class EmailAddress:
    address: str
    name: str = ""

    def __str__(self) -> str:
        return f"{self.name} <{self.address}>" if self.name else self.address


@dataclass(slots=True)
class Account:
    id: int | None
    display_name: str
    email: str
    username: str
    imap_host: str
    imap_port: int
    imap_security: ConnectionSecurity
    smtp_host: str
    smtp_port: int
    smtp_security: ConnectionSecurity
    auth_method: AuthMethod = AuthMethod.PASSWORD
    kind: AccountKind = AccountKind.MAIL
    receive_protocol: ReceiveProtocol = ReceiveProtocol.IMAP
    nntp_host: str = ""
    nntp_port: int = 119
    nntp_security: ConnectionSecurity = ConnectionSecurity.TLS
    pop3_host: str = ""
    pop3_port: int = 995
    pop3_security: ConnectionSecurity = ConnectionSecurity.TLS
    pop3_leave_on_server: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class Identity:
    id: int | None
    account_id: int
    display_name: str
    email: str
    reply_to: str = ""
    signature: str = ""
    is_default: bool = False


@dataclass(slots=True)
class Folder:
    id: int | None
    account_id: int
    remote_name: str
    display_name: str
    type: FolderType = FolderType.CUSTOM
    parent_id: int | None = None
    uidvalidity: int | None = None
    uidnext: int | None = None
    unread_count: int = 0
    total_count: int = 0


@dataclass(slots=True)
class MessageFlags:
    seen: bool = False
    answered: bool = False
    flagged: bool = False
    draft: bool = False
    deleted: bool = False


@dataclass(slots=True)
class Message:
    id: int | None
    folder_id: int
    account_id: int
    uid: int | None
    message_id: str
    subject: str = ""
    from_name: str = ""
    from_addr: str = ""
    to_addrs: str = ""
    cc_addrs: str = ""
    date_utc: datetime | None = None
    size: int = 0
    snippet: str = ""
    has_attachments: bool = False
    flags: MessageFlags = field(default_factory=MessageFlags)
    raw_path: str = ""
    body_fetched: bool = False


@dataclass(slots=True)
class Attachment:
    id: int | None
    message_id: int
    filename: str
    content_type: str = "application/octet-stream"
    size: int = 0
    content_id: str = ""
    is_inline: bool = False
    storage_path: str = ""


@dataclass(slots=True)
class Contact:
    id: int | None
    display_name: str
    first_name: str = ""
    last_name: str = ""
    organization: str = ""
    notes: str = ""
    emails: list[EmailAddress] = field(default_factory=list)


@dataclass(slots=True)
class Rule:
    id: int | None
    name: str
    enabled: bool = True
    priority: int = 0
    match_json: str = "{}"
    actions_json: str = "[]"


@dataclass(slots=True)
class Event:
    """A calendar event. Times are timezone-aware UTC; all-day events span a day."""

    id: int | None
    title: str
    start_utc: datetime
    end_utc: datetime
    all_day: bool = False
    location: str = ""
    notes: str = ""
