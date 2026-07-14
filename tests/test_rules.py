from __future__ import annotations

import sqlite3

from corvid.domain.entities import (
    Account,
    ConnectionSecurity,
    Folder,
    FolderType,
    Message,
)
from corvid.domain.rules import (
    Action,
    ActionType,
    Condition,
    MatchField,
    MatchMode,
    MatchOp,
    Rule,
    RuleEngine,
    condition_matches,
    rule_matches,
)
from corvid.infra.repositories import (
    AccountRepository,
    FolderRepository,
    MessageRepository,
    RuleRepository,
)
from corvid.service.rules import RuleService


def _msg(subject: str = "", from_addr: str = "", to: str = "") -> Message:
    return Message(id=1, folder_id=1, account_id=1, uid=1, message_id="<x>",
                   subject=subject, from_addr=from_addr, to_addrs=to)


def test_condition_ops() -> None:
    m = _msg(subject="Hello World", from_addr="bob@spam.com")
    assert condition_matches(Condition(MatchField.SUBJECT, MatchOp.CONTAINS, "world"), m)
    assert condition_matches(Condition(MatchField.FROM, MatchOp.ENDSWITH, "spam.com"), m)
    assert not condition_matches(Condition(MatchField.SUBJECT, MatchOp.EQUALS, "hello"), m)
    assert condition_matches(Condition(MatchField.SUBJECT, MatchOp.REGEX, r"H\w+ W"), m)


def test_rule_match_modes() -> None:
    m = _msg(subject="invoice", from_addr="billing@acme.com")
    all_rule = Rule(id=1, name="r", mode=MatchMode.ALL, conditions=[
        Condition(MatchField.SUBJECT, MatchOp.CONTAINS, "invoice"),
        Condition(MatchField.FROM, MatchOp.CONTAINS, "acme"),
    ])
    assert rule_matches(all_rule, m)
    all_rule.conditions[1].value = "other"
    assert not rule_matches(all_rule, m)
    any_rule = Rule(id=1, name="r", mode=MatchMode.ANY, conditions=all_rule.conditions)
    assert rule_matches(any_rule, m)  # subject still matches


def test_engine_priority_and_stop() -> None:
    m = _msg(subject="urgent")
    high = Rule(id=1, name="high", priority=0,
                conditions=[Condition(MatchField.SUBJECT, MatchOp.CONTAINS, "urgent")],
                actions=[Action(ActionType.FLAG), Action(ActionType.STOP)])
    low = Rule(id=2, name="low", priority=1,
               conditions=[Condition(MatchField.SUBJECT, MatchOp.CONTAINS, "urgent")],
               actions=[Action(ActionType.DELETE)])
    actions = RuleEngine([low, high]).evaluate(m)
    assert actions == [Action(ActionType.FLAG)]  # stop halts before low's DELETE


def test_rule_repository_roundtrip(db: sqlite3.Connection) -> None:
    repo = RuleRepository(db)
    rule = Rule(id=None, name="flag spam", mode=MatchMode.ANY,
                conditions=[Condition(MatchField.FROM, MatchOp.CONTAINS, "spam")],
                actions=[Action(ActionType.FLAG)])
    saved = repo.add(rule)
    loaded = repo.get(saved.id)  # type: ignore[arg-type]
    assert loaded is not None
    assert loaded.mode is MatchMode.ANY
    assert loaded.conditions[0].field is MatchField.FROM
    assert loaded.actions[0].type is ActionType.FLAG


def _seed_account_folders(db: sqlite3.Connection) -> tuple[int, int, int]:
    account = AccountRepository(db).add(
        Account(id=None, display_name="A", email="a@x", username="a",
                imap_host="i", imap_port=993, imap_security=ConnectionSecurity.TLS,
                smtp_host="s", smtp_port=587, smtp_security=ConnectionSecurity.STARTTLS)
    )
    folders = FolderRepository(db)
    inbox = folders.upsert(Folder(id=None, account_id=account.id, remote_name="INBOX",  # type: ignore[arg-type]
                                  display_name="INBOX", type=FolderType.INBOX))
    junk = folders.upsert(Folder(id=None, account_id=account.id, remote_name="Junk",  # type: ignore[arg-type]
                                 display_name="Junk", type=FolderType.JUNK))
    return account.id, inbox.id, junk.id  # type: ignore[return-value]


def test_rule_service_flags_and_moves(db: sqlite3.Connection) -> None:
    account_id, inbox_id, junk_id = _seed_account_folders(db)
    rules = RuleRepository(db)
    rules.add(Rule(id=None, name="junk it",
                   conditions=[Condition(MatchField.FROM, MatchOp.CONTAINS, "spam")],
                   actions=[Action(ActionType.MARK_READ), Action(ActionType.MOVE, "junk")]))
    messages = MessageRepository(db)
    msg = messages.insert_header(
        Message(id=None, folder_id=inbox_id, account_id=account_id, uid=5,
                message_id="<5@x>", subject="Win big", from_addr="promo@spam.com")
    )
    service = RuleService(rules, messages, FolderRepository(db))
    performed = service.apply_to_message(account_id, msg)
    assert ActionType.MARK_READ in performed
    assert ActionType.MOVE in performed

    moved = messages.get(msg.id)  # type: ignore[arg-type]
    assert moved is not None
    assert moved.folder_id == junk_id
    assert moved.flags.seen is True
