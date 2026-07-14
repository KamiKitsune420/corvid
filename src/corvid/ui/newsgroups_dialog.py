"""Subscribe/unsubscribe from newsgroups on an NNTP account."""

from __future__ import annotations

import wx

from .accessibility import accessible_name


class NewsgroupsDialog(wx.Dialog):
    """Two-pane subscriber: available groups on the left, subscribed on the right.

    ``available`` (all groups the server advertised) can be large, so a filter box
    narrows it client-side; a manual entry lets the user subscribe to a group by
    exact name even if it is not in the fetched list. On OK, :attr:`subscribed`
    holds the desired set.
    """

    def __init__(
        self, parent: wx.Window | None, available: list[str], subscribed: set[str]
    ) -> None:
        super().__init__(parent, title="Newsgroups", size=(560, 460))
        self._available = sorted(available)
        self.subscribed: set[str] = set(subscribed)

        self._filter = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        accessible_name(self._filter, "Filter newsgroups")
        self._filter.Bind(wx.EVT_TEXT, lambda _e: self._refresh_available())

        self._avail_list = wx.ListBox(self, style=wx.LB_EXTENDED)
        accessible_name(self._avail_list, "Available newsgroups")
        self._sub_list = wx.ListBox(self, style=wx.LB_EXTENDED)
        accessible_name(self._sub_list, "Subscribed newsgroups")

        sub_btn = wx.Button(self, label="Subscribe →")
        unsub_btn = wx.Button(self, label="← Unsubscribe")
        sub_btn.Bind(wx.EVT_BUTTON, self.on_subscribe)
        unsub_btn.Bind(wx.EVT_BUTTON, self.on_unsubscribe)

        self._manual = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        accessible_name(self._manual, "Group name to add")
        add_btn = wx.Button(self, label="&Add by name")
        add_btn.Bind(wx.EVT_BUTTON, self.on_add_manual)
        self._manual.Bind(wx.EVT_TEXT_ENTER, self.on_add_manual)

        # Layout: [available | buttons | subscribed]
        mid = wx.BoxSizer(wx.VERTICAL)
        mid.AddStretchSpacer()
        mid.Add(sub_btn, 0, wx.EXPAND | wx.BOTTOM, 6)
        mid.Add(unsub_btn, 0, wx.EXPAND)
        mid.AddStretchSpacer()

        avail_box = wx.BoxSizer(wx.VERTICAL)
        avail_box.Add(wx.StaticText(self, label="Available (filter):"), 0)
        avail_box.Add(self._filter, 0, wx.EXPAND | wx.BOTTOM, 4)
        avail_box.Add(self._avail_list, 1, wx.EXPAND)

        sub_box = wx.BoxSizer(wx.VERTICAL)
        sub_box.Add(wx.StaticText(self, label="Subscribed:"), 0)
        sub_box.AddSpacer(self._filter.GetSize().height + 4)  # align with filter
        sub_box.Add(self._sub_list, 1, wx.EXPAND)

        lists = wx.BoxSizer(wx.HORIZONTAL)
        lists.Add(avail_box, 1, wx.EXPAND | wx.RIGHT, 8)
        lists.Add(mid, 0, wx.EXPAND | wx.RIGHT, 8)
        lists.Add(sub_box, 1, wx.EXPAND)

        manual = wx.BoxSizer(wx.HORIZONTAL)
        manual.Add(wx.StaticText(self, label="Group:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        manual.Add(self._manual, 1, wx.RIGHT, 6)
        manual.Add(add_btn, 0)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(lists, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(manual, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)

        self._refresh_available()
        self._refresh_subscribed()

    def _refresh_available(self) -> None:
        needle = self._filter.GetValue().strip().lower()
        shown = [g for g in self._available if needle in g.lower()] if needle else self._available
        self._avail_list.Set(shown[:2000])  # cap the widget; filter to narrow further

    def _refresh_subscribed(self) -> None:
        self._sub_list.Set(sorted(self.subscribed))

    def on_subscribe(self, _event: wx.CommandEvent) -> None:
        for i in self._avail_list.GetSelections():
            self.subscribed.add(self._avail_list.GetString(i))
        self._refresh_subscribed()

    def on_unsubscribe(self, _event: wx.CommandEvent) -> None:
        for i in self._sub_list.GetSelections():
            self.subscribed.discard(self._sub_list.GetString(i))
        self._refresh_subscribed()

    def on_add_manual(self, _event: wx.CommandEvent) -> None:
        name = self._manual.GetValue().strip()
        if name:
            self.subscribed.add(name)
            self._manual.SetValue("")
            self._refresh_subscribed()
