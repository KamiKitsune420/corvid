"""Ports and value objects for importing legacy/local mail stores.

An importer reads a source on disk (a single mbox file, a maildir, a directory of
``.eml`` files, or an Outlook Express ``.dbx`` store) and yields folders, each
folder yielding raw RFC 822 messages. The ``service`` layer maps these into the
local database via the normal repositories, so imported mail displays and
searches exactly like synced mail.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ImportedMessage:
    """One message from a source store: raw bytes plus recovered flags."""

    raw: bytes
    seen: bool = True
    flagged: bool = False
    answered: bool = False


@dataclass(slots=True)
class ImportedFolder:
    """A named folder and its (lazily produced) messages."""

    name: str
    messages: Iterable[ImportedMessage]


class MailImporter(Protocol):
    """Reads a local store and yields its folders."""

    def folders(self) -> Iterator[ImportedFolder]:
        """Yield each folder in the source, in a stable order."""
        ...
