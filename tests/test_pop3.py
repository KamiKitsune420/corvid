from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from corvid.domain.entities import Account, ConnectionSecurity, FolderType, ReceiveProtocol
from corvid.infra.mail.pop3_receiver import Pop3Receiver
from corvid.infra.repositories import (
    AccountRepository,
    FolderRepository,
    MessageRepository,
    Pop3UidlRepository,
)
from corvid.service.pop3 import Pop3Service


def _raw(subject: str, mid: str) -> bytes:
    return (
        f"From: Bob <bob@example.com>\r\nTo: me@example.com\r\n"
        f"Subject: {subject}\r\nMessage-ID: {mid}\r\n"
        f"Date: Mon, 6 Jul 2026 10:00:00 +0000\r\n\r\nbody of {subject}\r\n"
    ).encode()


def _pop3_account(db: sqlite3.Connection, *, leave: bool = True) -> Account:
    return AccountRepository(db).add(
        Account(
            id=None, display_name="Popper", email="me@example.com", username="me",
            imap_host="", imap_port=0, imap_security=ConnectionSecurity.TLS,
            smtp_host="smtp.example.com", smtp_port=587,
            smtp_security=ConnectionSecurity.STARTTLS,
            receive_protocol=ReceiveProtocol.POP3,
            pop3_host="pop.example.com", pop3_port=995,
            pop3_security=ConnectionSecurity.TLS, pop3_leave_on_server=leave,
        )
    )


# -- Pop3Receiver against a fake poplib client -------------------------------

class _FakePop3:
    def __init__(self, messages: list[tuple[str, bytes]]) -> None:
        # messages: (uidl, raw) in maildrop order (1-based numbers)
        self._messages = messages
        self.deleted: list[int] = []
        self.quit_called = False

    def uidl(self):
        lines = [f"{i + 1} {u}".encode() for i, (u, _) in enumerate(self._messages)]
        return b"+OK", lines, 0

    def retr(self, number: int):
        _uidl, raw = self._messages[number - 1]
        return b"+OK", raw.split(b"\r\n"), len(raw)

    def dele(self, number: int) -> None:
        self.deleted.append(number)

    def quit(self) -> None:
        self.quit_called = True

    def close(self) -> None:
        pass


def _receiver_with(fake: _FakePop3) -> Pop3Receiver:
    r = Pop3Receiver("h", 995, ConnectionSecurity.TLS, "u", "p")
    r._client = fake  # type: ignore[attr-defined]
    return r


def test_receiver_fetch_new_skips_seen() -> None:
    fake = _FakePop3([("aaa", _raw("one", "<1@x>")), ("bbb", _raw("two", "<2@x>"))])
    receiver = _receiver_with(fake)
    got = list(receiver.fetch_new({"aaa"}))
    assert [u for u, _ in got] == ["bbb"]
    assert b"body of two" in got[0][1]


def test_receiver_delete_marks_dele() -> None:
    fake = _FakePop3([("aaa", _raw("one", "<1@x>"))])
    receiver = _receiver_with(fake)
    list(receiver.fetch_new(set(), delete=True))
    assert fake.deleted == [1]


# -- Pop3Service against a fake receiver -------------------------------------

class _FakeReceiver:
    def __init__(self, messages: list[tuple[str, bytes]]) -> None:
        self._messages = messages
        self.delete_requested = False

    def fetch_new(self, seen: set[str], *, delete: bool = False) -> Iterator[tuple[str, bytes]]:
        self.delete_requested = delete
        for uidl, raw in self._messages:
            if uidl not in seen:
                yield uidl, raw


def test_pop3_service_downloads_into_inbox(db: sqlite3.Connection, tmp_path: Path) -> None:
    account = _pop3_account(db)
    assert account.id is not None
    receiver = _FakeReceiver([("aaa", _raw("one", "<1@x>")), ("bbb", _raw("two", "<2@x>"))])
    service = Pop3Service(
        FolderRepository(db), MessageRepository(db), Pop3UidlRepository(db), tmp_path / "msg"
    )
    summary = service.sync(account, receiver)  # type: ignore[arg-type]

    assert summary.new_messages == 2
    inbox = FolderRepository(db).get_by_remote(account.id, "INBOX")
    assert inbox is not None and inbox.type is FolderType.INBOX
    assert inbox.total_count == 2 and inbox.unread_count == 2  # received mail is unread
    stored = MessageRepository(db).list_for_folder(inbox.id)  # type: ignore[arg-type]
    assert len(stored) == 2
    assert stored[0].uid is None and stored[0].body_fetched is True
    assert Path(stored[0].raw_path).exists()


def test_pop3_service_is_idempotent(db: sqlite3.Connection, tmp_path: Path) -> None:
    account = _pop3_account(db)
    assert account.id is not None
    msgs = [("aaa", _raw("one", "<1@x>"))]
    service = Pop3Service(
        FolderRepository(db), MessageRepository(db), Pop3UidlRepository(db), tmp_path / "msg"
    )
    assert service.sync(account, _FakeReceiver(msgs)).new_messages == 1  # type: ignore[arg-type]
    # Second poll: UIDL already recorded, so nothing new downloads.
    assert service.sync(account, _FakeReceiver(msgs)).new_messages == 0  # type: ignore[arg-type]
    assert Pop3UidlRepository(db).seen(account.id) == {"aaa"}


def test_pop3_service_honors_leave_on_server(db: sqlite3.Connection, tmp_path: Path) -> None:
    account = _pop3_account(db, leave=False)
    receiver = _FakeReceiver([("aaa", _raw("one", "<1@x>"))])
    service = Pop3Service(
        FolderRepository(db), MessageRepository(db), Pop3UidlRepository(db), tmp_path / "msg"
    )
    service.sync(account, receiver)  # type: ignore[arg-type]
    assert receiver.delete_requested is True
