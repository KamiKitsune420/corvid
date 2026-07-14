"""CSV contact importer (pure stdlib ``csv``).

Targets the CSV that Windows Address Book / Outlook export ("Name", "First
Name", "Last Name", "E-mail Address", "E-mail 2 Address", "Company", "Notes",
...), but maps headers flexibly (case- and punctuation-insensitive) so exports
from other tools also work. Every column whose header looks like an email address
is collected, in order.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from ...domain.entities import Contact, EmailAddress

# Normalized header -> field. Normalization drops case, spaces, and punctuation.
_FIRST = {"firstname", "givenname", "first"}
_LAST = {"lastname", "surname", "familyname", "last"}
_DISPLAY = {"name", "displayname", "fullname"}
_ORG = {"company", "organization", "organisation", "companyname"}
_NOTES = {"notes", "note", "comments"}


def _norm(header: str) -> str:
    return "".join(ch for ch in header.lower() if ch.isalnum())


def _looks_like_email_header(norm: str) -> bool:
    return "email" in norm and "display" not in norm  # skip "E-mail Display Name"


class CsvContactImporter:
    def __init__(self, path: Path) -> None:
        self._path = path

    def contacts(self) -> Iterator[Contact]:
        text = self._path.read_bytes().decode("utf-8-sig", "replace")
        reader = csv.DictReader(text.splitlines())
        if reader.fieldnames is None:
            return
        norm_map = {name: _norm(name) for name in reader.fieldnames}
        email_cols = [n for n, k in norm_map.items() if _looks_like_email_header(k)]
        for row in reader:
            contact = self._row_to_contact(row, norm_map, email_cols)
            if contact is not None:
                yield contact

    def _row_to_contact(
        self,
        row: dict[str, str | None],
        norm_map: dict[str, str],
        email_cols: list[str],
    ) -> Contact | None:
        first = last = display = organization = notes = ""
        for col, norm in norm_map.items():
            value = (row.get(col) or "").strip()
            if not value:
                continue
            if norm in _FIRST:
                first = value
            elif norm in _LAST:
                last = value
            elif norm in _DISPLAY and not display:
                display = value
            elif norm in _ORG:
                organization = value
            elif norm in _NOTES:
                notes = value
        emails = [
            EmailAddress(address=addr)
            for col in email_cols
            if (addr := (row.get(col) or "").strip())
        ]
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
