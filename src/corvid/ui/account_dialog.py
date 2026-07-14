"""'Add Account' dialog.

Beginner-first: you normally type only display name, email, and password — the
server settings are auto-detected from the email domain (see
``infra.autodiscovery``) and kept out of sight under "Advanced". If a provider
needs an **app password** (Gmail, Outlook, Yahoo, ...), a help link appears.
Username defaults to the email and lives under Advanced for the rare server that
needs a separate login. News (NNTP) accounts show their server field directly,
since news has no autodiscovery.
"""

from __future__ import annotations

import threading

import wx

from ..domain.entities import (
    Account,
    AccountKind,
    AuthMethod,
    ConnectionSecurity,
    ReceiveProtocol,
)
from ..infra.autodiscovery import discover, domain_of
from ..infra.oauth import OAuthClient, authorize

_SECURITY_CHOICES = [
    ("TLS/SSL", ConnectionSecurity.TLS),
    ("STARTTLS", ConnectionSecurity.STARTTLS),
    ("None", ConnectionSecurity.NONE),
]
_KIND_CHOICES = [("Mail (IMAP/POP3)", AccountKind.MAIL), ("News (NNTP)", AccountKind.NEWS)]
_RECEIVE_CHOICES = [("IMAP", ReceiveProtocol.IMAP), ("POP3", ReceiveProtocol.POP3)]

# The OAuth "Sign in with Google/Microsoft" button is hidden for now: a verified
# public Google client requires a paid security assessment, so distribution leads
# with app passwords instead. All OAuth code (client, XOAUTH2, config, service)
# stays in place — flip this to True to re-enable the sign-in UI.
_OAUTH_SIGN_IN_ENABLED = False


def _security_index(security: ConnectionSecurity) -> int:
    return next(i for i, (_, s) in enumerate(_SECURITY_CHOICES) if s is security)


class AccountDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window | None,
        *,
        oauth_clients: dict[str, OAuthClient] | None = None,
    ) -> None:
        super().__init__(parent, title="Add Account", size=(480, 560))
        self._oauth_clients = oauth_clients or {}
        self._fields: dict[str, wx.TextCtrl] = {}
        self._username_row: list[wx.Window] = []
        self._receive_row: list[wx.Window] = []
        self._imap_rows: list[wx.Window] = []
        self._pop3_rows: list[wx.Window] = []
        self._smtp_rows: list[wx.Window] = []
        self._nntp_rows: list[wx.Window] = []
        self._last_domain = ""
        self._signin_wanted = False
        self._detected_oauth = ""          # provider key of the detected provider
        self._oauth_refresh_token = ""     # set once the user signs in
        panel = self
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1, 1)

        def row(
            label: str, key: str, default: str = "", *, password: bool = False,
            bucket: list[wx.Window] | None = None,
        ) -> wx.TextCtrl:
            static = wx.StaticText(panel, label=label)
            grid.Add(static, 0, wx.ALIGN_CENTER_VERTICAL)
            ctrl = wx.TextCtrl(panel, value=default, style=wx.TE_PASSWORD if password else 0)
            self._fields[key] = ctrl
            grid.Add(ctrl, 1, wx.EXPAND)
            if bucket is not None:
                bucket.extend((static, ctrl))
            return ctrl

        def choice_row(
            label: str, choices: list[str], default_index: int, bucket: list[wx.Window]
        ) -> wx.Choice:
            static = wx.StaticText(panel, label=label)
            grid.Add(static, 0, wx.ALIGN_CENTER_VERTICAL)
            choice = wx.Choice(panel, choices=choices)
            choice.SetSelection(default_index)
            grid.Add(choice, 1, wx.EXPAND)
            bucket.extend((static, choice))
            return choice

        sec = [c[0] for c in _SECURITY_CHOICES]

        grid.Add(wx.StaticText(panel, label="Account type"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._kind = wx.Choice(panel, choices=[c[0] for c in _KIND_CHOICES])
        self._kind.SetSelection(0)
        self._kind.Bind(wx.EVT_CHOICE, lambda _e: self._sync_visibility())
        grid.Add(self._kind, 1, wx.EXPAND)

        row("Display name", "display_name")
        email = row("Email", "email")
        email.Bind(wx.EVT_KILL_FOCUS, self._on_email)
        # The password is collected afterwards (with app-password guidance) and
        # verified before the account is saved — see CredentialsDialog.

        # Detection status + OAuth sign-in (currently hidden — see account dialog).
        self._status = wx.StaticText(panel, label="")
        self._signin_btn = wx.Button(panel, label="Sign in")
        self._signin_btn.Bind(wx.EVT_BUTTON, self._on_sign_in)
        self._signin_btn.Hide()

        self._advanced = wx.CheckBox(panel, label="Advanced server settings")
        self._advanced.Bind(wx.EVT_CHECKBOX, lambda _e: self._sync_visibility())

        # -- advanced / server rows --
        row("Username", "username", bucket=self._username_row)
        self._receive = choice_row(
            "Receive using", [c[0] for c in _RECEIVE_CHOICES], 0, self._receive_row
        )
        self._receive.Bind(wx.EVT_CHOICE, lambda _e: self._sync_visibility())

        row("IMAP host", "imap_host", bucket=self._imap_rows)
        row("IMAP port", "imap_port", "993", bucket=self._imap_rows)
        self._imap_security = choice_row("IMAP security", sec, 0, self._imap_rows)

        row("POP3 host", "pop3_host", bucket=self._pop3_rows)
        row("POP3 port", "pop3_port", "995", bucket=self._pop3_rows)
        self._pop3_security = choice_row("POP3 security", sec, 0, self._pop3_rows)
        self._leave = wx.CheckBox(panel, label="Leave a copy of messages on the server")
        self._leave.SetValue(True)
        leave_spacer = wx.StaticText(panel, label="")
        grid.Add(leave_spacer, 0)
        grid.Add(self._leave, 0, wx.EXPAND)
        self._pop3_rows.extend((leave_spacer, self._leave))

        row("SMTP host", "smtp_host", bucket=self._smtp_rows)
        row("SMTP port", "smtp_port", "587", bucket=self._smtp_rows)
        self._smtp_security = choice_row("SMTP security", sec, 1, self._smtp_rows)

        row("News (NNTP) host", "nntp_host", bucket=self._nntp_rows)
        row("News port", "nntp_port", "119", bucket=self._nntp_rows)
        self._nntp_security = choice_row("News security", sec, 2, self._nntp_rows)

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)
        outer.Add(self._status, 0, wx.LEFT | wx.RIGHT, 12)
        outer.Add(self._signin_btn, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        outer.Add(self._advanced, 0, wx.ALL, 12)
        outer.AddStretchSpacer()
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(outer)
        self._grid = grid
        self._sync_visibility()

    # -- helpers ------------------------------------------------------------
    def _selected_kind(self) -> AccountKind:
        return _KIND_CHOICES[self._kind.GetSelection()][1]

    def _selected_receive(self) -> ReceiveProtocol:
        return _RECEIVE_CHOICES[self._receive.GetSelection()][1]

    def _value(self, key: str) -> str:
        return self._fields[key].GetValue().strip()

    def _set_security(self, choice: wx.Choice, security: ConnectionSecurity) -> None:
        choice.SetSelection(_security_index(security))

    def _sync_visibility(self) -> None:
        news = self._selected_kind() is AccountKind.NEWS
        adv = self._advanced.GetValue()
        pop3 = self._selected_receive() is ReceiveProtocol.POP3
        for w in self._username_row:
            w.Show((not news and adv) or news)
        for w in self._receive_row:
            w.Show(not news and adv)
        for w in self._smtp_rows:
            w.Show(not news and adv)
        for w in self._imap_rows:
            w.Show(not news and adv and not pop3)
        for w in self._pop3_rows:
            w.Show(not news and adv and pop3)
        for w in self._nntp_rows:
            w.Show(news)
        self._advanced.Show(not news)
        self._status.Show(not news)
        self._signin_btn.Show(not news and self._signin_wanted)
        self._grid.Layout()
        self.Layout()

    # -- autodiscovery ------------------------------------------------------
    def _on_email(self, event: wx.FocusEvent) -> None:
        event.Skip()  # let the field process focus normally
        self._detect()

    def _detect(self) -> None:
        if self._selected_kind() is AccountKind.NEWS:
            return
        domain = domain_of(self._value("email"))
        if "." not in domain or domain == self._last_domain:
            return
        self._last_domain = domain
        settings = discover(domain)
        if settings is None:
            self._status.SetLabel(
                f"Couldn't auto-detect {domain}. Enter your server settings under Advanced."
            )
            self._signin_wanted = False
            self._detected_oauth = ""
            self._advanced.SetValue(True)
            self._sync_visibility()
            return
        self._fields["imap_host"].SetValue(settings.imap_host)
        self._fields["imap_port"].SetValue(str(settings.imap_port))
        self._set_security(self._imap_security, settings.imap_security)
        self._fields["smtp_host"].SetValue(settings.smtp_host)
        self._fields["smtp_port"].SetValue(str(settings.smtp_port))
        self._set_security(self._smtp_security, settings.smtp_security)
        if settings.pop3_host:
            self._fields["pop3_host"].SetValue(settings.pop3_host)
            self._fields["pop3_port"].SetValue(str(settings.pop3_port))
            self._set_security(self._pop3_security, settings.pop3_security)
        self._status.SetLabel(f"✓ Found {settings.name} settings.")
        # Offer OAuth sign-in when enabled, this provider supports it, and a
        # client id is set. Disabled for now (see _OAUTH_SIGN_IN_ENABLED).
        self._detected_oauth = settings.oauth
        self._signin_wanted = (
            _OAUTH_SIGN_IN_ENABLED
            and bool(settings.oauth)
            and settings.oauth in self._oauth_clients
            and not self._oauth_refresh_token
        )
        if self._signin_wanted:
            self._signin_btn.SetLabel(f"Sign in with {settings.name}")
            self._signin_btn.Enable()
        # App-password guidance is shown afterwards in CredentialsDialog, not here.
        self._advanced.SetValue(False)  # detected — keep it tidy
        self._sync_visibility()

    # -- OAuth sign-in ------------------------------------------------------
    def _on_sign_in(self, _event: wx.CommandEvent) -> None:
        client = self._oauth_clients.get(self._detected_oauth)
        if client is None:
            return
        self._signin_btn.Disable()
        self._status.SetLabel(
            "Opening your browser to sign in — approve access, then come back here."
        )

        def work() -> None:
            try:
                tokens = authorize(client)
                wx.CallAfter(self._signin_ok, tokens.refresh_token)
            except Exception as exc:  # noqa: BLE001 - reported back on the UI thread
                wx.CallAfter(self._signin_fail, exc)

        threading.Thread(target=work, daemon=True).start()

    def _signin_ok(self, refresh_token: str) -> None:
        if not refresh_token:
            self._status.SetLabel(
                "Signed in, but no refresh token was returned. Remove Corvid's access "
                "in your account settings and try again."
            )
            self._signin_btn.Enable()
            return
        self._oauth_refresh_token = refresh_token
        self._status.SetLabel("✓ Signed in. Click OK to finish adding the account.")
        self._signin_wanted = False
        self._sync_visibility()

    def _signin_fail(self, exc: Exception) -> None:
        message = getattr(exc, "user_message", str(exc))
        self._status.SetLabel(f"Sign-in failed: {message}")
        self._signin_btn.Enable()

    # -- result -------------------------------------------------------------
    def get_account(self) -> tuple[Account, str]:
        """Return (account, credential).

        The credential is empty for the normal flow (the password is collected and
        verified afterwards); it holds an OAuth refresh token only if sign-in was
        used (currently disabled). Raises ValueError on bad numeric input.
        """
        self._detect()  # ensure settings are filled even if Email never lost focus
        kind = self._selected_kind()
        receive = self._selected_receive()
        account = Account(
            id=None,
            display_name=self._value("display_name") or self._value("email"),
            email=self._value("email"),
            username=self._value("username"),
            imap_host=self._value("imap_host"),
            imap_port=int(self._value("imap_port") or "993"),
            imap_security=_SECURITY_CHOICES[self._imap_security.GetSelection()][1],
            smtp_host=self._value("smtp_host"),
            smtp_port=int(self._value("smtp_port") or "587"),
            smtp_security=_SECURITY_CHOICES[self._smtp_security.GetSelection()][1],
            kind=kind,
            receive_protocol=receive,
            nntp_host=self._value("nntp_host"),
            nntp_port=int(self._value("nntp_port") or "119"),
            nntp_security=_SECURITY_CHOICES[self._nntp_security.GetSelection()][1],
            pop3_host=self._value("pop3_host"),
            pop3_port=int(self._value("pop3_port") or "995"),
            pop3_security=_SECURITY_CHOICES[self._pop3_security.GetSelection()][1],
            pop3_leave_on_server=self._leave.GetValue(),
        )
        if kind is AccountKind.MAIL and not account.username:
            account.username = account.email
        if self._oauth_refresh_token:
            # OAuth account: XOAUTH2 with the email; the stored credential is the
            # refresh token, and there is no password.
            account.auth_method = AuthMethod.OAUTH2
            account.username = account.email
            return account, self._oauth_refresh_token
        return account, ""  # password collected + verified afterwards
