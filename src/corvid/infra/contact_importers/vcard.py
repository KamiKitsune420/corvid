"""vCard (``.vcf``) contact importer (pure stdlib).

Handles vCard 2.1/3.0/4.0: line folding, the common properties (FN, N, EMAIL,
ORG, NOTE), TYPE/ENCODING parameters, quoted-printable values, and value
escaping. Unknown properties are ignored. Multiple vCards per file are supported.
"""

from __future__ import annotations

import quopri
from collections.abc import Iterator
from pathlib import Path

from ...domain.entities import Contact, EmailAddress


def _unfold(text: str) -> list[str]:
    """Join RFC 6350 folded lines (a line starting with space/tab continues the previous)."""
    lines: list[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({"n": "\n", "N": "\n"}.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _decode_value(value: str, params: dict[str, str]) -> str:
    encoding = params.get("ENCODING", "").upper()
    if encoding in ("QUOTED-PRINTABLE", "B", "BASE64"):
        if encoding == "QUOTED-PRINTABLE":
            try:
                return quopri.decodestring(value.encode("utf-8")).decode("utf-8", "replace")
            except ValueError:
                return value
    return _unescape(value)


def _parse_property(line: str) -> tuple[str, dict[str, str], str] | None:
    """Split ``NAME;PARAM=v:value`` into (name, params, value)."""
    if ":" not in line:
        return None
    head, _, value = line.partition(":")
    parts = head.split(";")
    name = parts[0].split(".")[-1].upper()  # drop any group prefix (e.g. item1.EMAIL)
    params: dict[str, str] = {}
    for param in parts[1:]:
        if "=" in param:
            key, _, val = param.partition("=")
            params[key.upper()] = val
        else:  # bare type token, e.g. vCard 2.1 "EMAIL;INTERNET:"
            params.setdefault("TYPE", param)
    return name, params, value


def _contact_from_lines(lines: list[str]) -> Contact | None:
    display_name = first = last = organization = notes = ""
    emails: list[EmailAddress] = []
    for line in lines:
        parsed = _parse_property(line)
        if parsed is None:
            continue
        name, params, raw_value = parsed
        value = _decode_value(raw_value, params)
        if name == "FN":
            display_name = value.strip()
        elif name == "N":
            fields = value.split(";")
            last = _unescape(fields[0]).strip() if len(fields) > 0 else ""
            first = _unescape(fields[1]).strip() if len(fields) > 1 else ""
        elif name == "EMAIL":
            addr = value.strip()
            if addr:
                emails.append(EmailAddress(address=addr))
        elif name == "ORG":
            organization = value.split(";")[0].strip()
        elif name == "NOTE":
            notes = value.strip()
    if not display_name:
        display_name = f"{first} {last}".strip() or (emails[0].address if emails else "")
    if not display_name and not emails:
        return None
    return Contact(
        id=None,
        display_name=display_name or "(no name)",
        first_name=first,
        last_name=last,
        organization=organization,
        notes=notes,
        emails=emails,
    )


class VcardImporter:
    def __init__(self, path: Path) -> None:
        self._path = path

    def contacts(self) -> Iterator[Contact]:
        text = self._path.read_bytes().decode("utf-8", "replace")
        current: list[str] | None = None
        for line in _unfold(text):
            stripped = line.strip()
            if stripped.upper() == "BEGIN:VCARD":
                current = []
            elif stripped.upper() == "END:VCARD":
                if current is not None:
                    contact = _contact_from_lines(current)
                    if contact is not None:
                        yield contact
                current = None
            elif current is not None:
                current.append(line)
