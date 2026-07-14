from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from email.message import EmailMessage

from corvid.domain.entities import (
    Account,
    ConnectionSecurity,
    Folder,
    FolderType,
    Message,
    MessageFlags,
)
from corvid.domain.threads import (
    build_threads,
    normalize_message_id,
    parse_reference_ids,
)
from corvid.infra.mail.parsing import header_fields_from_raw
from corvid.infra.repositories import AccountRepository, FolderRepository, MessageRepository
from corvid.ui.presenters import MessageListPresenter


def _seed(db: sqlite3.Connection) -> tuple[int, int]:
    """Create one account + INBOX folder; return their ids."""
    account = AccountRepository(db).add(
        Account(
            id=None, display_name="A", email="a@x", username="a",
            imap_host="imap", imap_port=993, imap_security=ConnectionSecurity.TLS,
            smtp_host="smtp", smtp_port=587, smtp_security=ConnectionSecurity.STARTTLS,
        )
    )
    folder = FolderRepository(db).upsert(
        Folder(id=None, account_id=account.id, remote_name="INBOX",  # type: ignore[arg-type]
               display_name="INBOX", type=FolderType.INBOX)
    )
    return account.id, folder.id  # type: ignore[return-value]


def _msg(
    mid: str,
    *,
    subject: str = "",
    in_reply_to: str = "",
    references: str = "",
    day: int = 1,
    seen: bool = True,
) -> Message:
    return Message(
        id=None,
        folder_id=1,
        account_id=1,
        uid=day,
        message_id=mid,
        subject=subject,
        in_reply_to=in_reply_to,
        references=references,
        date_utc=datetime(2026, 7, day, 12, 0, tzinfo=UTC),
        flags=MessageFlags(seen=seen),
    )


# --------------------------------------------------------------------------
# normalization / parsing
# --------------------------------------------------------------------------
def test_normalize_message_id() -> None:
    assert normalize_message_id(" <ABC@Host> ") == "abc@host"
    assert normalize_message_id("plain@id") == "plain@id"


def test_parse_reference_ids_splits_and_normalizes() -> None:
    assert parse_reference_ids("<a@x> <B@x>\n <c@x>") == ["a@x", "b@x", "c@x"]
    assert parse_reference_ids("") == []


# --------------------------------------------------------------------------
# threading
# --------------------------------------------------------------------------
def test_reply_chain_groups_into_one_thread() -> None:
    original = _msg("<1@x>", subject="Budget", day=1)
    reply = _msg("<2@x>", subject="Re: Budget", in_reply_to="<1@x>", day=2)
    reply2 = _msg("<3@x>", subject="Re: Budget", references="<1@x> <2@x>", day=3)
    threads = build_threads([reply2, original, reply])
    assert len(threads) == 1
    thread = threads[0]
    assert thread.is_conversation
    # ordered oldest-first: original, then replies
    assert [m.message_id for m in thread.messages] == ["<1@x>", "<2@x>", "<3@x>"]
    assert thread.newest.message_id == "<3@x>"


def test_unrelated_messages_stay_separate() -> None:
    a = _msg("<a@x>", subject="Hi", day=1)
    b = _msg("<b@x>", subject="Hi", day=2)  # same subject, NO reply headers
    threads = build_threads([a, b])
    assert len(threads) == 2  # subject alone does not merge — headers only
    assert all(not t.is_conversation for t in threads)


def test_threads_ordered_by_newest_message_first() -> None:
    old = _msg("<old@x>", day=1)
    convo_a = _msg("<a1@x>", day=2)
    convo_a2 = _msg("<a2@x>", in_reply_to="<a1@x>", day=9)  # newest overall
    threads = build_threads([old, convo_a, convo_a2])
    # The conversation (newest message day 9) comes before the day-1 singleton.
    assert threads[0].newest.message_id == "<a2@x>"
    assert threads[1].messages[0].message_id == "<old@x>"


def test_missing_reference_target_does_not_crash() -> None:
    reply = _msg("<r@x>", in_reply_to="<not-present@x>", day=1)
    threads = build_threads([reply])
    assert len(threads) == 1
    assert not threads[0].is_conversation


# --------------------------------------------------------------------------
# header extraction
# --------------------------------------------------------------------------
def test_header_fields_extract_reply_headers() -> None:
    msg = EmailMessage()
    msg["Message-ID"] = "<2@x>"
    msg["In-Reply-To"] = "<1@x>"
    msg["References"] = "<0@x> <1@x>"
    msg["Subject"] = "Re: hi"
    msg.set_content("body")
    headers = header_fields_from_raw(msg.as_bytes())
    assert headers.in_reply_to == "<1@x>"
    assert headers.references == "<0@x> <1@x>"  # folded whitespace collapsed


# --------------------------------------------------------------------------
# persistence round-trip (migration v7 columns)
# --------------------------------------------------------------------------
def test_reply_headers_survive_db_round_trip(db: sqlite3.Connection) -> None:
    account_id, folder_id = _seed(db)
    repo = MessageRepository(db)
    stored = repo.insert_header(
        Message(
            id=None, folder_id=folder_id, account_id=account_id, uid=99,
            message_id="<reply@x>", subject="Re: x",
            in_reply_to="<orig@x>", references="<orig@x>",
        )
    )
    assert stored.id is not None
    fetched = repo.get(stored.id)
    assert fetched is not None
    assert fetched.in_reply_to == "<orig@x>"
    assert fetched.references == "<orig@x>"


# --------------------------------------------------------------------------
# presenter grouping
# --------------------------------------------------------------------------
def _seed_thread(db: sqlite3.Connection) -> int:
    account = AccountRepository(db).list()[0]
    folder = FolderRepository(db).list_for_account(account.id)[0]  # type: ignore[arg-type]
    repo = MessageRepository(db)
    now = datetime(2026, 7, 1, tzinfo=UTC)
    repo.insert_header(Message(id=None, folder_id=folder.id, account_id=account.id,  # type: ignore[arg-type]
                               uid=10, message_id="<o@x>", subject="Plan", date_utc=now,
                               flags=MessageFlags(seen=True)))
    repo.insert_header(Message(id=None, folder_id=folder.id, account_id=account.id,  # type: ignore[arg-type]
                               uid=11, message_id="<r@x>", subject="Re: Plan",
                               in_reply_to="<o@x>", date_utc=now, flags=MessageFlags(seen=False)))
    return folder.id  # type: ignore[return-value]


def test_presenter_groups_conversation(db: sqlite3.Connection) -> None:
    _seed(db)
    folder_id = _seed_thread(db)
    groups = MessageListPresenter(MessageRepository(db)).conversations(folder_id, group=True)
    assert len(groups) == 1
    group = groups[0]
    assert group.is_conversation
    assert len(group.messages) == 2
    assert group.unread_count == 1
    assert "conversation, 2 messages" in group.speech


def test_presenter_flat_when_grouping_off(db: sqlite3.Connection) -> None:
    _seed(db)
    folder_id = _seed_thread(db)
    groups = MessageListPresenter(MessageRepository(db)).conversations(folder_id, group=False)
    assert len(groups) == 2  # each message its own single-item group
    assert all(not g.is_conversation for g in groups)
