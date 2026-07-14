"""Address-book use-cases: CRUD, autocomplete, and sender collection."""

from __future__ import annotations

import builtins
from email.utils import formataddr
from pathlib import Path

from ..domain.entities import Contact, EmailAddress, Message
from ..infra.repositories import ContactRepository
from .contact_import import ContactImportService, ContactImportSummary


class ContactService:
    def __init__(self, contacts: ContactRepository) -> None:
        self._contacts = contacts

    def list(self) -> builtins.list[Contact]:
        return self._contacts.list()

    def get(self, contact_id: int) -> Contact | None:
        return self._contacts.get(contact_id)

    def add(self, contact: Contact) -> Contact:
        return self._contacts.add(contact)

    def update(self, contact: Contact) -> None:
        self._contacts.update(contact)

    def delete(self, contact_id: int) -> None:
        self._contacts.delete(contact_id)

    def autocomplete(self, prefix: str, *, limit: int = 20) -> builtins.list[str]:
        """Return formatted ``Name <email>`` suggestions for a name/email prefix."""
        prefix = prefix.strip()
        if len(prefix) < 2:
            return []
        return [
            formataddr((name, email))
            for name, email in self._contacts.search(prefix, limit=limit)
        ]

    def import_from(self, path: Path) -> ContactImportSummary:
        """Import contacts from a vCard/CSV/.contact/LDIF file (kind auto-detected)."""
        from ..infra.contact_importers import build_contact_importer

        importer = build_contact_importer(path)
        return ContactImportService(self._contacts).import_contacts(importer)

    def collect_sender(self, message: Message) -> Contact | None:
        """Add the message's sender to the address book if not already present.

        Returns the new contact, or None if the address was empty or known.
        """
        address = message.from_addr.strip()
        if not address or self._contacts.find_by_email(address) is not None:
            return None
        name = message.from_name.strip() or address
        return self._contacts.add(
            Contact(id=None, display_name=name, emails=[EmailAddress(address, name)])
        )
