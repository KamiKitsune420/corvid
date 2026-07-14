"""A compact dialog to view, add, toggle, and delete message rules."""

from __future__ import annotations

import wx

from ..domain.rules import (
    Action,
    ActionType,
    Condition,
    MatchField,
    MatchMode,
    MatchOp,
    Rule,
)
from ..infra.repositories import RuleRepository

_FIELDS = [(f.value.title(), f) for f in (MatchField.FROM, MatchField.TO, MatchField.SUBJECT)]
_OPS = [(o.value, o) for o in MatchOp]
_ACTIONS = [
    ("Mark read", ActionType.MARK_READ),
    ("Flag", ActionType.FLAG),
    ("Delete", ActionType.DELETE),
    ("Move to folder", ActionType.MOVE),
]


class RulesDialog(wx.Dialog):
    def __init__(self, parent: wx.Window | None, repo: RuleRepository) -> None:
        super().__init__(parent, title="Message Rules", size=(520, 520))
        self._repo = repo
        panel = wx.Panel(self)

        self._list = wx.CheckListBox(panel)
        self._list.Bind(wx.EVT_CHECKLISTBOX, self.on_toggle)

        name = wx.StaticText(panel, label="When a new message arrives:")
        self._field = wx.Choice(panel, choices=[label for label, _ in _FIELDS])
        self._op = wx.Choice(panel, choices=[label for label, _ in _OPS])
        self._value = wx.TextCtrl(panel)
        self._action = wx.Choice(panel, choices=[label for label, _ in _ACTIONS])
        self._param = wx.TextCtrl(panel)
        self._param.SetHint("folder (for Move)")
        for choice in (self._field, self._op, self._action):
            choice.SetSelection(0)

        cond = wx.BoxSizer(wx.HORIZONTAL)
        for widget in (self._field, self._op, self._value):
            cond.Add(widget, 1, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 4)
        act = wx.BoxSizer(wx.HORIZONTAL)
        act.Add(wx.StaticText(panel, label="then"), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 4)
        act.Add(self._action, 1, wx.RIGHT, 4)
        act.Add(self._param, 1)

        add_btn = wx.Button(panel, label="Add Rule")
        del_btn = wx.Button(panel, label="Delete Selected")
        close_btn = wx.Button(panel, wx.ID_CLOSE, label="Close")
        add_btn.Bind(wx.EVT_BUTTON, self.on_add)
        del_btn.Bind(wx.EVT_BUTTON, self.on_delete)
        close_btn.Bind(wx.EVT_BUTTON, lambda _e: self.Close())
        btns = wx.BoxSizer(wx.HORIZONTAL)
        btns.Add(add_btn, 0, wx.RIGHT, 6)
        btns.Add(del_btn, 0)
        btns.AddStretchSpacer()
        btns.Add(close_btn, 0)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(panel, label="Rules (checked = enabled):"), 0, wx.ALL, 8)
        outer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        outer.Add(name, 0, wx.ALL, 8)
        outer.Add(cond, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        outer.Add(act, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(btns, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(outer)

        self._rules: list[Rule] = []
        self._reload()

    def _reload(self) -> None:
        self._rules = self._repo.list()
        self._list.Set([self._describe(r) for r in self._rules])
        for index, rule in enumerate(self._rules):
            self._list.Check(index, rule.enabled)

    @staticmethod
    def _describe(rule: Rule) -> str:
        cond = ", ".join(f"{c.field.value} {c.op.value} '{c.value}'" for c in rule.conditions)
        act = ", ".join(a.type.value + (f"->{a.param}" if a.param else "") for a in rule.actions)
        return f"{rule.name}: if {cond} then {act}"

    # -- events -------------------------------------------------------------
    def on_toggle(self, event: wx.CommandEvent) -> None:
        index = event.GetInt()
        rule = self._rules[index]
        rule.enabled = self._list.IsChecked(index)
        self._repo.update(rule)

    def on_add(self, _event: wx.CommandEvent) -> None:
        value = self._value.GetValue().strip()
        if not value:
            wx.MessageBox("Enter a value to match.", "Add Rule", wx.ICON_WARNING)
            return
        field = _FIELDS[self._field.GetSelection()][1]
        op = _OPS[self._op.GetSelection()][1]
        action_type = _ACTIONS[self._action.GetSelection()][1]
        param = self._param.GetValue().strip()
        rule = Rule(
            id=None,
            name=f"{field.value} {op.value} {value}",
            mode=MatchMode.ALL,
            conditions=[Condition(field, op, value)],
            actions=[Action(action_type, param)],
        )
        self._repo.add(rule)
        self._value.SetValue("")
        self._param.SetValue("")
        self._reload()

    def on_delete(self, _event: wx.CommandEvent) -> None:
        index = self._list.GetSelection()
        if index == wx.NOT_FOUND:
            return
        rule = self._rules[index]
        if rule.id is not None:
            self._repo.delete(rule.id)
        self._reload()
