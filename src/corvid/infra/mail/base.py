"""The mail-store port.

The sync service depends on this protocol, not on imaplib. Tests inject a fake
implementation; production uses :class:`~corvid.infra.mail.imap_store.ImapMailStore`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import FolderInfo, FolderStatus, HeaderEnvelope


@runtime_checkable
class MailStore(Protocol):
    """A connected, read-capable view of a remote mailbox account."""

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def list_folders(self) -> list[FolderInfo]: ...

    def select(self, remote_name: str, *, readonly: bool = True) -> FolderStatus: ...

    def search_uids(self, min_uid: int | None = None) -> list[int]:
        """Return UIDs strictly greater than ``min_uid`` (all if ``None``)."""
        ...

    def fetch_headers(self, uids: list[int]) -> list[HeaderEnvelope]: ...

    def fetch_raw(self, uid: int) -> bytes:
        """Fetch the full raw RFC 822 message for a single UID."""
        ...

    def store_flags(self, uid: int, flags: tuple[str, ...], *, add: bool) -> None:
        """Add or remove IMAP flags (mailbox must be selected read-write)."""
        ...

    def move(self, uid: int, dest_remote_name: str) -> None:
        """Move a message to another mailbox."""
        ...

    def delete(self, uid: int) -> None:
        """Permanently delete (flag \\Deleted + expunge) a message."""
        ...

    def __enter__(self) -> MailStore: ...

    def __exit__(self, *exc: object) -> None: ...
