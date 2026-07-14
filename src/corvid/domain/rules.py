"""Message rules: conditions, actions, and a pure evaluation engine.

A rule has one or more conditions (combined ALL/ANY) and one or more actions.
The engine evaluates enabled rules in priority order against a message and
returns the actions to perform. A ``stop`` action halts further rule processing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .entities import Message


class MatchField(StrEnum):
    FROM = "from"
    TO = "to"
    SUBJECT = "subject"


class MatchOp(StrEnum):
    CONTAINS = "contains"
    EQUALS = "equals"
    STARTSWITH = "startswith"
    ENDSWITH = "endswith"
    REGEX = "regex"


class MatchMode(StrEnum):
    ALL = "all"
    ANY = "any"


class ActionType(StrEnum):
    MARK_READ = "mark_read"
    MARK_UNREAD = "mark_unread"
    FLAG = "flag"
    DELETE = "delete"
    MOVE = "move"
    STOP = "stop"


@dataclass(slots=True)
class Condition:
    field: MatchField
    op: MatchOp
    value: str


@dataclass(slots=True)
class Action:
    type: ActionType
    param: str = ""


@dataclass(slots=True)
class Rule:
    id: int | None
    name: str
    enabled: bool = True
    priority: int = 0
    mode: MatchMode = MatchMode.ALL
    conditions: list[Condition] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)


def _field_value(field_: MatchField, message: Message) -> str:
    if field_ is MatchField.FROM:
        return f"{message.from_name} {message.from_addr}"
    if field_ is MatchField.TO:
        return f"{message.to_addrs} {message.cc_addrs}"
    return message.subject


def condition_matches(condition: Condition, message: Message) -> bool:
    haystack = _field_value(condition.field, message).lower()
    needle = condition.value.lower()
    op = condition.op
    if op is MatchOp.CONTAINS:
        return needle in haystack
    if op is MatchOp.EQUALS:
        return haystack.strip() == needle.strip()
    if op is MatchOp.STARTSWITH:
        return haystack.lstrip().startswith(needle)
    if op is MatchOp.ENDSWITH:
        return haystack.rstrip().endswith(needle)
    if op is MatchOp.REGEX:
        try:
            return re.search(condition.value, _field_value(condition.field, message)) is not None
        except re.error:
            return False
    return False


def rule_matches(rule: Rule, message: Message) -> bool:
    if not rule.conditions:
        return False
    results = (condition_matches(c, message) for c in rule.conditions)
    return all(results) if rule.mode is MatchMode.ALL else any(results)


class RuleEngine:
    """Evaluates an ordered set of rules against a message."""

    def __init__(self, rules: list[Rule]) -> None:
        self._rules = sorted(
            (r for r in rules if r.enabled), key=lambda r: (r.priority, r.id or 0)
        )

    def evaluate(self, message: Message) -> list[Action]:
        collected: list[Action] = []
        for rule in self._rules:
            if not rule_matches(rule, message):
                continue
            for action in rule.actions:
                if action.type is ActionType.STOP:
                    return collected
                collected.append(action)
        return collected
