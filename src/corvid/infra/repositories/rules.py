"""Rule repository: persists rules as JSON in the ``rules`` table."""

from __future__ import annotations

import json
import sqlite3

from ...domain.rules import (
    Action,
    ActionType,
    Condition,
    MatchField,
    MatchMode,
    MatchOp,
    Rule,
)
from ._rows import from_bool, last_id, to_bool
from .base import Repository


def _rule_to_json(rule: Rule) -> tuple[str, str]:
    match = {
        "mode": rule.mode.value,
        "conditions": [
            {"field": c.field.value, "op": c.op.value, "value": c.value}
            for c in rule.conditions
        ],
    }
    actions = [{"type": a.type.value, "param": a.param} for a in rule.actions]
    return json.dumps(match), json.dumps(actions)


def _rule_from_row(row: sqlite3.Row) -> Rule:
    match = json.loads(row["match_json"] or "{}")
    actions = json.loads(row["actions_json"] or "[]")
    return Rule(
        id=row["id"],
        name=row["name"],
        enabled=to_bool(row["enabled"]),
        priority=row["priority"],
        mode=MatchMode(match.get("mode", "all")),
        conditions=[
            Condition(MatchField(c["field"]), MatchOp(c["op"]), c["value"])
            for c in match.get("conditions", [])
        ],
        actions=[Action(ActionType(a["type"]), a.get("param", "")) for a in actions],
    )


class RuleRepository(Repository):
    def add(self, rule: Rule) -> Rule:
        match_json, actions_json = _rule_to_json(rule)
        cur = self.conn.execute(
            """
            INSERT INTO rules (name, enabled, priority, match_json, actions_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rule.name, from_bool(rule.enabled), rule.priority, match_json, actions_json),
        )
        rule.id = last_id(cur)
        return rule

    def update(self, rule: Rule) -> None:
        if rule.id is None:
            raise ValueError("Cannot update a rule without an id.")
        match_json, actions_json = _rule_to_json(rule)
        self.conn.execute(
            """
            UPDATE rules SET name = ?, enabled = ?, priority = ?,
                match_json = ?, actions_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                rule.name,
                from_bool(rule.enabled),
                rule.priority,
                match_json,
                actions_json,
                rule.id,
            ),
        )

    def get(self, rule_id: int) -> Rule | None:
        row = self.conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
        return _rule_from_row(row) if row else None

    def list(self) -> list[Rule]:
        rows = self.conn.execute("SELECT * FROM rules ORDER BY priority, id").fetchall()
        return [_rule_from_row(r) for r in rows]

    def delete(self, rule_id: int) -> None:
        self.conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
