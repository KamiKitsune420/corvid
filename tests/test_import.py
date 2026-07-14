from __future__ import annotations

import mailbox
import sqlite3
from pathlib import Path

import pytest

from corvid.domain.entities import Account, ConnectionSecurity, FolderType
from corvid.infra.importers import (
    DbxImporter,
    EmlDirectoryImporter,
    MaildirImporter,
    MboxImporter,
    SourceKind,
    detect_kind,
)
from corvid.infra.mail.parsing import header_fields_from_raw
from corvid.infra.repositories import (
    AccountRepository,
    FolderRepository,
    MessageRepository,
)
from corvid.service.import_store import ImportService, classify_imported_folder


def _account(db: sqlite3.Connection) -> Account:
    return AccountRepository(db).add(
        Account(
            id=None, display_name="Alice", email="alice@example.com", username="alice",
            imap_host="imap.example.com", imap_port=993, imap_security=ConnectionSecurity.TLS,
            smtp_host="smtp.example.com", smtp_port=587,
            smtp_security=ConnectionSecurity.STARTTLS,
        )
    )


def _raw(subject: str, *, frm: str = "Bob <bob@example.com>", to: str = "alice@example.com",
         mid: str = "", body: str = "hello") -> bytes:
    mid = mid or f"<{subject.replace(' ', '')}@example.com>"
    return (
        f"From: {frm}\r\n"
        f"To: {to}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: {mid}\r\n"
        f"Date: Mon, 6 Jul 2026 10:00:00 +0000\r\n"
        f"\r\n{body}\r\n"
    ).encode()


# -- header extraction -------------------------------------------------------

def test_header_fields_from_raw() -> None:
    h = header_fields_from_raw(_raw("Hi there", frm="Bob Jones <bob@example.com>"))
    assert h.subject == "Hi there"
    assert h.from_name == "Bob Jones"
    assert h.from_addr == "bob@example.com"
    assert h.to_addrs == "alice@example.com"
    assert h.message_id == "<Hithere@example.com>"
    assert h.date_utc is not None and h.date_utc.year == 2026
    assert not h.has_attachments


def test_header_fields_tolerates_garbage() -> None:
    h = header_fields_from_raw(b"not a real \x00 message at all")
    assert h.subject == ""
    assert h.date_utc is None
    assert h.size == len(b"not a real \x00 message at all")


# -- detection ---------------------------------------------------------------

def test_detect_kind(tmp_path: Path) -> None:
    mbox = tmp_path / "Inbox.mbox"
    mbox.write_bytes(b"")
    assert detect_kind(mbox) is SourceKind.MBOX

    dbx = tmp_path / "Inbox.dbx"
    dbx.write_bytes(b"")
    assert detect_kind(dbx) is SourceKind.DBX

    maildir = tmp_path / "md"
    for sub in ("cur", "new", "tmp"):
        (maildir / sub).mkdir(parents=True)
    assert detect_kind(maildir) is SourceKind.MAILDIR

    emldir = tmp_path / "emls"
    emldir.mkdir()
    assert detect_kind(emldir) is SourceKind.EML_DIR


def test_classify_imported_folder() -> None:
    assert classify_imported_folder("Inbox") is FolderType.INBOX
    assert classify_imported_folder("Sent Items") is FolderType.SENT
    assert classify_imported_folder("Random") is FolderType.CUSTOM


# -- mbox importer -----------------------------------------------------------

def test_mbox_importer(tmp_path: Path) -> None:
    path = tmp_path / "Saved.mbox"
    box = mailbox.mbox(str(path))
    box.lock()
    for i in range(3):
        msg = mailbox.mboxMessage(_raw(f"msg {i}"))
        if i == 0:
            msg.add_flag("R")  # read
        box.add(msg)
    box.flush()
    box.unlock()
    box.close()

    folders = list(MboxImporter(path).folders())
    assert len(folders) == 1
    assert folders[0].name == "Saved"
    msgs = list(folders[0].messages)
    assert len(msgs) == 3
    assert msgs[0].seen is True  # flagged read


def test_eml_directory_importer(tmp_path: Path) -> None:
    d = tmp_path / "export"
    d.mkdir()
    (d / "a.eml").write_bytes(_raw("first"))
    (d / "sub").mkdir()
    (d / "sub" / "b.eml").write_bytes(_raw("second"))
    (d / "notes.txt").write_bytes(b"ignore me")

    folders = list(EmlDirectoryImporter(d).folders())
    assert len(folders) == 1
    msgs = list(folders[0].messages)
    assert len(msgs) == 2


def test_maildir_importer(tmp_path: Path) -> None:
    md = tmp_path / "md"
    for sub in ("cur", "new", "tmp"):
        (md / sub).mkdir(parents=True)
    # A read+flagged message in cur, an unread one in new.
    (md / "cur" / "1700000000.abc;2,SF").write_bytes(_raw("seen one"))
    (md / "new" / "1700000001.def").write_bytes(_raw("fresh one"))
    # A Maildir++ subfolder.
    sub = md / ".Archive"
    for s in ("cur", "new", "tmp"):
        (sub / s).mkdir(parents=True)
    (sub / "cur" / "1700000002.ghi;2,S").write_bytes(_raw("archived"))

    folders = {f.name: list(f.messages) for f in MaildirImporter(md).folders()}
    assert set(folders) == {"md", "Archive"}
    root = folders["md"]
    assert len(root) == 2
    by_subject = {header_fields_from_raw(m.raw).subject: m for m in root}
    assert by_subject["seen one"].seen is True
    assert by_subject["seen one"].flagged is True
    assert by_subject["fresh one"].seen is False
    assert len(folders["Archive"]) == 1


# -- dbx importer ------------------------------------------------------------

def _build_dbx(messages: list[bytes], *, file_type: int = 0x6F74FDC5) -> bytes:
    """Construct a minimal but format-accurate OE .dbx message store."""
    buf = bytearray(0x300)

    def put_u32(off: int, val: int) -> None:
        buf[off : off + 4] = val.to_bytes(4, "little")

    def put_u16(off: int, val: int) -> None:
        buf[off : off + 2] = val.to_bytes(2, "little")

    def alloc(size: int) -> int:
        off = len(buf)
        buf.extend(b"\x00" * size)
        return off

    put_u32(0x00, 0xFE12ADCF)      # magic
    put_u32(0x04, file_type)        # discriminator (message store by default)
    put_u32(0xC4, len(messages))    # item count

    info_offsets: list[int] = []
    for raw in messages:
        chunks = [raw[i : i + 0x200] for i in range(0, len(raw), 0x200)] or [b""]
        seg_offsets = [alloc(0x10 + len(c)) for c in chunks]
        for idx, (off, chunk) in enumerate(zip(seg_offsets, chunks, strict=True)):
            put_u32(off + 0x00, off)                 # self pointer
            put_u32(off + 0x04, 0x200)               # capacity
            put_u16(off + 0x08, len(chunk))          # used bytes
            nxt = seg_offsets[idx + 1] if idx + 1 < len(seg_offsets) else 0
            put_u32(off + 0x0C, nxt)                 # next segment
            buf[off + 0x10 : off + 0x10 + len(chunk)] = chunk
        info = alloc(0x0C + 4)
        put_u32(info + 0x00, info)                   # self pointer
        put_u32(info + 0x08, 1 << 16)                # attribute count = 1 (byte at 0x0A)
        put_u32(info + 0x0C, 0x84 | (seg_offsets[0] << 8))  # direct body pointer (id 0x04|0x80)
        info_offsets.append(info)

    node = alloc(0x27C)
    put_u32(0xE4, node)                              # root tree pointer
    put_u32(node + 0x00, node)                       # self pointer
    buf[node + 0x11] = len(info_offsets)             # entry count
    put_u32(node + 0x14, len(info_offsets))          # subtree total
    for i, info in enumerate(info_offsets):
        entry = node + 0x18 + i * 12
        put_u32(entry + 0x00, info)                  # value pointer
    return bytes(buf)


def test_dbx_roundtrip(tmp_path: Path) -> None:
    small = _raw("small one")
    large = _raw("large one", body="X" * 1500)  # spans multiple 512-byte segments
    path = tmp_path / "Inbox.dbx"
    path.write_bytes(_build_dbx([small, large]))

    folders = list(DbxImporter(path).folders())
    assert len(folders) == 1 and folders[0].name == "Inbox"
    raws = {m.raw for m in folders[0].messages}
    assert small in raws
    assert large in raws


def test_dbx_rejects_non_message_store(tmp_path: Path) -> None:
    path = tmp_path / "Folders.dbx"
    path.write_bytes(_build_dbx([], file_type=0x6F74FDC6))  # Folders.dbx type
    with pytest.raises(ValueError, match="not a message store"):
        list(DbxImporter(path).folders())


def test_dbx_rejects_garbage(tmp_path: Path) -> None:
    path = tmp_path / "bogus.dbx"
    path.write_bytes(b"\x00" * 512)
    with pytest.raises(ValueError, match="not an Outlook Express"):
        list(DbxImporter(path).folders())


# -- import service ----------------------------------------------------------

def test_import_service_into_db(db: sqlite3.Connection, tmp_path: Path) -> None:
    account = _account(db)
    assert account.id is not None
    path = tmp_path / "Inbox.mbox"
    box = mailbox.mbox(str(path))
    for i in range(4):
        box.add(mailbox.mboxMessage(_raw(f"msg {i}")))
    box.flush()
    box.close()

    messages_dir = tmp_path / "messages"
    service = ImportService(FolderRepository(db), MessageRepository(db), messages_dir)
    summary = service.import_into(account.id, MboxImporter(path))

    assert summary.folders == 1
    assert summary.imported == 4
    folder = FolderRepository(db).get_by_remote(account.id, "import:Inbox")
    assert folder is not None
    assert folder.type is FolderType.INBOX
    assert folder.total_count == 4

    stored = MessageRepository(db).list_for_folder(folder.id)  # type: ignore[arg-type]
    assert len(stored) == 4
    first = stored[0]
    # Body was cached on disk and marked fetched, with uid NULL (invisible to IMAP sync).
    assert first.uid is None
    assert first.body_fetched is True
    assert Path(first.raw_path).exists()


def test_import_is_idempotent_by_message_id(db: sqlite3.Connection, tmp_path: Path) -> None:
    account = _account(db)
    assert account.id is not None
    path = tmp_path / "Inbox.mbox"
    box = mailbox.mbox(str(path))
    box.add(mailbox.mboxMessage(_raw("only", mid="<stable@example.com>")))
    box.flush()
    box.close()

    messages_dir = tmp_path / "messages"
    service = ImportService(FolderRepository(db), MessageRepository(db), messages_dir)
    first = service.import_into(account.id, MboxImporter(path))
    assert first.imported == 1
    second = service.import_into(account.id, MboxImporter(path))
    assert second.imported == 0
    assert second.skipped == 1
