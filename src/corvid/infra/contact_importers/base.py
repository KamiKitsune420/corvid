"""Port for importing contacts from address-book files.

A contact importer reads a file (vCard, CSV, or a Windows Address Book export)
and yields domain :class:`~corvid.domain.entities.Contact` objects (unpersisted,
``id is None``). The service layer deduplicates and stores them via the normal
``ContactRepository``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from ...domain.entities import Contact


class ContactImporter(Protocol):
    def contacts(self) -> Iterator[Contact]:
        """Yield each contact found in the source."""
        ...
