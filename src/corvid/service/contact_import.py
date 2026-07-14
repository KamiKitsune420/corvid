"""Import contacts from an address-book file into the local address book.

Deduplicates against existing contacts by email address so re-importing the same
file does not create duplicates. Contacts with no email are always added.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..infra.contact_importers.base import ContactImporter
from ..infra.repositories import ContactRepository

log = logging.getLogger("corvid.contact_import")


@dataclass(slots=True)
class ContactImportSummary:
    imported: int = 0
    skipped: int = 0


class ContactImportService:
    def __init__(self, contacts: ContactRepository) -> None:
        self._contacts = contacts

    def import_contacts(self, importer: ContactImporter) -> ContactImportSummary:
        summary = ContactImportSummary()
        for contact in importer.contacts():
            if any(self._contacts.find_by_email(e.address) for e in contact.emails):
                summary.skipped += 1
                continue
            self._contacts.add(contact)
            summary.imported += 1
        log.info(
            "contact import: %d added, %d already present",
            summary.imported,
            summary.skipped,
        )
        return summary
