"""Message preview pane: header, sanitized HTML/plain body, and attachments.

The body renders in a ``wx.html2.WebView`` (Edge) when available, because unlike
``wx.html.HtmlWindow`` its content is exposed to screen readers — NVDA reads the
message with browse mode and the arrow keys. It's fed only sanitized markup
(scripts removed, remote content blocked); link clicks are intercepted and opened
in the system browser rather than navigating in-pane. Falls back to HtmlWindow if
no WebView backend is present.
"""

from __future__ import annotations

import logging
import tempfile
import webbrowser
from collections.abc import Callable
from html import escape
from pathlib import Path

import wx
import wx.html

from ..htmlsanitize import html_to_text, sanitize_html
from ..infra.mail.parsing import ParsedAttachment, ParsedMessage
from .accessibility import accessible_name

try:
    import wx.html2 as _html2
except ImportError:  # pragma: no cover - html2 ships with wxPython
    _html2 = None  # type: ignore[assignment]

log = logging.getLogger("corvid.ui.preview")

_EXTERNAL = ("http://", "https://", "mailto:")
_BACK_URL = "corvid:back"

# Injected into every rendered page so pressing Escape inside the WebView (where
# wx accelerators don't reach) reaches the app. The sentinel-URL navigation is
# the reliable channel (intercepted and vetoed, so the page never actually
# leaves); postMessage is a harmless extra where it happens to be wired up. Both
# funnel to _exit_reading, which is idempotent, so firing twice is fine.
_ESCAPE_JS = (
    "<script>document.addEventListener('keydown',function(e){"
    "if(e.key==='Escape'){e.preventDefault();"
    "try{if(window.corvid&&window.corvid.postMessage){window.corvid.postMessage('escape');}}"
    "catch(err){}"
    "window.location.href='corvid:back';}"
    "},true);</script>"
)


class _BodyHtmlWindow(wx.html.HtmlWindow):
    """Fallback renderer that opens clicked links externally."""

    def OnLinkClicked(self, link: wx.html.HtmlLinkInfo) -> None:
        href = link.GetHref()
        if href.lower().startswith(_EXTERNAL):
            webbrowser.open(href)


class PreviewPanel(wx.Panel):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        self._block_remote = True
        self._attachments: list[ParsedAttachment] = []
        self._webview = None
        self._on_escape: Callable[[], None] | None = None
        self._last_page = ""  # last markup rendered, for refresh() after occlusion

        self._body = self._make_body()
        accessible_name(self._body, "Message")

        # Attachments bar (hidden when there are none).
        self._attach_list = wx.ListBox(self, style=wx.LB_SINGLE)
        accessible_name(self._attach_list, "Attachments")
        save_btn = wx.Button(self, label="&Save")
        open_btn = wx.Button(self, label="&Open")
        save_btn.Bind(wx.EVT_BUTTON, self.on_save)
        open_btn.Bind(wx.EVT_BUTTON, self.on_open)
        self._attach_bar = wx.BoxSizer(wx.HORIZONTAL)
        self._attach_bar.Add(
            wx.StaticText(self, label="Attachments:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6
        )
        self._attach_bar.Add(self._attach_list, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._attach_bar.Add(save_btn, 0, wx.RIGHT, 4)
        self._attach_bar.Add(open_btn, 0)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self._body, 1, wx.EXPAND)
        outer.Add(self._attach_bar, 0, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(outer)
        self._show_attachments(False)
        self.clear()

    def _make_body(self) -> wx.Window:
        if _html2 is not None and _html2.WebView.IsBackendAvailable(
            _html2.WebViewBackendEdge
        ):
            try:
                view = _html2.WebView.New(self, backend=_html2.WebViewBackendEdge)
                view.EnableContextMenu(False)
                view.Bind(_html2.EVT_WEBVIEW_NAVIGATING, self._on_navigating)
                # Preferred Escape channel: JS posts a message, no navigation.
                try:
                    view.AddScriptMessageHandler("corvid")
                    view.Bind(
                        _html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED,
                        self._on_script_message,
                    )
                except Exception:  # noqa: BLE001 - fall back to the sentinel URL
                    pass
                self._webview = view
                return view
            except Exception:  # noqa: BLE001 - fall back to HtmlWindow on any failure
                self._webview = None
        return _BodyHtmlWindow(self, style=wx.html.HW_SCROLLBAR_AUTO)

    def _on_script_message(self, event: wx.Event) -> None:
        if event.GetString() == "escape" and self._on_escape is not None:  # type: ignore[attr-defined]
            self._on_escape()

    def _on_navigating(self, event: wx.Event) -> None:
        # The sentinel URL is the Escape fallback; links open externally; internal
        # SetPage loads are left alone.
        url = event.GetURL()  # type: ignore[attr-defined]
        if url == _BACK_URL:
            event.Veto()  # type: ignore[attr-defined]
            if self._on_escape is not None:
                wx.CallAfter(self._on_escape)
        elif url.lower().startswith(_EXTERNAL):
            event.Veto()  # type: ignore[attr-defined]
            webbrowser.open(url)

    @staticmethod
    def _document(inner: str) -> str:
        """Wrap a body fragment in a proper HTML5 document.

        The doctype/charset/lang make Edge render in standards mode and expose a
        real document, so NVDA switches to browse mode (silencing the generic
        "grouping" container announcements) and reads the message linearly.
        """
        return (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            "<title>Message</title>"  # without this NVDA announces the URL ("about:blank")
            "<style>body{font-family:'Segoe UI',sans-serif;font-size:12pt;margin:8px;}"
            "p{margin:.2em 0;}</style></head><body>" + inner + "</body></html>"
        )

    def _set_page(self, html: str) -> None:
        if self._webview is not None:
            # Inject the Escape listener inside the body so it runs in the document.
            if "</body>" in html:
                html = html.replace("</body>", _ESCAPE_JS + "</body>", 1)
            else:
                html += _ESCAPE_JS
            self._last_page = html
            self._body.SetPage(html, "")  # type: ignore[call-arg]
        else:
            self._body.SetPage(html)  # type: ignore[attr-defined]

    def refresh(self) -> None:
        """Re-render the current page.

        Edge WebView2 sometimes paints blank after the window is occluded and
        restored (e.g. Alt+Tab away and back). Re-setting the same markup forces
        a repaint; harmless for the HtmlWindow fallback.
        """
        if self._webview is not None and self._last_page:
            self._body.SetPage(self._last_page, "")  # type: ignore[call-arg]

    def set_block_remote(self, block: bool) -> None:
        self._block_remote = block

    def set_escape_handler(self, handler: Callable[[], None]) -> None:
        """Called when Escape is pressed while the message body has focus."""
        self._on_escape = handler

    def focus_body(self) -> None:
        """Move keyboard focus to the message text so it can be read with arrows."""
        self._body.SetFocus()

    # -- rendering ----------------------------------------------------------
    def clear(self) -> None:
        self._set_page(self._document(""))
        self._attachments = []
        self._attach_list.Clear()
        self._show_attachments(False)

    def show_html(self, body_fragment: str) -> None:
        """Render a trusted internal body fragment (e.g. the first-run welcome)."""
        self._attachments = []
        self._attach_list.Clear()
        self._show_attachments(False)
        self._set_page(self._document(body_fragment))

    def show_loading(self, header_html: str) -> None:
        self._attachments = []
        self._attach_list.Clear()
        self._show_attachments(False)
        self._set_page(
            self._document(f"{header_html}<p><i>Downloading message…</i></p>")
        )

    def show(self, header_html: str, body: ParsedMessage) -> None:
        if body.html:
            result = sanitize_html(body.html, block_remote=self._block_remote)
            body_html = result.html
            if result.remote_blocked:
                body_html = (
                    '<p><small>[Remote content blocked. It can be enabled in '
                    "Settings &rarr; Security.]</small></p>" + body_html
                )
        else:
            text = body.text or html_to_text(body.html)
            body_html = f"<pre>{escape(text)}</pre>"

        self._set_page(self._document(f"{header_html}<hr/>{body_html}"))

        self._attachments = [a for a in body.attachments if not a.is_inline]
        self._attach_list.Set([f"{a.filename} ({a.size} bytes)" for a in self._attachments])
        self._show_attachments(bool(self._attachments))
        if self._attachments:
            self._attach_list.SetSelection(0)

    def _show_attachments(self, visible: bool) -> None:
        self._attach_bar.ShowItems(visible)
        self.Layout()

    # -- attachment actions -------------------------------------------------
    def _selected_attachment(self) -> ParsedAttachment | None:
        index = self._attach_list.GetSelection()
        return self._attachments[index] if index != wx.NOT_FOUND else None

    def on_save(self, _event: wx.CommandEvent) -> None:
        attachment = self._selected_attachment()
        if attachment is None:
            return
        with wx.FileDialog(
            self,
            "Save attachment",
            defaultFile=attachment.filename,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            try:
                Path(dialog.GetPath()).write_bytes(attachment.payload)
            except OSError as exc:
                wx.MessageBox(str(exc), "Could not save attachment", wx.ICON_ERROR)

    def on_open(self, _event: wx.CommandEvent) -> None:
        attachment = self._selected_attachment()
        if attachment is None:
            return
        # Write to a temp file and hand off to the OS default application.
        safe_name = Path(attachment.filename).name or "attachment"
        target = Path(tempfile.gettempdir()) / "corvid_attachments" / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(attachment.payload)
        except OSError as exc:
            wx.MessageBox(str(exc), "Could not open attachment", wx.ICON_ERROR)
            return
        if not wx.LaunchDefaultApplication(str(target)):
            webbrowser.open(target.as_uri())
