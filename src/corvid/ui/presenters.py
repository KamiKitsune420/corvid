"""Presenters: turn repository data into view-models for the wx views.

Pure logic, no wx imports - unit-tested in ``tests/test_presenters.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..domain.entities import FolderType, Message
from ..infra.repositories import AccountRepository, FolderRepository, MessageRepository
from .viewmodels import AccountNode, FolderNode, MessageRow

# Display order for known folder roles; custom folders sort alphabetically after.
_FOLDER_ORDER: dict[FolderType, int] = {
    FolderType.INBOX: 0,
    FolderType.DRAFTS: 1,
    FolderType.OUTBOX: 2,
    FolderType.SENT: 3,
    FolderType.JUNK: 4,
    FolderType.TRASH: 5,
    FolderType.ARCHIVE: 6,
    FolderType.CUSTOM: 7,
}


def format_date(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M")


def _clock(local: datetime) -> str:
    """A spoken 12-hour clock time, e.g. ``6:48AM`` / ``12:53PM``."""
    hour = local.hour % 12 or 12
    meridian = "AM" if local.hour < 12 else "PM"
    return f"{hour}:{local.minute:02d}{meridian}"


def speak_date(value: datetime | None, now: datetime) -> str:
    """Phrase a message date the way a screen reader should read it.

    Today -> ``today at 6:48AM``; yesterday -> ``yesterday``; anything else ->
    ``July 20, 2026 at 12:53PM``. Times are shown in the local timezone.
    """
    if value is None:
        return ""
    local = value.astimezone()
    delta = (now.astimezone().date() - local.date()).days
    if delta == 0:
        return f"today at {_clock(local)}"
    if delta == 1:
        return "yesterday"
    return f"{local.strftime('%B')} {local.day}, {local.year} at {_clock(local)}"


def folder_label(display_name: str, unread: int) -> str:
    return f"{display_name} ({unread})" if unread else display_name


def sender_display(message: Message) -> str:
    return message.from_name or message.from_addr or "(unknown sender)"


def row_speech(message: Message, now: datetime) -> str:
    """Compose the single line a screen reader announces for a list row."""
    prefix = "Unread, " if not message.flags.seen else ""
    subject = message.subject or "(no subject)"
    head = f"{prefix}{sender_display(message)}, {subject}"
    when = speak_date(message.date_utc, now)
    return f"{head}. sent {when}." if when else f"{head}."


def message_to_row(message: Message, now: datetime | None = None) -> MessageRow | None:
    if message.id is None:
        return None
    if now is None:
        now = datetime.now(UTC)
    return MessageRow(
        message_id=message.id,
        subject=message.subject or "(no subject)",
        sender=sender_display(message),
        date_display=format_date(message.date_utc),
        unread=not message.flags.seen,
        has_attachments=message.has_attachments,
        flagged=message.flags.flagged,
        speech=row_speech(message, now),
    )


class FolderTreePresenter:
    def __init__(self, accounts: AccountRepository, folders: FolderRepository) -> None:
        self._accounts = accounts
        self._folders = folders

    def build(self) -> list[AccountNode]:
        nodes: list[AccountNode] = []
        for account in self._accounts.list():
            assert account.id is not None
            folders = self._folders.list_for_account(account.id)
            folders.sort(key=lambda f: (_FOLDER_ORDER.get(f.type, 99), f.display_name.lower()))
            folder_nodes = [
                FolderNode(
                    folder_id=f.id,  # type: ignore[arg-type]
                    account_id=account.id,
                    label=folder_label(f.display_name, f.unread_count),
                    type=f.type.value,
                    unread=f.unread_count,
                    total=f.total_count,
                )
                for f in folders
                if f.id is not None
            ]
            nodes.append(
                AccountNode(account_id=account.id, label=account.email, folders=folder_nodes)
            )
        return nodes


class MessageListPresenter:
    def __init__(self, messages: MessageRepository) -> None:
        self._messages = messages

    def rows(self, folder_id: int, *, limit: int = 500, offset: int = 0) -> list[MessageRow]:
        now = datetime.now(UTC)  # one reference point so "today"/"yesterday" agree
        result: list[MessageRow] = []
        for msg in self._messages.list_for_folder(folder_id, limit=limit, offset=offset):
            row = message_to_row(msg, now)
            if row is not None:
                result.append(row)
        return result


class MessagePreviewPresenter:
    def __init__(self, messages: MessageRepository) -> None:
        self._messages = messages

    def header_block(self, message_id: int) -> str:
        msg = self._messages.get(message_id)
        if msg is None:
            return ""
        lines = [
            f"From:    {msg.from_name + ' ' if msg.from_name else ''}<{msg.from_addr}>",
            f"To:      {msg.to_addrs}",
        ]
        if msg.cc_addrs:
            lines.append(f"Cc:      {msg.cc_addrs}")
        lines.append(f"Date:    {format_date(msg.date_utc)}")
        lines.append(f"Subject: {msg.subject or '(no subject)'}")
        return "\n".join(lines)
