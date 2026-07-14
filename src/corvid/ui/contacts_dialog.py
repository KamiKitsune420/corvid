"""Address book: contact list, editor, and a picker mode for the composer."""

from __future__ import annotations

import wx

from ..domain.entities import Contact, EmailAddress
from ..service.contacts import ContactService
from .accessibility import accessible_name, labeled_row


def _primary_email(contact: Contact) -> str:
    return contact.emails[0].address if contact.emails else ""


class ContactEditDialog(wx.Dialog):
    """Create or edit a single contact."""

    def __init__(self, parent: wx.Window | None, contact: Contact) -> None:
        title = "Edit Contact" if contact.id is not None else "New Contact"
        super().__init__(parent, title=title, size=(420, 380))
        self._contact = contact
        panel = self  # parent content on the dialog so CreateButtonSizer matches
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1, 1)

        self._name = labeled_row(panel, grid, "&Display name:", wx.TextCtrl(panel))
        self._first = labeled_row(panel, grid, "&First name:", wx.TextCtrl(panel))
        self._last = labeled_row(panel, grid, "&Last name:", wx.TextCtrl(panel))
        self._org = labeled_row(panel, grid, "&Organization:", wx.TextCtrl(panel))
        self._name.SetValue(contact.display_name)
        self._first.SetValue(contact.first_name)
        self._last.SetValue(contact.last_name)
        self._org.SetValue(contact.organization)

        emails_label = wx.StaticText(panel, label="&Email addresses (one per line):")
        self._emails = wx.TextCtrl(panel, style=wx.TE_MULTILINE)
        accessible_name(self._emails, "Email addresses, one per line")
        self._emails.SetValue("\n".join(e.address for e in contact.emails))

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(emails_label, 0, wx.LEFT | wx.TOP, 10)
        outer.Add(self._emails, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(outer)
        self._name.SetFocus()

    def get_contact(self) -> Contact:
        self._contact.display_name = self._name.GetValue().strip() or "(no name)"
        self._contact.first_name = self._first.GetValue().strip()
        self._contact.last_name = self._last.GetValue().strip()
        self._contact.organization = self._org.GetValue().strip()
        self._contact.emails = [
            EmailAddress(address=line.strip(), name=self._contact.display_name)
            for line in self._emails.GetValue().splitlines()
            if line.strip()
        ]
        return self._contact


class ContactsDialog(wx.Dialog):
    """Browse/manage contacts; in ``pick`` mode, select addresses for a message."""

    def __init__(
        self, parent: wx.Window | None, service: ContactService, *, pick: bool = False
    ) -> None:
        super().__init__(parent, title="Address Book", size=(420, 480))
        self._service = service
        self._pick = pick
        self.picked: list[str] = []
        panel = self  # parent content on the dialog so CreateButtonSizer matches

        self._list = wx.ListBox(
            panel, style=wx.LB_SINGLE | (wx.LB_EXTENDED if pick else 0)
        )
        accessible_name(self._list, "Contacts")
        self._list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_activate)

        new_btn = wx.Button(panel, label="&New")
        edit_btn = wx.Button(panel, label="&Edit")
        del_btn = wx.Button(panel, label="De&lete")
        import_btn = wx.Button(panel, label="&Import...")
        new_btn.Bind(wx.EVT_BUTTON, self.on_new)
        edit_btn.Bind(wx.EVT_BUTTON, self.on_edit)
        del_btn.Bind(wx.EVT_BUTTON, self.on_delete)
        import_btn.Bind(wx.EVT_BUTTON, self.on_import)
        side = wx.BoxSizer(wx.VERTICAL)
        for btn in (new_btn, edit_btn, del_btn, import_btn):
            side.Add(btn, 0, wx.EXPAND | wx.BOTTOM, 6)

        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(self._list, 1, wx.EXPAND | wx.RIGHT, 8)
        body.Add(side, 0)

        flags = wx.OK | wx.CANCEL if pick else wx.CLOSE
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(body, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.CreateButtonSizer(flags), 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(outer)
        if not pick:
            self.Bind(wx.EVT_BUTTON, lambda _e: self.Close(), id=wx.ID_CLOSE)
        else:
            self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)

        self._contacts: list[Contact] = []
        self._reload()

    def _reload(self) -> None:
        self._contacts = self._service.list()
        self._list.Set(
            [f"{c.display_name} <{_primary_email(c)}>" for c in self._contacts]
        )

    def _selected(self) -> Contact | None:
        index = self._list.GetSelection()
        return self._contacts[index] if index != wx.NOT_FOUND else None

    # -- events -------------------------------------------------------------
    def on_activate(self, _event: wx.CommandEvent) -> None:
        if self._pick:
            self.on_ok(_event)
        else:
            self.on_edit(_event)

    def on_new(self, _event: wx.CommandEvent) -> None:
        dialog = ContactEditDialog(self, Contact(id=None, display_name=""))
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self._service.add(dialog.get_contact())
                self._reload()
        finally:
            dialog.Destroy()

    def on_edit(self, _event: wx.CommandEvent) -> None:
        contact = self._selected()
        if contact is None:
            return
        dialog = ContactEditDialog(self, contact)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self._service.update(dialog.get_contact())
                self._reload()
        finally:
            dialog.Destroy()

    def on_import(self, _event: wx.CommandEvent) -> None:
        from pathlib import Path

        with wx.FileDialog(
            self,
            "Import contacts",
            wildcard=(
                "Contact files (*.vcf;*.csv;*.contact;*.ldif;*.wab)"
                "|*.vcf;*.csv;*.contact;*.ldif;*.wab|All files (*.*)|*.*"
            ),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            with wx.BusyCursor():
                summary = self._service.import_from(path)
        except Exception as exc:  # noqa: BLE001 - show the reason (e.g. .wab guidance)
            wx.MessageBox(
                getattr(exc, "user_message", str(exc)), "Import failed",
                wx.OK | wx.ICON_WARNING,
            )
            return
        self._reload()
        wx.MessageBox(
            f"Imported {summary.imported} contact(s); "
            f"{summary.skipped} already present.",
            "Import complete", wx.OK | wx.ICON_INFORMATION,
        )

    def on_delete(self, _event: wx.CommandEvent) -> None:
        contact = self._selected()
        if contact is None or contact.id is None:
            return
        if wx.MessageBox(
            f"Delete {contact.display_name}?", "Confirm", wx.YES_NO | wx.ICON_QUESTION
        ) == wx.YES:
            self._service.delete(contact.id)
            self._reload()

    def on_ok(self, _event: wx.CommandEvent) -> None:
        self.picked = [
            f"{self._contacts[i].display_name} <{_primary_email(self._contacts[i])}>"
            for i in self._list.GetSelections()
            if _primary_email(self._contacts[i])
        ]
        self.EndModal(wx.ID_OK)
