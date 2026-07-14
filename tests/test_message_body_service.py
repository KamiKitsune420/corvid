from __future__ import annotations

import sqlite3
from email.message import EmailMessage
from pathlib import Path

from corvid.domain.entities import (
    Account,
    ConnectionSecurity,
    Folder,
    FolderType,
    Message,
)
from corvid.infra.repositories import AccountRepository, FolderRepository, MessageRepository
from corvid.service.messages import MessageBodyService


def _raw(body: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = "a@x"
    msg["Subject"] = "hi"
    msg.set_content(body)
    return msg.as_bytes()


class _RawStore:
    """Minimal stand-in exposing fetch_raw."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def fetch_raw(self, uid: int) -> bytes:
        return self._raw


def _seed(db: sqlite3.Connection) -> Message:
    account = AccountRepository(db).add(
        Account(id=None, display_name="A", email="a@x", username="a",
                imap_host="i", imap_port=993, imap_security=ConnectionSecurity.TLS,
                smtp_host="s", smtp_port=587, smtp_security=ConnectionSecurity.STARTTLS)
    )
    folder = FolderRepository(db).upsert(
        Folder(id=None, account_id=account.id, remote_name="INBOX",  # type: ignore[arg-type]
               display_name="INBOX", type=FolderType.INBOX)
    )
    return MessageRepository(db).insert_header(
        Message(id=None, folder_id=folder.id, account_id=account.id,  # type: ignore[arg-type]
                uid=7, message_id="<7@x>", subject="hi")
    )


def test_fetch_caches_then_reads_from_disk(db: sqlite3.Connection, tmp_path: Path) -> None:
    message = _seed(db)
    repo = MessageRepository(db)
    service = MessageBodyService(repo, tmp_path)

    assert service.get_cached(message) is None  # not yet downloaded

    parsed = service.fetch_and_cache(message, _RawStore(_raw("the body")))  # type: ignore[arg-type]
    assert parsed.text.strip() == "the body"

    # State persisted: a fresh entity read from the DB sees the cached body.
    reloaded = repo.get(message.id)  # type: ignore[arg-type]
    assert reloaded is not None and reloaded.body_fetched
    cached = service.get_cached(reloaded)
    assert cached is not None and cached.text.strip() == "the body"
    # And the .eml file exists on disk.
    assert (tmp_path / f"{message.id}.eml").exists()
