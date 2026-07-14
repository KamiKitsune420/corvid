from __future__ import annotations

import sqlite3

from corvid.domain.compose import DraftMessage
from corvid.domain.entities import Account, ConnectionSecurity
from corvid.infra.repositories import AccountRepository, DraftRepository


def _account(db: sqlite3.Connection) -> int:
    account = AccountRepository(db).add(
        Account(
            id=None, display_name="Alice", email="alice@example.com", username="alice",
            imap_host="imap", imap_port=993, imap_security=ConnectionSecurity.TLS,
            smtp_host="smtp", smtp_port=587, smtp_security=ConnectionSecurity.STARTTLS,
        )
    )
    assert account.id is not None
    return account.id


def test_draft_save_and_get(db: sqlite3.Connection) -> None:
    account_id = _account(db)
    repo = DraftRepository(db)
    draft = DraftMessage(
        from_addr="alice@example.com", account_id=account_id,
        to=["bob@x", "carol@y"], cc=["dave@z"], subject="Plan",
        body_text="hello", attachments=["/tmp/a.txt"],
    )
    saved = repo.save(draft)
    assert saved.id is not None

    loaded = repo.get(saved.id)
    assert loaded is not None
    assert loaded.to == ["bob@x", "carol@y"]
    assert loaded.cc == ["dave@z"]
    assert loaded.subject == "Plan"
    assert loaded.body_text == "hello"
    assert loaded.attachments == ["/tmp/a.txt"]


def test_draft_update_and_list_and_delete(db: sqlite3.Connection) -> None:
    account_id = _account(db)
    repo = DraftRepository(db)
    draft = repo.save(DraftMessage(from_addr="a@x", account_id=account_id, subject="one"))
    draft.subject = "one-edited"
    repo.save(draft)
    assert repo.get(draft.id).subject == "one-edited"  # type: ignore[union-attr,arg-type]

    repo.save(DraftMessage(from_addr="a@x", account_id=account_id, subject="two"))
    assert len(repo.list_for_account(account_id)) == 2

    repo.delete(draft.id)  # type: ignore[arg-type]
    assert repo.get(draft.id) is None  # type: ignore[arg-type]
    assert len(repo.list_for_account(account_id)) == 1
