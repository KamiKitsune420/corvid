"""Windows Address Book (``.wab``) contact importer.

The ``.wab`` on-disk format is undocumented, has no reliable signature, and its
only reverse-engineered description (libwab) leans on unexplained header fields
with no documented property serialization — so a from-scratch reader cannot
reliably extract names and addresses. Rather than ship a guessed parser that
would silently produce wrong data, Corvid recognizes the file and directs the
user to the standard, lossless migration path: export from Windows Address Book /
Windows Contacts to vCard or CSV (both of which Corvid imports), which is exactly
how ``.wab`` migration is done in practice.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ...domain.entities import Contact
from ...errors import ValidationError


class WabImporter:
    def __init__(self, path: Path) -> None:
        self._path = path

    def contacts(self) -> Iterator[Contact]:
        raise ValidationError(
            "Direct .wab reading isn't supported (the format is undocumented). "
            "In Windows Address Book / Contacts, choose Export → vCard or CSV, "
            "then import that file here.",
            user_message=(
                "Windows Address Book (.wab) files can't be read directly. Export "
                "your contacts to vCard (.vcf) or CSV from Windows, then import that."
            ),
        )
