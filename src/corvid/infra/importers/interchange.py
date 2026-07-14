"""Importers for standard interchange formats: mbox, Maildir, and .eml files.

These are the robust, always-available import paths (pure stdlib ``mailbox``),
covering exports from Thunderbird, Apple Mail, Dovecot/Maildir servers, and any
tool that can emit RFC 822 ``.eml`` files. Outlook Express' native ``.dbx`` store
is handled separately in :mod:`corvid.infra.importers.dbx`.
"""

from __future__ import annotations

import mailbox
from collections.abc import Iterator
from pathlib import Path

from .base import ImportedFolder, ImportedMessage


def _mbox_message_bytes(message: mailbox.mboxMessage) -> bytes:
    return message.as_bytes()


def _mbox_flags(message: mailbox.mboxMessage) -> tuple[bool, bool, bool]:
    """Return (seen, flagged, answered) from mbox Status/X-Status flags."""
    flags = set(message.get_flags())  # subset of 'RODFAT'
    seen = "R" in flags or "O" not in flags  # Read, or not "Old/unseen"
    return seen, "F" in flags, "A" in flags


class MboxImporter:
    """Reads a single Unix ``mbox`` file as one folder.

    The folder name defaults to the file stem (e.g. ``Inbox.mbox`` -> ``Inbox``).
    """

    def __init__(self, path: Path, *, folder_name: str | None = None) -> None:
        self._path = path
        self._folder_name = folder_name or path.stem or path.name

    def folders(self) -> Iterator[ImportedFolder]:
        yield ImportedFolder(self._folder_name, self._iter_messages())

    def _iter_messages(self) -> Iterator[ImportedMessage]:
        box = mailbox.mbox(str(self._path), create=False)
        try:
            for message in box.values():
                seen, flagged, answered = _mbox_flags(message)
                yield ImportedMessage(
                    raw=_mbox_message_bytes(message),
                    seen=seen,
                    flagged=flagged,
                    answered=answered,
                )
        finally:
            box.close()


def _maildir_flags(filename: str) -> tuple[bool, bool, bool]:
    """Parse (seen, flagged, answered) from a Maildir ``cur/`` filename.

    Filenames look like ``unique:2,SF``; the info separator is ``:`` on POSIX but
    Dovecot on case-insensitive/Windows volumes uses ``;`` (and some tools ``!``).
    """
    info = ""
    for sep in (":", ";", "!"):
        if sep in filename:
            marker, _, rest = filename.rpartition(sep)
            if rest.startswith("2,"):
                info = rest[2:]
                break
    return "S" in info, "F" in info, "R" in info


class MaildirImporter:
    """Reads a Maildir tree directly from ``cur/new/tmp``.

    Reads the raw files itself rather than via ``mailbox.Maildir`` so it works on
    Windows, where the ``:`` info separator is an illegal filename character.
    Maildir++ subfolders (directories named ``.Name``) become separate folders.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def folders(self) -> Iterator[ImportedFolder]:
        yield ImportedFolder(self._path.stem or "Imported", self._iter(self._path))
        for child in sorted(self._path.iterdir()):
            if child.is_dir() and child.name.startswith(".") and child.name not in (".", ".."):
                yield ImportedFolder(child.name.lstrip("."), self._iter(child))

    def _iter(self, root: Path) -> Iterator[ImportedMessage]:
        for subdir, seen_default in (("new", False), ("cur", True)):
            box = root / subdir
            if not box.is_dir():
                continue
            for entry in sorted(box.iterdir()):
                if not entry.is_file():
                    continue
                if subdir == "cur":
                    seen, flagged, answered = _maildir_flags(entry.name)
                else:
                    seen, flagged, answered = seen_default, False, False
                yield ImportedMessage(
                    raw=entry.read_bytes(), seen=seen, flagged=flagged, answered=answered
                )


class EmlDirectoryImporter:
    """Reads ``.eml`` files as one folder.

    Accepts either a single ``.eml`` file or a directory (recursing subdirs).
    """

    def __init__(self, path: Path, *, folder_name: str | None = None) -> None:
        self._path = path
        self._folder_name = folder_name or path.stem or path.name

    def folders(self) -> Iterator[ImportedFolder]:
        yield ImportedFolder(self._folder_name, self._iter_messages())

    def _iter_messages(self) -> Iterator[ImportedMessage]:
        if self._path.is_file():
            yield ImportedMessage(raw=self._path.read_bytes())
            return
        for eml in sorted(self._path.rglob("*.eml")):
            if eml.is_file():
                yield ImportedMessage(raw=eml.read_bytes())
