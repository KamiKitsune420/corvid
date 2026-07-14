from __future__ import annotations

import sqlite3

from corvid.domain.entities import (
    Account,
    AccountKind,
    ConnectionSecurity,
    Folder,
    FolderType,
    Message,
    MessageFlags,
    ReceiveProtocol,
)
from corvid.infra.repositories import (
    AccountRepository,
    FolderRepository,
    IdentityRepository,
    MessageRepository,
)


def _account() -> Account:
    return Account(
        id=None,
        display_name="Alice",
        email="alice@example.com",
        username="alice",
        imap_host="imap.example.com",
        imap_port=993,
        imap_security=ConnectionSecurity.TLS,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_security=ConnectionSecurity.STARTTLS,
    )


def test_account_roundtrips_news_and_pop3_fields(db: sqlite3.Connection) -> None:
    repo = AccountRepository(db)
    news = _account()
    news.kind = AccountKind.NEWS
    news.nntp_host = "news.example.com"
    news.nntp_port = 563
    news.nntp_security = ConnectionSecurity.TLS
    news.receive_protocol = ReceiveProtocol.POP3
    news.pop3_host = "pop.example.com"
    news.pop3_port = 110
    news.pop3_security = ConnectionSecurity.STARTTLS
    news.pop3_leave_on_server = False

    saved = repo.add(news)
    assert saved.id is not None
    got = repo.get(saved.id)
    assert got is not None
    assert got.kind is AccountKind.NEWS
    assert got.nntp_host == "news.example.com" and got.nntp_port == 563
    assert got.receive_protocol is ReceiveProtocol.POP3
    assert got.pop3_host == "pop.example.com" and got.pop3_port == 110
    assert got.pop3_security is ConnectionSecurity.STARTTLS
    assert got.pop3_leave_on_server is False

    # update() must persist the new columns too
    got.pop3_leave_on_server = True
    got.nntp_port = 119
    repo.update(got)
    reloaded = repo.get(saved.id)
    assert reloaded is not None
    assert reloaded.pop3_leave_on_server is True and reloaded.nntp_port == 119


def test_account_crud(db: sqlite3.Connection) -> None:
    repo = AccountRepository(db)
    saved = repo.add(_account())
    assert saved.id is not None
    assert saved.created_at is not None

    fetched = repo.get(saved.id)
    assert fetched is not None
    assert fetched.email == "alice@example.com"
    assert fetched.imap_security is ConnectionSecurity.TLS

    fetched.display_name = "Alice B."
    repo.update(fetched)
    assert repo.get(saved.id).display_name == "Alice B."  # type: ignore[union-attr]

    assert len(repo.list()) == 1
    repo.delete(saved.id)
    assert repo.get(saved.id) is None


def test_identity_default(db: sqlite3.Connection) -> None:
    account = AccountRepository(db).add(_account())
    repo = IdentityRepository(db)
    from corvid.domain.entities import Identity

    repo.add(Identity(id=None, account_id=account.id, display_name="Alice", email=account.email,
                       is_default=True))
    default = repo.default_for_account(account.id)  # type: ignore[arg-type]
    assert default is not None and default.is_default is True


def test_folder_upsert_is_idempotent(db: sqlite3.Connection) -> None:
    account = AccountRepository(db).add(_account())
    repo = FolderRepository(db)
    folder = Folder(id=None, account_id=account.id, remote_name="INBOX",  # type: ignore[arg-type]
                    display_name="INBOX", type=FolderType.INBOX)
    first = repo.upsert(folder)
    again = repo.upsert(Folder(id=None, account_id=account.id,  # type: ignore[arg-type]
                               remote_name="INBOX", display_name="Inbox", type=FolderType.INBOX))
    assert first.id == again.id
    assert len(repo.list_for_account(account.id)) == 1  # type: ignore[arg-type]


def test_message_insert_and_counts(db: sqlite3.Connection) -> None:
    account = AccountRepository(db).add(_account())
    folder = FolderRepository(db).upsert(
        Folder(id=None, account_id=account.id, remote_name="INBOX",  # type: ignore[arg-type]
               display_name="INBOX", type=FolderType.INBOX)
    )
    repo = MessageRepository(db)
    for uid, seen in [(101, True), (102, False), (103, False)]:
        repo.insert_header(
            Message(id=None, folder_id=folder.id, account_id=account.id,  # type: ignore[arg-type]
                    uid=uid, message_id=f"<{uid}@x>", subject=f"msg {uid}",
                    flags=MessageFlags(seen=seen))
        )
    # Duplicate UID is ignored (UNIQUE folder_id, uid).
    repo.insert_header(
        Message(id=None, folder_id=folder.id, account_id=account.id,  # type: ignore[arg-type]
                uid=101, message_id="<dup@x>", subject="dup")
    )

    assert repo.max_uid(folder.id) == 103  # type: ignore[arg-type]
    assert repo.existing_uids(folder.id) == {101, 102, 103}  # type: ignore[arg-type]
    total, unread = repo.counts_for_folder(folder.id)  # type: ignore[arg-type]
    assert (total, unread) == (3, 2)
