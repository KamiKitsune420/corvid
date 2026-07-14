from __future__ import annotations

import sqlite3

from fakes import FakeMailStore

from corvid.domain.entities import Account, ConnectionSecurity
from corvid.errors import ProtocolError
from corvid.infra.mail.types import FolderInfo, FolderStatus, HeaderEnvelope
from corvid.infra.repositories import AccountRepository, FolderRepository, MessageRepository
from corvid.service.sync import SyncService


def _account(db: sqlite3.Connection) -> Account:
    return AccountRepository(db).add(
        Account(
            id=None, display_name="Alice", email="alice@example.com", username="alice",
            imap_host="imap.example.com", imap_port=993, imap_security=ConnectionSecurity.TLS,
            smtp_host="smtp.example.com", smtp_port=587,
            smtp_security=ConnectionSecurity.STARTTLS,
        )
    )


def _env(uid: int, *, seen: bool = False) -> HeaderEnvelope:
    return HeaderEnvelope(
        uid=uid, message_id=f"<{uid}@x>", subject=f"msg {uid}",
        from_addr="bob@example.com", flags=frozenset({"\\Seen"} if seen else set()),
    )


def _store(envs: list[HeaderEnvelope], *, uidvalidity: int = 1) -> FakeMailStore:
    folders = [
        FolderInfo("INBOX", "INBOX", special_use="\\Inbox"),
        FolderInfo("Sent", "Sent", special_use="\\Sent"),
    ]
    status = FolderStatus(
        uidvalidity=uidvalidity,
        uidnext=max((e.uid for e in envs), default=0) + 1,
        exists=len(envs),
    )
    return FakeMailStore(folders, {"INBOX": (status, envs), "Sent": (
        FolderStatus(uidvalidity, 1, 0), [])})


def test_sync_account_full(db: sqlite3.Connection) -> None:
    account = _account(db)
    service = SyncService(FolderRepository(db), MessageRepository(db))
    store = _store([_env(101, seen=True), _env(102), _env(103)])

    summary = service.sync_account(account, store)
    assert summary.folders == 2
    assert summary.new_messages == 3
    assert summary.per_folder["INBOX"] == 3

    folder = FolderRepository(db).get_by_remote(account.id, "INBOX")  # type: ignore[arg-type]
    assert folder is not None
    assert folder.total_count == 3
    assert folder.unread_count == 2
    assert folder.uidvalidity == 1


def test_sync_is_incremental(db: sqlite3.Connection) -> None:
    account = _account(db)
    service = SyncService(FolderRepository(db), MessageRepository(db))
    store = _store([_env(101), _env(102)])
    assert service.sync_account(account, store).new_messages == 2

    # Two more arrive; only the new ones are fetched.
    inbox_status = FolderStatus(uidvalidity=1, uidnext=105, exists=4)
    store.set_mailbox("INBOX", inbox_status, [_env(101), _env(102), _env(103), _env(104)])
    second = service.sync_account(account, store)
    assert second.per_folder["INBOX"] == 2

    folder = FolderRepository(db).get_by_remote(account.id, "INBOX")  # type: ignore[arg-type]
    assert folder is not None and folder.total_count == 4


def test_sync_skips_noselect_folders(db: sqlite3.Connection) -> None:
    account = _account(db)
    service = SyncService(FolderRepository(db), MessageRepository(db))
    status = FolderStatus(uidvalidity=1, uidnext=1, exists=0)
    store = FakeMailStore(
        [
            FolderInfo("INBOX", "INBOX", special_use="\\Inbox"),
            FolderInfo("[Gmail]", "[Gmail]", flags=("\\Noselect", "\\HasChildren")),
            FolderInfo("[Gmail]/Sent", "Sent", special_use="\\Sent"),
        ],
        {"INBOX": (status, []), "[Gmail]/Sent": (status, [])},
    )
    names = [f.remote_name for f in service.sync_folders(account, store)]
    assert "[Gmail]" not in names  # container-only mailbox skipped
    assert "INBOX" in names and "[Gmail]/Sent" in names


def test_sync_account_continues_after_a_folder_error(db: sqlite3.Connection) -> None:
    account = _account(db)
    service = SyncService(FolderRepository(db), MessageRepository(db))

    class FlakyStore(FakeMailStore):
        def select(self, remote_name: str, *, readonly: bool = True) -> FolderStatus:
            if remote_name == "Bad":
                raise ProtocolError("STATUS failed for 'Bad': NO")
            return super().select(remote_name, readonly=readonly)

    status = FolderStatus(uidvalidity=1, uidnext=2, exists=1)
    store = FlakyStore(
        [
            FolderInfo("INBOX", "INBOX", special_use="\\Inbox"),
            FolderInfo("Bad", "Bad"),
            FolderInfo("Sent", "Sent", special_use="\\Sent"),
        ],
        {"INBOX": (status, [_env(101)]), "Bad": (status, []), "Sent": (status, [])},
    )
    summary = service.sync_account(account, store)  # must not raise
    assert "INBOX" in summary.per_folder and "Sent" in summary.per_folder
    assert "Bad" not in summary.per_folder  # the failing folder was skipped


def test_uidvalidity_change_resyncs(db: sqlite3.Connection) -> None:
    account = _account(db)
    service = SyncService(FolderRepository(db), MessageRepository(db))
    store = _store([_env(101), _env(102)])
    service.sync_account(account, store)

    # Server resets UIDVALIDITY -> local UIDs are stale and must be dropped.
    new_status = FolderStatus(uidvalidity=999, uidnext=51, exists=1)
    store.set_mailbox("INBOX", new_status, [_env(50)])
    service.sync_account(account, store)

    folder = FolderRepository(db).get_by_remote(account.id, "INBOX")  # type: ignore[arg-type]
    assert folder is not None
    assert folder.uidvalidity == 999
    assert folder.total_count == 1
    assert MessageRepository(db).existing_uids(folder.id) == {50}  # type: ignore[arg-type]
