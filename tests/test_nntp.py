from __future__ import annotations

import sqlite3

import pytest

from corvid.domain.entities import Account, AccountKind, ConnectionSecurity, FolderType
from corvid.domain.news import build_article
from corvid.errors import AuthError
from corvid.infra.mail.nntp_client import ActiveGroup, GroupInfo, NntpClient
from corvid.infra.mail.nntp_store import NntpMailStore, parse_overview_line
from corvid.infra.repositories import AccountRepository, FolderRepository, MessageRepository
from corvid.service.news import NewsService

# -- fakes -------------------------------------------------------------------

class FakeNntpClient:
    """Duck-typed stand-in for NntpClient used by NntpMailStore/NewsService."""

    def __init__(self, groups: dict[str, tuple[int, int, list[bytes]]]) -> None:
        # group -> (first, last, overview_lines); articles keyed by number
        self._groups = groups
        self.can_post = True
        self.posted: list[bytes] = []
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def group(self, name: str) -> GroupInfo:
        first, last, _ = self._groups[name]
        return GroupInfo(name=name, count=last - first + 1, first=first, last=last)

    def over(self, first: int, last: int) -> list[bytes]:
        for _, (_, _, lines) in self._groups.items():
            return [ln for ln in lines if first <= int(ln.split(b"\t")[0]) <= last]
        return []

    def article(self, number: int) -> bytes:
        return f"Subject: art {number}\r\n\r\nbody {number}".encode()

    def list_active(self, pattern: str | None = None) -> list[ActiveGroup]:
        return [ActiveGroup(name, 0, 0, "y") for name in self._groups]

    def post(self, article: bytes) -> None:
        self.posted.append(article)


def _ov(num: int, subject: str) -> bytes:
    # number, Subject, From, Date, Message-ID, References, :bytes, :lines
    return (
        f"{num}\t{subject}\tBob <bob@example.com>\tMon, 6 Jul 2026 10:00:00 +0000"
        f"\t<{num}@news>\t\t1234\t20"
    ).encode()


def _news_account(db: sqlite3.Connection) -> Account:
    return AccountRepository(db).add(
        Account(
            id=None, display_name="Newsy", email="me@example.com", username="",
            imap_host="", imap_port=0, imap_security=ConnectionSecurity.TLS,
            smtp_host="", smtp_port=0, smtp_security=ConnectionSecurity.TLS,
            kind=AccountKind.NEWS, nntp_host="news.example.com", nntp_port=119,
            nntp_security=ConnectionSecurity.NONE,
        )
    )


# -- overview parsing --------------------------------------------------------

def test_parse_overview_line() -> None:
    env = parse_overview_line(_ov(42, "Hello world"))
    assert env is not None
    assert env.uid == 42
    assert env.subject == "Hello world"
    assert env.from_addr == "bob@example.com"
    assert env.message_id == "<42@news>"
    assert env.size == 1234
    assert env.date_utc is not None and env.date_utc.year == 2026


def test_parse_overview_line_rejects_junk() -> None:
    assert parse_overview_line(b"not a number\tx") is None
    assert parse_overview_line(b"") is None


# -- store -------------------------------------------------------------------

def test_nntp_store_as_mailstore() -> None:
    lines = [_ov(1, "one"), _ov(2, "two"), _ov(3, "three")]
    client = FakeNntpClient({"comp.test": (1, 3, lines)})
    store = NntpMailStore(client, ["comp.test"])

    folders = store.list_folders()
    assert folders[0].is_newsgroup is True

    status = store.select("comp.test")
    assert status.exists == 3 and status.uidnext == 4

    assert store.search_uids(None) == [1, 2, 3]
    assert store.search_uids(1) == [2, 3]

    envs = store.fetch_headers([2, 3])
    assert {e.uid for e in envs} == {2, 3}
    assert b"body 2" in store.fetch_raw(2)


def test_nntp_store_initial_limit() -> None:
    client = FakeNntpClient({"big": (1, 1000, [])})
    store = NntpMailStore(client, ["big"], initial_limit=10)
    store.select("big")
    uids = store.search_uids(None)
    assert uids == list(range(991, 1001))  # only the most recent 10


# -- news service ------------------------------------------------------------

def test_news_subscribe_sync_unsubscribe(db: sqlite3.Connection) -> None:
    account = _news_account(db)
    assert account.id is not None
    lines = [_ov(1, "one"), _ov(2, "two")]
    client = FakeNntpClient({"comp.test": (1, 2, lines)})
    store = NntpMailStore(client, [])
    service = NewsService(FolderRepository(db), MessageRepository(db))

    folder = service.subscribe(account.id, "comp.test")
    assert folder.type is FolderType.NEWSGROUP
    assert service.subscribed_groups(account.id) == ["comp.test"]

    summary = service.sync(account, store)
    assert summary.new_messages == 2
    stored = MessageRepository(db).list_for_folder(folder.id)  # type: ignore[arg-type]
    assert len(stored) == 2

    service.unsubscribe(folder)
    assert service.subscribed_groups(account.id) == []
    assert MessageRepository(db).list_for_folder(folder.id) == []  # type: ignore[arg-type]


def test_news_post(db: sqlite3.Connection) -> None:
    account = _news_account(db)
    client = FakeNntpClient({"comp.test": (1, 1, [])})
    store = NntpMailStore(client, [])
    service = NewsService(FolderRepository(db), MessageRepository(db))

    service.post(account, store, newsgroups="comp.test", subject="Hi", body="hello group")
    assert len(client.posted) == 1
    assert b"Newsgroups: comp.test" in client.posted[0]
    assert b"hello group" in client.posted[0]


# -- article builder ---------------------------------------------------------

def test_build_article() -> None:
    raw = build_article(
        from_addr="me@example.com", from_name="Me", newsgroups="comp.lang.python",
        subject="Q", body="What is a metaclass?", references="<parent@news>",
    )
    assert b"From: Me <me@example.com>" in raw
    assert b"Newsgroups: comp.lang.python" in raw
    assert b"References: <parent@news>" in raw
    assert b"What is a metaclass?" in raw


# -- real client parsing (fake socket) --------------------------------------

class _FakeReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def readline(self) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _FakeSock:
    def __init__(self) -> None:
        self.sent = bytearray()

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def close(self) -> None:
        pass


def _client_with(responses: list[bytes]) -> tuple[NntpClient, _FakeSock]:
    client = NntpClient("h", 119, ConnectionSecurity.NONE)
    sock = _FakeSock()
    client._sock = sock  # type: ignore[attr-defined]
    client._reader = _FakeReader(responses)  # type: ignore[attr-defined]
    return client, sock


def test_client_group_and_article() -> None:
    client, sock = _client_with([
        b"211 3 1 3 comp.test\r\n",
        b"220 1 article\r\n",
        b"Subject: hi\r\n",
        b"..dotted line\r\n",   # dot-stuffed -> single dot
        b".\r\n",              # terminator
    ])
    info = client.group("comp.test")
    assert (info.first, info.last, info.count) == (1, 3, 3)
    raw = client.article(1)
    assert b"Subject: hi" in raw
    assert b".dotted line" in raw  # unstuffed
    assert b"GROUP comp.test\r\n" in sock.sent


def test_client_post_dot_stuffs() -> None:
    client, sock = _client_with([b"340 ok\r\n", b"240 received\r\n"])
    client.can_post = True
    client.post(b"Subject: x\r\n\r\n.leading dot\r\nnormal")
    # The body's leading-dot line must be stuffed to '..' on the wire.
    assert b"\r\n..leading dot\r\n" in sock.sent
    assert sock.sent.endswith(b"\r\n.\r\n")


def test_client_auth_failure() -> None:
    client, _ = _client_with([b"481 auth rejected\r\n"])
    client._username = "u"  # type: ignore[attr-defined]
    client._password = "p"  # type: ignore[attr-defined]
    with pytest.raises(AuthError):
        client._authenticate()  # type: ignore[attr-defined]
