"""Windows Contacts ``.contact`` importer (the WAB successor store).

Each ``.contact`` file is one contact in Microsoft's Windows Contact Schema XML
(``http://schemas.microsoft.com/Contact``). This importer accepts a single
``.contact`` file or a directory of them (``%UserProfile%\\Contacts``). Element
namespaces are matched by local tag name, so schema-URI variations don't matter.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

from ...domain.entities import Contact, EmailAddress


def _local(tag: str) -> str:
    """Strip an XML namespace: ``{uri}Name`` -> ``Name``."""
    return tag.rsplit("}", 1)[-1]


def _find(element: ET.Element, *names: str) -> ET.Element | None:
    """Depth-first find the first descendant whose local tag matches ``names``."""
    wanted = set(names)
    for child in element.iter():
        if _local(child.tag) in wanted:
            return child
    return None


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _contact_from_xml(root: ET.Element) -> Contact | None:
    name_el = _find(root, "Name")
    first = last = display = ""
    if name_el is not None:
        for child in name_el.iter():
            local = _local(child.tag)
            if local == "GivenName":
                first = _text(child)
            elif local == "FamilyName":
                last = _text(child)
            elif local == "FormattedName":
                display = _text(child)

    emails: list[EmailAddress] = []
    for el in root.iter():
        if _local(el.tag) == "EmailAddress":
            addr_el = next((c for c in el.iter() if _local(c.tag) == "Address"), None)
            addr = _text(addr_el)
            if addr:
                emails.append(EmailAddress(address=addr))

    position = _find(root, "Position")
    organization = ""
    if position is not None:
        company = next(
            (c for c in position.iter() if _local(c.tag) in ("Company", "Organization")),
            None,
        )
        organization = _text(company)

    notes = _text(_find(root, "Notes"))

    if not display:
        display = f"{first} {last}".strip() or (emails[0].address if emails else "")
    if not display and not emails:
        return None
    return Contact(
        id=None,
        display_name=display or "(no name)",
        first_name=first,
        last_name=last,
        organization=organization,
        notes=notes,
        emails=emails,
    )


class ContactXmlImporter:
    def __init__(self, path: Path) -> None:
        self._path = path

    def contacts(self) -> Iterator[Contact]:
        files = (
            sorted(self._path.rglob("*.contact"))
            if self._path.is_dir()
            else [self._path]
        )
        for file in files:
            try:
                root = ET.fromstring(file.read_bytes())
            except ET.ParseError:
                continue
            contact = _contact_from_xml(root)
            if contact is not None:
                yield contact
