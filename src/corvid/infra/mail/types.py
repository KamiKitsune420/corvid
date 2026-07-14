"""Value objects exchanged across the mail-store port."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class FolderInfo:
    """A mailbox as reported by the server's LIST."""

    remote_name: str
    display_name: str
    delimiter: str = "/"
    flags: tuple[str, ...] = ()
    special_use: str | None = None  # e.g. "\\Sent", "\\Trash" (RFC 6154)
    is_newsgroup: bool = False


@dataclass(slots=True)
class FolderStatus:
    """Server-side state of a selected mailbox."""

    uidvalidity: int
    uidnext: int
    exists: int


@dataclass(slots=True)
class HeaderEnvelope:
    """Header-level metadata for a single message."""

    uid: int
    message_id: str = ""
    subject: str = ""
    from_name: str = ""
    from_addr: str = ""
    to_addrs: str = ""
    cc_addrs: str = ""
    date_utc: datetime | None = None
    size: int = 0
    has_attachments: bool = False
    flags: frozenset[str] = field(default_factory=frozenset)

    @property
    def seen(self) -> bool:
        return "\\Seen" in self.flags

    @property
    def answered(self) -> bool:
        return "\\Answered" in self.flags

    @property
    def flagged(self) -> bool:
        return "\\Flagged" in self.flags

    @property
    def draft(self) -> bool:
        return "\\Draft" in self.flags

    @property
    def deleted(self) -> bool:
        return "\\Deleted" in self.flags
