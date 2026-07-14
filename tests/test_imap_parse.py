from __future__ import annotations

from corvid.infra.mail.imap_store import (
    parse_envelope,
    parse_fetch_response,
    parse_list_line,
)
from corvid.infra.mail.types import FolderInfo
from corvid.service.sync import classify_folder

HEADER = (
    b"Subject: =?utf-8?q?Hello_=C2=A1?=\r\n"
    b"From: Alice Example <alice@example.com>\r\n"
    b"To: bob@example.com, Carol <carol@example.com>\r\n"
    b"Cc: dave@example.com\r\n"
    b"Date: Tue, 01 Jan 2030 12:00:00 +0000\r\n"
    b"Message-ID: <abc123@example.com>\r\n"
    b"Content-Type: multipart/mixed; boundary=xyz\r\n"
    b"\r\n"
)
META = b"1 (UID 101 FLAGS (\\Seen \\Flagged) RFC822.SIZE 2048 BODY[HEADER.FIELDS (...)] {123}"


def test_parse_list_line_special_use() -> None:
    info = parse_list_line(b'(\\HasNoChildren \\Sent) "/" "Sent"')
    assert info is not None
    assert info.special_use == "\\Sent"
    assert info.display_name == "Sent"
    assert info.delimiter == "/"


def test_parse_list_line_inbox() -> None:
    info = parse_list_line(b'(\\HasNoChildren) "/" "INBOX"')
    assert info is not None
    assert info.special_use == "\\Inbox"


def test_parse_list_line_hierarchical() -> None:
    info = parse_list_line(b'(\\HasNoChildren) "/" "Work/Reports"')
    assert info is not None
    assert info.display_name == "Reports"
    assert info.remote_name == "Work/Reports"


def test_parse_envelope() -> None:
    env = parse_envelope(META, HEADER)
    assert env.uid == 101
    assert env.size == 2048
    assert env.seen is True
    assert env.flagged is True
    assert env.subject == "Hello ¡"
    assert env.from_name == "Alice Example"
    assert env.from_addr == "alice@example.com"
    assert "carol@example.com" in env.to_addrs
    assert env.cc_addrs == "dave@example.com"
    assert env.has_attachments is True
    assert env.date_utc is not None and env.date_utc.year == 2030


def test_parse_fetch_response_skips_closers() -> None:
    data = [(META, HEADER), b")"]
    envs = parse_fetch_response(data)
    assert len(envs) == 1 and envs[0].uid == 101


def test_classify_folder_by_name() -> None:
    assert classify_folder(FolderInfo("Spam", "Spam")).value == "junk"
    assert classify_folder(FolderInfo("Misc", "Misc")).value == "custom"
    assert classify_folder(FolderInfo("Sent", "Sent", special_use="\\Sent")).value == "sent"
