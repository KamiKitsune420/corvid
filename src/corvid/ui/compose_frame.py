"""Message composer window (plain text + HTML modes, attachments)."""

from __future__ import annotations

import logging
from collections.abc import Callable

import wx

from ..domain.compose import DraftMessage, parse_address_list
from .accessibility import accessible_name

log = logging.getLogger("corvid.ui.compose")

SendCallback = Callable[[DraftMessage], None]
SaveDraftCallback = Callable[[DraftMessage], None]
CompleterLookup = Callable[[str], list[str]]
PickContacts = Callable[[], list[str]]


class ContactCompleter(wx.TextCompleter):
    """Autocompletes the recipient currently being typed (the token after the
    last comma), leaving already-entered recipients intact."""

    def __init__(self, lookup: CompleterLookup) -> None:
        super().__init__()
        self._lookup = lookup
        self._matches: list[str] = []
        self._index = 0

    def Start(self, prefix: str) -> bool:
        head, _, last = prefix.rpartition(",")
        token = last.strip()
        if len(token) < 2:
            return False
        preamble = f"{head.strip()}, " if head.strip() else ""
        self._matches = [preamble + suggestion for suggestion in self._lookup(token)]
        self._index = 0
        return bool(self._matches)

    def GetNext(self) -> str:
        if self._index >= len(self._matches):
            return ""
        value = self._matches[self._index]
        self._index += 1
        return value


class ComposeFrame(wx.Frame):
    """A standalone compose window.

    Send/save are injected as callbacks so this widget stays decoupled from the
    service wiring (and from worker-thread connection handling in the caller).
    """

    def __init__(
        self,
        parent: wx.Window | None,
        draft: DraftMessage,
        *,
        on_send: SendCallback,
        on_save_draft: SaveDraftCallback | None = None,
        completer_lookup: CompleterLookup | None = None,
        pick_contacts: PickContacts | None = None,
    ) -> None:
        super().__init__(parent, title="New Message", size=(720, 560))
        self._draft = draft
        self._on_send = on_send
        self._on_save_draft = on_save_draft
        self._pick_contacts = pick_contacts
        self._attachments: list[str] = list(draft.attachments)

        panel = wx.Panel(self)
        self._to = wx.TextCtrl(panel, value=", ".join(draft.to))
        self._cc = wx.TextCtrl(panel, value=", ".join(draft.cc))
        self._subject = wx.TextCtrl(panel, value=draft.subject)
        if completer_lookup is not None:
            self._to.AutoComplete(ContactCompleter(completer_lookup))
            self._cc.AutoComplete(ContactCompleter(completer_lookup))
        self._html_mode = wx.CheckBox(panel, label="HTML")
        self._html_mode.SetValue(bool(draft.body_html))
        self._body = wx.TextCtrl(
            panel, value=draft.body_html or draft.body_text, style=wx.TE_MULTILINE
        )
        self._attach_label = wx.StaticText(panel, label="")
        self._update_attach_label()

        form = wx.FlexGridSizer(cols=2, vgap=4, hgap=8)
        form.AddGrowableCol(1, 1)
        for label, ctrl in (
            ("&To:", self._to),
            ("&Cc:", self._cc),
            ("Subjec&t:", self._subject),
        ):
            form.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            accessible_name(ctrl, label)
            form.Add(ctrl, 1, wx.EXPAND)
        accessible_name(self._body, "Message body")

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        send_btn = wx.Button(panel, label="&Send")
        attach_btn = wx.Button(panel, label="&Attach...")
        save_btn = wx.Button(panel, label="Save &Draft")
        send_btn.Bind(wx.EVT_BUTTON, self.on_send)
        attach_btn.Bind(wx.EVT_BUTTON, self.on_attach)
        save_btn.Bind(wx.EVT_BUTTON, self.on_save_draft)
        widgets: list[wx.Window] = [send_btn, attach_btn, save_btn, self._html_mode]
        if self._pick_contacts is not None:
            book_btn = wx.Button(panel, label="Address &Book...")
            book_btn.Bind(wx.EVT_BUTTON, self.on_address_book)
            widgets.insert(2, book_btn)
        for widget in widgets:
            toolbar.Add(widget, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(toolbar, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(form, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self._attach_label, 0, wx.LEFT | wx.BOTTOM, 8)
        outer.Add(self._body, 1, wx.EXPAND | wx.ALL, 6)
        panel.SetSizer(outer)
        save_btn.Enable(self._on_save_draft is not None)

    # -- helpers ------------------------------------------------------------
    def _update_attach_label(self) -> None:
        if self._attachments:
            names = ", ".join(p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in self._attachments)
            self._attach_label.SetLabel(f"Attachments: {names}")
        else:
            self._attach_label.SetLabel("")

    def _collect(self) -> DraftMessage:
        body = self._body.GetValue()
        is_html = self._html_mode.GetValue()
        self._draft.to = parse_address_list(self._to.GetValue())
        self._draft.cc = parse_address_list(self._cc.GetValue())
        self._draft.subject = self._subject.GetValue()
        self._draft.body_text = "" if is_html else body
        self._draft.body_html = body if is_html else ""
        self._draft.attachments = list(self._attachments)
        return self._draft

    # -- events -------------------------------------------------------------
    def on_address_book(self, _event: wx.CommandEvent) -> None:
        if self._pick_contacts is None:
            return
        picked = self._pick_contacts()
        if not picked:
            return
        existing = parse_address_list(self._to.GetValue())
        merged = existing + [p for p in picked if p not in existing]
        self._to.SetValue(", ".join(merged))

    def on_attach(self, _event: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self, "Choose attachments", style=wx.FD_OPEN | wx.FD_MULTIPLE
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self._attachments.extend(dialog.GetPaths())
                self._update_attach_label()

    def on_send(self, _event: wx.CommandEvent) -> None:
        draft = self._collect()
        if not draft.to:
            wx.MessageBox("Please specify at least one recipient.", "Send", wx.ICON_WARNING)
            return
        try:
            self._on_send(draft)
        except Exception as exc:  # noqa: BLE001 - surface send failures to the user
            wx.MessageBox(str(exc), "Could not send message", wx.ICON_ERROR)
            return
        self.Close()

    def on_save_draft(self, _event: wx.CommandEvent) -> None:
        if self._on_save_draft is None:
            return
        try:
            self._on_save_draft(self._collect())
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(str(exc), "Could not save draft", wx.ICON_ERROR)
            return
        self.SetTitle("New Message (draft saved)")
