"""Settings: general preferences, security, and per-account signatures."""

from __future__ import annotations

import sqlite3

import wx

from ..app.config import AppConfig
from ..app.paths import AppPaths
from ..errors import ConfigError
from ..infra.repositories import AccountRepository, IdentityRepository
from .accessibility import accessible_name, labeled_row

_THEMES = ["system", "light", "dark"]


class SettingsDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window | None,
        config: AppConfig,
        paths: AppPaths,
        db: sqlite3.Connection,
    ) -> None:
        super().__init__(parent, title="Settings", size=(520, 520))
        self._config = config
        self._paths = paths
        self._db = db
        self._identities = IdentityRepository(db)

        panel = self  # parent content on the dialog so CreateButtonSizer matches
        notebook = wx.Notebook(panel)
        notebook.AddPage(self._general_page(notebook), "General")
        notebook.AddPage(self._security_page(notebook), "Security")
        notebook.AddPage(self._signatures_page(notebook), "Signatures")

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(notebook, 1, wx.EXPAND | wx.ALL, 8)
        outer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(outer)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)

    # -- pages --------------------------------------------------------------
    def _general_page(self, parent: wx.Window) -> wx.Window:
        page = wx.Panel(parent)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        self._theme = wx.Choice(page, choices=[t.title() for t in _THEMES])
        self._theme.SetSelection(
            _THEMES.index(self._config.theme) if self._config.theme in _THEMES else 0
        )
        labeled_row(page, grid, "&Theme:", self._theme)

        self._interval = wx.SpinCtrl(
            page, min=0, max=86400, initial=self._config.sync.interval_seconds
        )
        labeled_row(page, grid, "Sync &interval (seconds):", self._interval)

        self._jobs = wx.SpinCtrl(
            page, min=1, max=32, initial=self._config.sync.max_concurrent_jobs
        )
        labeled_row(page, grid, "Max concurrent &jobs:", self._jobs)

        self._auto_sync = wx.CheckBox(page, label="Check for new mail &automatically")
        self._auto_sync.SetValue(self._config.sync.auto_sync)
        self._notify = wx.CheckBox(page, label="Show a &notification when new mail arrives")
        self._notify.SetValue(self._config.ui.show_notifications)
        self._tray = wx.CheckBox(page, label="&Close to the system tray instead of exiting")
        self._tray.SetValue(self._config.ui.minimize_to_tray)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)
        for box in (self._auto_sync, self._notify, self._tray):
            sizer.Add(box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        page.SetSizer(sizer)
        return page

    def _security_page(self, parent: wx.Window) -> wx.Window:
        page = wx.Panel(parent)
        self._enforce_tls = wx.CheckBox(page, label="Enforce &TLS for all connections")
        self._block_remote = wx.CheckBox(page, label="Block &remote content in messages")
        self._sanitize = wx.CheckBox(page, label="&Sanitize HTML before rendering")
        self._enforce_tls.SetValue(self._config.security.enforce_tls)
        self._block_remote.SetValue(self._config.security.block_remote_content)
        self._sanitize.SetValue(self._config.security.sanitize_html)

        sizer = wx.BoxSizer(wx.VERTICAL)
        for box in (self._enforce_tls, self._block_remote, self._sanitize):
            sizer.Add(box, 0, wx.ALL, 10)
        page.SetSizer(sizer)
        return page

    def _signatures_page(self, parent: wx.Window) -> wx.Window:
        page = wx.Panel(parent)
        self._sig_accounts = AccountRepository(self._db).list()
        self._account_choice = wx.Choice(page, choices=[a.email for a in self._sig_accounts])
        accessible_name(self._account_choice, "Account")
        self._signature = wx.TextCtrl(page, style=wx.TE_MULTILINE)
        accessible_name(self._signature, "Signature")
        self._account_choice.Bind(wx.EVT_CHOICE, lambda _e: self._load_signature())
        if self._sig_accounts:
            self._account_choice.SetSelection(0)
            self._load_signature()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(page, label="&Account:"), 0, wx.ALL, 8)
        sizer.Add(self._account_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        sizer.Add(wx.StaticText(page, label="Si&gnature:"), 0, wx.ALL, 8)
        sizer.Add(self._signature, 1, wx.EXPAND | wx.ALL, 8)
        page.SetSizer(sizer)
        return page

    def _current_identity(self):  # type: ignore[no-untyped-def]
        index = self._account_choice.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._sig_accounts):
            return None
        account = self._sig_accounts[index]
        return self._identities.default_for_account(account.id) if account.id else None

    def _load_signature(self) -> None:
        identity = self._current_identity()
        self._signature.SetValue(identity.signature if identity else "")

    # -- persistence --------------------------------------------------------
    def on_ok(self, _event: wx.CommandEvent) -> None:
        identity = self._current_identity()
        if identity is not None:
            identity.signature = self._signature.GetValue()
            self._identities.update(identity)

        self._config.theme = _THEMES[self._theme.GetSelection()]
        self._config.sync.interval_seconds = self._interval.GetValue()
        self._config.sync.max_concurrent_jobs = self._jobs.GetValue()
        self._config.sync.auto_sync = self._auto_sync.GetValue()
        self._config.ui.show_notifications = self._notify.GetValue()
        self._config.ui.minimize_to_tray = self._tray.GetValue()
        self._config.security.enforce_tls = self._enforce_tls.GetValue()
        self._config.security.block_remote_content = self._block_remote.GetValue()
        self._config.security.sanitize_html = self._sanitize.GetValue()
        try:
            self._config.save(self._paths.config_file)
        except ConfigError as exc:
            wx.MessageBox(str(exc), "Invalid settings", wx.ICON_ERROR)
            return
        self.EndModal(wx.ID_OK)
