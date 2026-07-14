from __future__ import annotations

import sqlite3

from corvid.domain.entities import (
    Account,
    ConnectionSecurity,
    Folder,
    FolderType,
    Message,
)
from corvid.infra.repositories import AccountRepository, FolderRepository, MessageRepository
from corvid.service.search import SearchService


def _seed(db: sqlite3.Connection) -> tuple[int, int]:
    account = AccountRepository(db).add(
        Account(
            id=None, display_name="Alice", email="alice@example.com", username="alice",
            imap_host="imap", imap_port=993, imap_security=ConnectionSecurity.TLS,
            smtp_host="smtp", smtp_port=587, smtp_security=ConnectionSecurity.STARTTLS,
        )
    )
    folder = FolderRepository(db).upsert(
        Folder(id=None, account_id=account.id, remote_name="INBOX",  # type: ignore[arg-type]
               display_name="INBOX", type=FolderType.INBOX)
    )
    repo = MessageRepository(db)
    repo.insert_header(Message(id=None, folder_id=folder.id, account_id=account.id,  # type: ignore[arg-type]
                              uid=1, message_id="<1@x>", subject="Quarterly budget review",
                              from_name="Bob", from_addr="bob@work.com"))
    repo.insert_header(Message(id=None, folder_id=folder.id, account_id=account.id,  # type: ignore[arg-type]
                              uid=2, message_id="<2@x>", subject="Lunch plans",
                              from_name="Carol", from_addr="carol@friends.net"))
    return account.id, folder.id  # type: ignore[return-value]


def test_search_by_subject(db: sqlite3.Connection) -> None:
    account_id, _ = _seed(db)
    results = SearchService(db).search("budget")
    assert len(results) == 1
    assert results[0].subject == "Quarterly budget review"


def test_search_by_sender(db: sqlite3.Connection) -> None:
    _seed(db)
    results = SearchService(db).search("carol")
    assert len(results) == 1
    assert results[0].from_name == "Carol"


def test_search_prefix(db: sqlite3.Connection) -> None:
    _seed(db)
    assert len(SearchService(db).search("lun")) == 1  # prefix match -> "Lunch"


def test_search_account_filter(db: sqlite3.Connection) -> None:
    account_id, _ = _seed(db)
    assert len(SearchService(db).search("plans", account_id=account_id)) == 1
    assert SearchService(db).search("plans", account_id=account_id + 999) == []


def test_search_folder_filter(db: sqlite3.Connection) -> None:
    account_id, folder_id = _seed(db)
    # A second folder with no matching mail.
    other = FolderRepository(db).upsert(
        Folder(id=None, account_id=account_id, remote_name="Archive",
               display_name="Archive", type=FolderType.ARCHIVE)
    )
    assert len(SearchService(db).search("budget", folder_id=folder_id)) == 1
    assert SearchService(db).search("budget", folder_id=other.id) == []  # scoped out


def test_empty_query(db: sqlite3.Connection) -> None:
    _seed(db)
    assert SearchService(db).search("   ") == []
