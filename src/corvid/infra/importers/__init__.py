"""Importers for legacy and local mail stores.

Supported sources: Unix ``mbox`` files, Maildir trees, directories of ``.eml``
files, and Outlook Express ``.dbx`` stores. :func:`detect_importer` picks one
from a filesystem path; the UI/CLI may also force a kind explicitly.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from .base import ImportedFolder, ImportedMessage, MailImporter
from .dbx import DbxImporter
from .interchange import EmlDirectoryImporter, MaildirImporter, MboxImporter


class SourceKind(StrEnum):
    MBOX = "mbox"
    MAILDIR = "maildir"
    EML_DIR = "eml_dir"
    DBX = "dbx"


def _looks_like_maildir(path: Path) -> bool:
    return all((path / sub).is_dir() for sub in ("cur", "new", "tmp"))


def detect_kind(path: Path) -> SourceKind:
    """Guess the source kind from a path's shape and extension."""
    if path.is_dir():
        return SourceKind.MAILDIR if _looks_like_maildir(path) else SourceKind.EML_DIR
    suffix = path.suffix.lower()
    if suffix == ".dbx":
        return SourceKind.DBX
    if suffix == ".eml":
        return SourceKind.EML_DIR
    return SourceKind.MBOX


def build_importer(
    path: Path, kind: SourceKind | None = None, *, folder_name: str | None = None
) -> MailImporter:
    """Construct the importer for ``path`` (auto-detecting the kind if omitted)."""
    resolved = kind or detect_kind(path)
    if resolved is SourceKind.MAILDIR:
        return MaildirImporter(path)
    if resolved is SourceKind.EML_DIR:
        return EmlDirectoryImporter(path, folder_name=folder_name)
    if resolved is SourceKind.DBX:
        return DbxImporter(path, folder_name=folder_name)
    return MboxImporter(path, folder_name=folder_name)


__all__ = [
    "ImportedFolder",
    "ImportedMessage",
    "MailImporter",
    "SourceKind",
    "MboxImporter",
    "MaildirImporter",
    "EmlDirectoryImporter",
    "DbxImporter",
    "detect_kind",
    "build_importer",
]
