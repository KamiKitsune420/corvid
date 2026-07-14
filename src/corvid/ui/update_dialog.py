"""Check-for-updates dialog: query GitHub Releases and download the installer.

The network check and download run on background threads, marshaling results
back to the UI with ``wx.CallAfter``. The status is a read-only multiline text
control (not a static label) so NVDA reads each state change in browse mode, and
every control carries an explicit accessible name. Escape closes the dialog.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import wx

from ..domain.updates import UpdateInfo
from ..errors import CorvidError
from ..service.updates import UpdateService
from .accessibility import accessible_name


class UpdateDialog(wx.Dialog):
    def __init__(
        self, parent: wx.Window, service: UpdateService, dest_dir: Path
    ) -> None:
        super().__init__(parent, title="Check for Updates", size=(520, 360))
        self._service = service
        self._dest_dir = dest_dir
        self._update: UpdateInfo | None = None
        self._busy = False

        current = service.current_version
        self._status = wx.TextCtrl(
            self,
            value=f"Current version: {current}\n\nChecking for updates…",
            style=wx.TE_READONLY | wx.TE_MULTILINE | wx.TE_WORDWRAP,
        )
        accessible_name(self._status, "Update status")

        self._gauge = wx.Gauge(self, range=100)
        accessible_name(self._gauge, "Download progress")
        self._gauge.Hide()

        self._download_btn = wx.Button(self, label="&Download Update")
        self._download_btn.Hide()
        self._download_btn.Bind(wx.EVT_BUTTON, self._on_download)
        self._close_btn = wx.Button(self, wx.ID_CLOSE, "&Close")
        self._close_btn.Bind(wx.EVT_BUTTON, lambda _e: self.EndModal(wx.ID_CLOSE))

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(self._download_btn, 0, wx.RIGHT, 8)
        buttons.Add(self._close_btn, 0)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self._status, 1, wx.EXPAND | wx.ALL, 12)
        outer.Add(self._gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        self.SetSizer(outer)
        self.CentreOnParent()

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        threading.Thread(target=self._check, daemon=True).start()

    # -- check -------------------------------------------------------------
    def _check(self) -> None:
        try:
            update = self._service.check_for_updates()
        except CorvidError as exc:
            wx.CallAfter(self._on_checked, None, exc)
        else:
            wx.CallAfter(self._on_checked, update, None)

    def _on_checked(
        self, update: UpdateInfo | None, error: CorvidError | None
    ) -> None:
        current = self._service.current_version
        if error is not None:
            self._status.SetValue(f"Current version: {current}\n\n{error.user_message}")
            self._close_btn.SetFocus()
        elif update is not None:
            self._update = update
            text = (
                f"Current version: {current}\n"
                f"New version available: {update.version}\n"
            )
            if update.release_notes:
                text += f"\nRelease notes:\n{update.release_notes}"
            self._status.SetValue(text)
            self._download_btn.Show()
            self.Layout()
            self._download_btn.SetFocus()
        else:
            self._status.SetValue(f"Current version: {current}\n\nYou are up to date.")
            self._status.SetFocus()

    # -- download ----------------------------------------------------------
    def _on_download(self, _event: wx.CommandEvent) -> None:
        update = self._update
        if update is None or self._busy:
            return
        self._busy = True
        self._download_btn.Disable()
        self._gauge.SetValue(0)
        self._gauge.Show()
        self.Layout()

        def _progress(done: int, total: int) -> None:
            if total > 0:
                wx.CallAfter(self._gauge.SetValue, int(done * 100 / total))
            else:
                wx.CallAfter(self._gauge.Pulse)

        def _run() -> None:
            try:
                path = self._service.download(
                    update, self._dest_dir, progress_cb=_progress
                )
            except CorvidError as exc:
                wx.CallAfter(self._on_downloaded, None, exc)
            else:
                wx.CallAfter(self._on_downloaded, path, None)

        threading.Thread(target=_run, daemon=True).start()

    def _on_downloaded(self, path: Path | None, error: CorvidError | None) -> None:
        self._busy = False
        self._gauge.Hide()
        self.Layout()
        if error is not None or path is None:
            reason = error.user_message if error else "The update could not be downloaded."
            self._status.SetValue(f"Download failed.\n\n{reason}\n\nPlease try again.")
            self._download_btn.Enable()
            self._download_btn.SetFocus()
            return
        how_to = (
            "To install: close Corvid, then run the downloaded installer and "
            "follow the prompts. Your accounts, mail, and settings are kept."
        )
        self._status.SetValue(f"Download complete.\n\nSaved to: {path}\n\n{how_to}")
        self._close_btn.SetFocus()
        self._reveal(path)

    # -- helpers -----------------------------------------------------------
    def _reveal(self, path: Path) -> None:
        """Open Explorer with the downloaded file selected (best effort)."""
        try:
            subprocess.Popen(["explorer", f"/select,{path}"])  # noqa: S603, S607
        except OSError:
            pass

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CLOSE)
            return
        event.Skip()
