from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from corvid.errors import ValidationError
from corvid.infra.contact_importers import (
    ContactSourceKind,
    ContactXmlImporter,
    CsvContactImporter,
    LdifImporter,
    VcardImporter,
    WabImporter,
    detect_contact_kind,
)
from corvid.infra.repositories import ContactRepository
from corvid.service.contact_import import ContactImportService

# -- detection ---------------------------------------------------------------

def test_detect_contact_kind(tmp_path: Path) -> None:
    assert detect_contact_kind(tmp_path / "x.vcf") is ContactSourceKind.VCARD
    assert detect_contact_kind(tmp_path / "x.vcard") is ContactSourceKind.VCARD
    assert detect_contact_kind(tmp_path / "x.wab") is ContactSourceKind.WAB
    assert detect_contact_kind(tmp_path / "x.contact") is ContactSourceKind.CONTACT_XML
    assert detect_contact_kind(tmp_path / "x.ldif") is ContactSourceKind.LDIF
    assert detect_contact_kind(tmp_path / "x.csv") is ContactSourceKind.CSV
    d = tmp_path / "Contacts"
    d.mkdir()
    assert detect_contact_kind(d) is ContactSourceKind.CONTACT_XML  # folder of .contact


# -- vCard -------------------------------------------------------------------

def test_vcard_basic(tmp_path: Path) -> None:
    path = tmp_path / "c.vcf"
    path.write_text(
        "BEGIN:VCARD\r\nVERSION:3.0\r\n"
        "FN:John Q. Smith\r\nN:Smith;John;Q;;\r\n"
        "EMAIL;TYPE=INTERNET:john@example.com\r\n"
        "EMAIL;TYPE=INTERNET,HOME:jsmith@home.example.com\r\n"
        "ORG:Acme Inc.;Sales\r\nNOTE:A note\r\nEND:VCARD\r\n",
        encoding="utf-8",
    )
    contacts = list(VcardImporter(path).contacts())
    assert len(contacts) == 1
    c = contacts[0]
    assert c.display_name == "John Q. Smith"
    assert c.first_name == "John" and c.last_name == "Smith"
    assert c.organization == "Acme Inc."
    assert c.notes == "A note"
    assert [e.address for e in c.emails] == ["john@example.com", "jsmith@home.example.com"]


def test_vcard_multiple_and_folding(tmp_path: Path) -> None:
    path = tmp_path / "c.vcf"
    # Second card uses a folded NOTE line (continuation starts with a space).
    path.write_text(
        "BEGIN:VCARD\nVERSION:2.1\nFN:Alice\nEMAIL:alice@x.com\nEND:VCARD\n"
        "BEGIN:VCARD\nVERSION:3.0\nFN:Bob\nNOTE:line one\n  continued\n"
        "EMAIL:bob@x.com\nEND:VCARD\n",
        encoding="utf-8",
    )
    contacts = list(VcardImporter(path).contacts())
    assert [c.display_name for c in contacts] == ["Alice", "Bob"]
    assert contacts[1].notes == "line one continued"


def test_vcard_name_fallback_from_n(tmp_path: Path) -> None:
    path = tmp_path / "c.vcf"
    path.write_text(
        "BEGIN:VCARD\nVERSION:3.0\nN:Doe;Jane;;;\nEMAIL:jane@x.com\nEND:VCARD\n",
        encoding="utf-8",
    )
    (c,) = list(VcardImporter(path).contacts())
    assert c.display_name == "Jane Doe"


def test_vcard_quoted_printable(tmp_path: Path) -> None:
    path = tmp_path / "c.vcf"
    path.write_text(
        "BEGIN:VCARD\nVERSION:2.1\nFN;ENCODING=QUOTED-PRINTABLE:Jos=C3=A9\n"
        "EMAIL:jose@x.com\nEND:VCARD\n",
        encoding="utf-8",
    )
    (c,) = list(VcardImporter(path).contacts())
    assert c.display_name == "José"


# -- CSV ---------------------------------------------------------------------

def test_csv_wab_style_headers(tmp_path: Path) -> None:
    path = tmp_path / "c.csv"
    path.write_text(
        "First Name,Last Name,E-mail Address,E-mail 2 Address,Company,Notes\r\n"
        "John,Smith,john@example.com,john2@example.com,Acme,hello\r\n"
        "Jane,Doe,jane@example.com,,,\r\n",
        encoding="utf-8",
    )
    contacts = list(CsvContactImporter(path).contacts())
    assert len(contacts) == 2
    john = contacts[0]
    assert john.display_name == "John Smith"
    assert john.organization == "Acme"
    assert [e.address for e in john.emails] == ["john@example.com", "john2@example.com"]
    assert contacts[1].emails[0].address == "jane@example.com"


def test_csv_display_name_column(tmp_path: Path) -> None:
    path = tmp_path / "c.csv"
    path.write_text(
        "Name,E-mail Address\r\nThe Team <team>,team@example.com\r\n", encoding="utf-8"
    )
    (c,) = list(CsvContactImporter(path).contacts())
    assert c.display_name == "The Team <team>"


# -- .contact XML ------------------------------------------------------------

_CONTACT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<c:contact xmlns:c="http://schemas.microsoft.com/Contact">
  <c:NameCollection><c:Name>
    <c:FormattedName>John Q. Smith</c:FormattedName>
    <c:GivenName>John</c:GivenName>
    <c:FamilyName>Smith</c:FamilyName>
  </c:Name></c:NameCollection>
  <c:EmailAddressCollection>
    <c:EmailAddress><c:Address>john@example.com</c:Address><c:Type>SMTP</c:Type></c:EmailAddress>
    <c:EmailAddress><c:Address>john2@example.com</c:Address></c:EmailAddress>
  </c:EmailAddressCollection>
  <c:PositionCollection><c:Position><c:Company>Acme</c:Company></c:Position></c:PositionCollection>
  <c:Notes>hello</c:Notes>
</c:contact>"""


def test_contact_xml_single_and_directory(tmp_path: Path) -> None:
    (tmp_path / "john.contact").write_text(_CONTACT_XML, encoding="utf-8")
    # single file
    (c,) = list(ContactXmlImporter(tmp_path / "john.contact").contacts())
    assert c.display_name == "John Q. Smith"
    assert c.first_name == "John" and c.last_name == "Smith"
    assert c.organization == "Acme" and c.notes == "hello"
    assert [e.address for e in c.emails] == ["john@example.com", "john2@example.com"]
    # a directory of .contact files
    assert len(list(ContactXmlImporter(tmp_path).contacts())) == 1


# -- LDIF --------------------------------------------------------------------

def test_ldif_import(tmp_path: Path) -> None:
    path = tmp_path / "c.ldif"
    path.write_text(
        "dn: cn=John Smith\nobjectclass: person\ncn: John Smith\n"
        "givenName: John\nsn: Smith\nmail: john@example.com\no: Acme\n"
        "description: a note\n\n"
        "dn: cn=Jane Doe\ncn: Jane Doe\nmail: jane@example.com\n",
        encoding="utf-8",
    )
    contacts = list(LdifImporter(path).contacts())
    assert [c.display_name for c in contacts] == ["John Smith", "Jane Doe"]
    assert contacts[0].last_name == "Smith"
    assert contacts[0].organization == "Acme"
    assert contacts[0].emails[0].address == "john@example.com"


# -- WAB (guided error) ------------------------------------------------------

def test_wab_raises_guidance(tmp_path: Path) -> None:
    path = tmp_path / "book.wab"
    path.write_bytes(b"\x00" * 32)
    with pytest.raises(ValidationError, match="vCard"):
        list(WabImporter(path).contacts())


# -- service (dedup) ---------------------------------------------------------

def _write_vcf(path: Path, *pairs: tuple[str, str]) -> None:
    body = "".join(
        f"BEGIN:VCARD\nVERSION:3.0\nFN:{name}\nEMAIL:{email}\nEND:VCARD\n"
        for name, email in pairs
    )
    path.write_text(body, encoding="utf-8")


def test_contact_import_service_dedup(db: sqlite3.Connection, tmp_path: Path) -> None:
    path = tmp_path / "c.vcf"
    _write_vcf(path, ("Alice", "alice@x.com"), ("Bob", "bob@x.com"))
    service = ContactImportService(ContactRepository(db))

    first = service.import_contacts(VcardImporter(path))
    assert first.imported == 2 and first.skipped == 0
    assert len(ContactRepository(db).list()) == 2

    # Re-import: both already present (matched by email).
    second = service.import_contacts(VcardImporter(path))
    assert second.imported == 0 and second.skipped == 2
    assert len(ContactRepository(db).list()) == 2
