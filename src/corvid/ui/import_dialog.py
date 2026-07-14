"""Dialog to import a legacy/local mail store into an account."""

from __future__ import annotations

from pathlib import Path

import wx

from ..domain.entities import Account
from ..infra.importers import SourceKind, detect_kind
from .accessibility import accessible_name, labeled_row

_KIND_LABELS = {
    SourceKind.MBOX: "Unix mbox file",
    SourceKind.MAILDIR: "Maildir folder",
    SourceKind.EML_DIR: ".eml file(s)",
    SourceKind.DBX: "Outlook Express .dbx",
}


class ImportDialog(wx.Dialog):
    """Choose a source store and the account to import it into.

    A source may be a single file (mbox, ``.dbx``, or ``.eml``) or a directory
    (Maildir tree or a folder of ``.eml`` files), so both a file and a folder
    browser are offered. The detected format is shown for confirmation.
    """

    def __init__(self, parent: wx.Window | None, accounts: list[Account]) -> None:
        super().__init__(parent, title="Import Messages", size=(480, 260))
        self._accounts = accounts
        self.source_path: Path | None = None
        self.account_id: int | None = None

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        self._account = wx.Choice(self, choices=[f"{a.display_name} <{a.email}>" for a in accounts])
        if accounts:
            self._account.SetSelection(0)
        labeled_row(self, grid, "Import &into:", self._account)

        self._path_field = wx.TextCtrl(self, style=wx.TE_READONLY)
        accessible_name(self._path_field, "Selected source path")
        labeled_row(self, grid, "&Source:", self._path_field)

        self._kind_label = wx.StaticText(self, label="")
        labeled_row(self, grid, "Format:", self._kind_label)

        file_btn = wx.Button(self, label="Choose &File...")
        dir_btn = wx.Button(self, label="Choose Fol&der...")
        file_btn.Bind(wx.EVT_BUTTON, self.on_pick_file)
        dir_btn.Bind(wx.EVT_BUTTON, self.on_pick_dir)
        browse = wx.BoxSizer(wx.HORIZONTAL)
        browse.Add(file_btn, 0, wx.RIGHT, 8)
        browse.Add(dir_btn, 0)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)
        outer.Add(browse, 0, wx.LEFT | wx.BOTTOM, 12)
        outer.Add(
            wx.StaticText(
                self,
                label="Imported mail is stored locally and never uploaded to the server.",
            ),
            0,
            wx.LEFT | wx.RIGHT, 12,
        )
        outer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)

        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self._ok_button = self.FindWindowById(wx.ID_OK)
        if self._ok_button is not None:
            self._ok_button.Enable(False)

    def _set_source(self, path: Path) -> None:
        self.source_path = path
        self._path_field.SetValue(str(path))
        self._kind_label.SetLabel(_KIND_LABELS.get(detect_kind(path), "Unknown"))
        if self._ok_button is not None:
            self._ok_button.Enable(True)

    def on_pick_file(self, _event: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self,
            "Select a mail file",
            wildcard=(
                "Mail files (*.mbox;*.dbx;*.eml)|*.mbox;*.dbx;*.eml|All files (*.*)|*.*"
            ),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self._set_source(Path(dlg.GetPath()))

    def on_pick_dir(self, _event: wx.CommandEvent) -> None:
        with wx.DirDialog(
            self, "Select a Maildir or folder of .eml files", style=wx.DD_DIR_MUST_EXIST
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self._set_source(Path(dlg.GetPath()))

    def on_ok(self, _event: wx.CommandEvent) -> None:
        if self.source_path is None:
            return
        index = self._account.GetSelection()
        if index == wx.NOT_FOUND:
            return
        self.account_id = self._accounts[index].id
        self.EndModal(wx.ID_OK)
