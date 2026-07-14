from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from corvid.domain.entities import (
    Account,
    ConnectionSecurity,
    Folder,
    FolderType,
    Message,
    MessageFlags,
)
from corvid.infra.repositories import AccountRepository, FolderRepository, MessageRepository
from corvid.ui.presenters import (
    FolderTreePresenter,
    MessageListPresenter,
    MessagePreviewPresenter,
    format_date,
    row_speech,
    sender_display,
    speak_date,
)


def _seed(db: sqlite3.Connection) -> tuple[int, int, int]:
    account = AccountRepository(db).add(
        Account(
            id=None, display_name="Alice", email="alice@example.com", username="alice",
            imap_host="imap", imap_port=993, imap_security=ConnectionSecurity.TLS,
            smtp_host="smtp", smtp_port=587, smtp_security=ConnectionSecurity.STARTTLS,
        )
    )
    folders = FolderRepository(db)
    # Insert out of display order to verify sorting.
    custom = folders.upsert(Folder(id=None, account_id=account.id, remote_name="Work",  # type: ignore[arg-type]
                                   display_name="Work", type=FolderType.CUSTOM))
    inbox = folders.upsert(Folder(id=None, account_id=account.id, remote_name="INBOX",  # type: ignore[arg-type]
                                  display_name="INBOX", type=FolderType.INBOX))
    folders.update_counts(inbox.id, 2, 1)  # type: ignore[arg-type]
    return account.id, inbox.id, custom.id  # type: ignore[return-value]


def test_folder_tree_orders_and_labels(db: sqlite3.Connection) -> None:
    account_id, inbox_id, _ = _seed(db)
    presenter = FolderTreePresenter(AccountRepository(db), FolderRepository(db))
    nodes = presenter.build()
    assert len(nodes) == 1
    labels = [f.label for f in nodes[0].folders]
    assert labels[0] == "INBOX (1)"  # inbox first, with unread count
    assert "Work" in labels[1]


def test_message_list_rows(db: sqlite3.Connection) -> None:
    account_id, inbox_id, _ = _seed(db)
    repo = MessageRepository(db)
    repo.insert_header(
        Message(id=None, folder_id=inbox_id, account_id=account_id, uid=10,
                message_id="<a@x>", subject="Hi", from_name="Bob", from_addr="bob@x",
                date_utc=datetime(2030, 1, 2, 9, 30, tzinfo=UTC),
                flags=MessageFlags(seen=False))
    )
    rows = MessageListPresenter(repo).rows(inbox_id)
    assert len(rows) == 1
    assert rows[0].subject == "Hi"
    assert rows[0].sender == "Bob"
    assert rows[0].date_display == "2030-01-02 09:30"
    assert rows[0].unread is True


def test_preview_header_block(db: sqlite3.Connection) -> None:
    account_id, inbox_id, _ = _seed(db)
    repo = MessageRepository(db)
    msg = repo.insert_header(
        Message(id=None, folder_id=inbox_id, account_id=account_id, uid=11,
                message_id="<b@x>", subject="Report", from_addr="carol@x",
                to_addrs="alice@example.com")
    )
    block = MessagePreviewPresenter(repo).header_block(msg.id)  # type: ignore[arg-type]
    assert "Subject: Report" in block
    assert "carol@x" in block


def test_helpers() -> None:
    assert format_date(None) == ""
    msg = Message(id=None, folder_id=1, account_id=1, uid=1, message_id="", from_addr="x@y")
    assert sender_display(msg) == "x@y"


# Build datetimes in the system-local zone so astimezone() doesn't shift the date.
_LOCAL = datetime.now().astimezone().tzinfo


def test_speak_date_today() -> None:
    now = datetime(2026, 7, 20, 18, 0, tzinfo=_LOCAL)
    when = datetime(2026, 7, 20, 6, 48, tzinfo=_LOCAL)
    assert speak_date(when, now) == "today at 6:48AM"


def test_speak_date_yesterday() -> None:
    now = datetime(2026, 7, 20, 9, 0, tzinfo=_LOCAL)
    when = datetime(2026, 7, 19, 22, 15, tzinfo=_LOCAL)
    assert speak_date(when, now) == "yesterday"


def test_speak_date_older() -> None:
    now = datetime(2026, 7, 25, 9, 0, tzinfo=_LOCAL)
    when = datetime(2026, 7, 20, 12, 53, tzinfo=_LOCAL)
    assert speak_date(when, now) == "July 20, 2026 at 12:53PM"


def test_speak_date_none() -> None:
    assert speak_date(None, datetime(2026, 7, 20, tzinfo=_LOCAL)) == ""


def test_row_speech_unread_today() -> None:
    now = datetime(2026, 7, 20, 18, 0, tzinfo=_LOCAL)
    msg = Message(
        id=1, folder_id=1, account_id=1, uid=1, message_id="", subject="Lunch?",
        from_name="Bob", from_addr="bob@x",
        date_utc=datetime(2026, 7, 20, 6, 48, tzinfo=_LOCAL),
        flags=MessageFlags(seen=False),
    )
    assert row_speech(msg, now) == "Unread, Bob, Lunch?. sent today at 6:48AM."


def test_row_speech_read_has_no_unread_prefix() -> None:
    now = datetime(2026, 7, 20, 18, 0, tzinfo=_LOCAL)
    msg = Message(
        id=1, folder_id=1, account_id=1, uid=1, message_id="", subject="Notes",
        from_name="Carol", from_addr="carol@x",
        date_utc=datetime(2026, 7, 19, 8, 0, tzinfo=_LOCAL),
        flags=MessageFlags(seen=True),
    )
    assert row_speech(msg, now) == "Carol, Notes. sent yesterday."
