"""Collect the account password after the details are entered.

For providers that require an **app password** (Gmail, Outlook, Yahoo, ...), this
explains that the normal account password won't work, offers a button that opens
the provider's app-password page in the browser, and takes the generated password
in the box below. For everything else it's a plain password prompt.
"""

from __future__ import annotations

import webbrowser

import wx

from .accessibility import accessible_name


class CredentialsDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window | None,
        *,
        email: str,
        provider_name: str,
        help_url: str,
        app_password: bool,
    ) -> None:
        super().__init__(parent, title="Account Password", size=(460, 300))
        self._app_password = app_password
        outer = wx.BoxSizer(wx.VERTICAL)

        if app_password and help_url:
            who = provider_name or "this provider"
            intro = wx.StaticText(
                self,
                label=(
                    f"To use Corvid with {who}, you need an App Password — not your "
                    f"normal {who} password.\n\nClick below to open the App Password "
                    f"page, create one, then paste it here."
                ),
            )
            intro.Wrap(420)
            outer.Add(intro, 0, wx.ALL, 12)
            open_btn = wx.Button(self, label="&Open the App Password page")
            open_btn.Bind(wx.EVT_BUTTON, lambda _e: webbrowser.open(help_url))
            outer.Add(open_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            field_label = "Paste the App Password:"
        else:
            outer.Add(
                wx.StaticText(self, label=f"Enter the password for {email}:"),
                0, wx.ALL, 12,
            )
            field_label = "Password:"

        outer.Add(wx.StaticText(self, label=field_label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self._pw = wx.TextCtrl(self, style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER)
        accessible_name(self._pw, field_label)
        self._pw.Bind(wx.EVT_TEXT_ENTER, lambda _e: self.EndModal(wx.ID_OK))
        outer.Add(self._pw, 0, wx.EXPAND | wx.ALL, 12)

        outer.AddStretchSpacer()
        outer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)
        self._pw.SetFocus()

    def get_password(self) -> str:
        value = self._pw.GetValue()
        # App passwords are shown grouped with spaces (e.g. "abcd efgh ijkl mnop");
        # the spaces are cosmetic, so strip all whitespace.
        return "".join(value.split()) if self._app_password else value
