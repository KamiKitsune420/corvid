"""Find-messages dialog: search the current folder, then jump to a result.

Type a query and press Search; the box and Search button collapse away, leaving
the results list and Cancel. Activating a result closes the dialog with that
message selected so the caller can reveal it in the folder.
"""

from __future__ import annotations

from collections.abc import Callable

import wx

from ..domain.entities import Message
from .accessibility import accessible_name

SearchFn = Callable[[str], list[Message]]


class FindDialog(wx.Dialog):
    def __init__(self, parent: wx.Window | None, search_fn: SearchFn) -> None:
        super().__init__(parent, title="Find Messages", size=(520, 440))
        self._search_fn = search_fn
        self._rows: list[Message] = []
        self.selected_message_id: int | None = None

        self._prompt = wx.StaticText(self, label="&Find what:")
        self._query = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        accessible_name(self._query, "Find what")
        self._query.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self._search_btn = wx.Button(self, label="&Search")
        self._search_btn.Bind(wx.EVT_BUTTON, self._on_search)

        self._search_row = wx.BoxSizer(wx.HORIZONTAL)
        self._search_row.Add(self._prompt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._search_row.Add(self._query, 1, wx.RIGHT, 6)
        self._search_row.Add(self._search_btn, 0)

        self._results = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        accessible_name(self._results, "Search results")
        self._results.InsertColumn(0, "Subject", width=280)
        self._results.InsertColumn(1, "From", width=180)
        self._results.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_pick)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self._search_row, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(self._results, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(self.CreateButtonSizer(wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)
        self._query.SetFocus()

    def _on_search(self, _event: wx.CommandEvent) -> None:
        query = self._query.GetValue().strip()
        if not query:
            return
        self._rows = self._search_fn(query)
        self._results.DeleteAllItems()
        for i, message in enumerate(self._rows):
            idx = self._results.InsertItem(i, message.subject or "(no subject)")
            self._results.SetItem(idx, 1, message.from_name or message.from_addr)
            self._results.SetItemData(idx, i)

        # Collapse the query box + Search button, leaving the results and Cancel.
        self._prompt.Hide()
        self._query.Hide()
        self._search_btn.Hide()
        count = len(self._rows)
        self.SetTitle(f"Find — {count} result{'s' if count != 1 else ''} for '{query}'")
        self.Layout()
        if self._rows:
            self._results.Select(0)
            self._results.Focus(0)
        self._results.SetFocus()

    def _on_pick(self, event: wx.ListEvent) -> None:
        index = self._results.GetItemData(event.GetIndex())
        message = self._rows[index]
        self.selected_message_id = message.id
        self.EndModal(wx.ID_OK)
