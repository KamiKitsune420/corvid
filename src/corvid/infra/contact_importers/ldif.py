"""LDIF (``.ldif``) contact importer — e.g. the output of ``wabread``.

Parses RFC 2849 LDIF: records separated by blank lines, line folding
(continuation lines begin with a space), and base64 values (``attr:: <b64>``).
Maps the standard person attributes onto a contact.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterator
from pathlib import Path

from ...domain.entities import Contact, EmailAddress


def _parse_line(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    attr, _, rest = line.partition(":")
    attr = attr.strip().lower()
    if rest.startswith(":"):  # base64-encoded value
        try:
            value = base64.b64decode(rest[1:].strip()).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            value = ""
    elif rest.startswith("<"):  # URL reference — unsupported, skip
        return None
    else:
        value = rest.strip()
    return attr, value


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        if raw[:1] == " " and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _contact_from_record(pairs: list[tuple[str, str]]) -> Contact | None:
    first = last = display = organization = notes = ""
    emails: list[EmailAddress] = []
    for attr, value in pairs:
        if not value:
            continue
        if attr == "cn":
            display = display or value
        elif attr == "givenname":
            first = value
        elif attr == "sn":
            last = value
        elif attr in ("mail", "rfc822mailbox"):
            emails.append(EmailAddress(address=value))
        elif attr in ("o", "organizationname", "company"):
            organization = value
        elif attr in ("description", "notes"):
            notes = value
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


class LdifImporter:
    def __init__(self, path: Path) -> None:
        self._path = path

    def contacts(self) -> Iterator[Contact]:
        text = self._path.read_bytes().decode("utf-8", "replace")
        record: list[tuple[str, str]] = []
        for line in _unfold(text):
            if not line.strip():  # blank line ends a record
                if record:
                    contact = _contact_from_record(record)
                    if contact is not None:
                        yield contact
                    record = []
                continue
            if line.lstrip().startswith("#"):
                continue
            parsed = _parse_line(line)
            if parsed is not None:
                record.append(parsed)
        if record:
            contact = _contact_from_record(record)
            if contact is not None:
                yield contact
