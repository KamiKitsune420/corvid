from __future__ import annotations

import sqlite3

from fakes import FakeMailStore

from corvid.domain.entities import (
    Account,
    ConnectionSecurity,
    Folder,
    FolderType,
    Message,
    MessageFlags,
)
from corvid.infra.mail.types import FolderInfo, FolderStatus
from corvid.infra.repositories import AccountRepository, FolderRepository, MessageRepository
from corvid.service.actions import MessageActionService


def _store() -> FakeMailStore:
    status = FolderStatus(uidvalidity=1, uidnext=99, exists=0)
    return FakeMailStore(
        [FolderInfo("INBOX", "INBOX"), FolderInfo("Trash", "Trash")],
        {"INBOX": (status, []), "Trash": (status, [])},
    )


def _seed(db: sqlite3.Connection, *, seen: bool = False) -> tuple[Message, Folder, Folder]:
    account = AccountRepository(db).add(
        Account(id=None, display_name="A", email="a@x", username="a",
                imap_host="i", imap_port=993, imap_security=ConnectionSecurity.TLS,
                smtp_host="s", smtp_port=587, smtp_security=ConnectionSecurity.STARTTLS)
    )
    folders = FolderRepository(db)
    inbox = folders.upsert(Folder(id=None, account_id=account.id, remote_name="INBOX",  # type: ignore[arg-type]
                                  display_name="INBOX", type=FolderType.INBOX))
    trash = folders.upsert(Folder(id=None, account_id=account.id, remote_name="Trash",  # type: ignore[arg-type]
                                  display_name="Trash", type=FolderType.TRASH))
    message = MessageRepository(db).insert_header(
        Message(id=None, folder_id=inbox.id, account_id=account.id,  # type: ignore[arg-type]
                uid=42, message_id="<42@x>", subject="hi", flags=MessageFlags(seen=seen))
    )
    return message, inbox, trash


def test_mark_seen_writes_through(db: sqlite3.Connection) -> None:
    message, inbox, _ = _seed(db, seen=False)
    store = _store()
    repo = MessageRepository(db)
    MessageActionService(repo, FolderRepository(db)).mark_seen(message, store, seen=True)

    assert store.flag_ops == [(42, ("\\Seen",), True)]
    assert repo.get(message.id).flags.seen is True  # type: ignore[union-attr]
    assert FolderRepository(db).get(inbox.id).unread_count == 0  # type: ignore[union-attr]


def test_toggle_flag_writes_through(db: sqlite3.Connection) -> None:
    message, _, _ = _seed(db)
    store = _store()
    repo = MessageRepository(db)
    MessageActionService(repo, FolderRepository(db)).set_flagged(message, store, flagged=True)
    assert store.flag_ops == [(42, ("\\Flagged",), True)]
    assert repo.get(message.id).flags.flagged is True  # type: ignore[union-attr]


def test_delete_moves_to_trash(db: sqlite3.Connection) -> None:
    message, inbox, trash = _seed(db)
    store = _store()
    repo = MessageRepository(db)
    MessageActionService(repo, FolderRepository(db)).delete(message, store, trash)

    assert store.moves == [(42, "Trash")]
    moved = repo.get(message.id)  # type: ignore[arg-type]
    assert moved is not None and moved.folder_id == trash.id
    assert FolderRepository(db).get(inbox.id).total_count == 0  # type: ignore[union-attr]


def test_delete_without_trash_expunges(db: sqlite3.Connection) -> None:
    message, inbox, _ = _seed(db)
    store = _store()
    repo = MessageRepository(db)
    MessageActionService(repo, FolderRepository(db)).delete(message, store, trash=None)

    assert store.deletes == [42]
    assert repo.get(message.id) is None  # type: ignore[arg-type]  # row removed locally
