"""Compose a newsgroup article (new post or follow-up)."""

from __future__ import annotations

import wx

from .accessibility import accessible_name, labeled_row


class PostDialog(wx.Dialog):
    """A plain-text article composer targeting one or more newsgroups."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        newsgroups: str,
        subject: str = "",
        body: str = "",
    ) -> None:
        super().__init__(parent, title="Post to Newsgroup", size=(560, 460))
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1, 1)

        self._groups = wx.TextCtrl(self)
        self._subject = wx.TextCtrl(self)
        labeled_row(self, grid, "&Newsgroups:", self._groups)
        labeled_row(self, grid, "&Subject:", self._subject)
        self._groups.SetValue(newsgroups)
        self._subject.SetValue(subject)

        self._body = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        accessible_name(self._body, "Message body")
        self._body.SetValue(body)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(wx.StaticText(self, label="&Message:"), 0, wx.LEFT, 10)
        outer.Add(self._body, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)
        (self._subject if subject else self._body).SetFocus()

    @property
    def newsgroups(self) -> str:
        return self._groups.GetValue().strip()

    @property
    def subject(self) -> str:
        return self._subject.GetValue().strip()

    @property
    def body(self) -> str:
        return self._body.GetValue()
