"""Importers for address-book files (vCard, CSV, Windows Address Book)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from .base import ContactImporter
from .contact_xml import ContactXmlImporter
from .csv_contacts import CsvContactImporter
from .ldif import LdifImporter
from .vcard import VcardImporter
from .wab import WabImporter


class ContactSourceKind(StrEnum):
    VCARD = "vcard"
    CSV = "csv"
    CONTACT_XML = "contact"
    LDIF = "ldif"
    WAB = "wab"


def detect_contact_kind(path: Path) -> ContactSourceKind:
    if path.is_dir():
        return ContactSourceKind.CONTACT_XML  # a folder of .contact files
    suffix = path.suffix.lower()
    if suffix in (".vcf", ".vcard"):
        return ContactSourceKind.VCARD
    if suffix == ".contact":
        return ContactSourceKind.CONTACT_XML
    if suffix in (".ldif", ".ldf"):
        return ContactSourceKind.LDIF
    if suffix == ".wab":
        return ContactSourceKind.WAB
    return ContactSourceKind.CSV


def build_contact_importer(
    path: Path, kind: ContactSourceKind | None = None
) -> ContactImporter:
    resolved = kind or detect_contact_kind(path)
    if resolved is ContactSourceKind.VCARD:
        return VcardImporter(path)
    if resolved is ContactSourceKind.CONTACT_XML:
        return ContactXmlImporter(path)
    if resolved is ContactSourceKind.LDIF:
        return LdifImporter(path)
    if resolved is ContactSourceKind.WAB:
        return WabImporter(path)
    return CsvContactImporter(path)


__all__ = [
    "ContactImporter",
    "ContactSourceKind",
    "VcardImporter",
    "CsvContactImporter",
    "ContactXmlImporter",
    "LdifImporter",
    "WabImporter",
    "detect_contact_kind",
    "build_contact_importer",
]
