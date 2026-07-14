"""Import legacy/local mail stores into the local database.

The :class:`ImportService` drives a :class:`~corvid.infra.importers.base.MailImporter`
(mbox, Maildir, an ``.eml`` directory, or an Outlook Express ``.dbx`` store) into
an existing account: each source folder becomes a local folder, and each message
is stored header-first with its raw RFC 822 bytes cached on disk and marked
``body_fetched`` — so imported mail reads and searches exactly like synced mail
without any server round-trip. Messages carry ``uid = NULL``, so incremental IMAP
sync never touches them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..app.jobs import JobContext
from ..domain.entities import Folder, FolderType
from ..infra.importers.base import ImportedFolder, MailImporter
from ..infra.mail.parsing import header_fields_from_raw
from ..infra.repositories import FolderRepository, MessageRepository
from .delivery import deliver_raw

log = logging.getLogger("corvid.import")

# Local role classification for imported folders, by (case-folded) name.
_NAME_TO_TYPE: dict[str, FolderType] = {
    "inbox": FolderType.INBOX,
    "sent": FolderType.SENT,
    "sent items": FolderType.SENT,
    "outbox": FolderType.OUTBOX,
    "drafts": FolderType.DRAFTS,
    "trash": FolderType.TRASH,
    "deleted": FolderType.TRASH,
    "deleted items": FolderType.TRASH,
    "junk": FolderType.JUNK,
    "junk e-mail": FolderType.JUNK,
    "spam": FolderType.JUNK,
    "archive": FolderType.ARCHIVE,
}


def classify_imported_folder(name: str) -> FolderType:
    return _NAME_TO_TYPE.get(name.strip().lower(), FolderType.CUSTOM)


@dataclass(slots=True)
class ImportSummary:
    folders: int = 0
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    per_folder: dict[str, int] = field(default_factory=dict)


class ImportService:
    """Persists an importer's folders/messages into one account."""

    def __init__(
        self,
        folders: FolderRepository,
        messages: MessageRepository,
        messages_dir: Path,
    ) -> None:
        self._folders = folders
        self._messages = messages
        self._dir = messages_dir

    def import_into(
        self,
        account_id: int,
        importer: MailImporter,
        *,
        ctx: JobContext | None = None,
    ) -> ImportSummary:
        summary = ImportSummary()
        self._dir.mkdir(parents=True, exist_ok=True)
        for imported in importer.folders():
            if ctx is not None:
                ctx.raise_if_cancelled()
            count = self._import_folder(account_id, imported, summary, ctx=ctx)
            summary.folders += 1
            summary.per_folder[imported.name] = count
        log.info(
            "import complete: %d folders, %d messages (%d skipped, %d failed)",
            summary.folders,
            summary.imported,
            summary.skipped,
            summary.failed,
        )
        return summary

    def _import_folder(
        self,
        account_id: int,
        imported: ImportedFolder,
        summary: ImportSummary,
        *,
        ctx: JobContext | None,
    ) -> int:
        folder = self._folders.upsert(
            Folder(
                id=None,
                account_id=account_id,
                remote_name=f"import:{imported.name}",
                display_name=imported.name,
                type=classify_imported_folder(imported.name),
            )
        )
        assert folder.id is not None
        seen_ids = self._messages.existing_message_ids(folder.id)
        count = 0
        for item in imported.messages:
            if ctx is not None:
                ctx.raise_if_cancelled()
            try:
                headers = header_fields_from_raw(item.raw)
            except Exception as exc:  # never let one bad message abort the import
                log.warning("skipping unparseable message: %s", exc)
                summary.failed += 1
                continue
            if headers.message_id and headers.message_id in seen_ids:
                summary.skipped += 1
                continue

            stored = deliver_raw(
                self._messages,
                self._dir,
                folder_id=folder.id,
                account_id=account_id,
                raw=item.raw,
                seen=item.seen,
                flagged=item.flagged,
                answered=item.answered,
            )
            if stored is None:
                summary.failed += 1
                continue
            if headers.message_id:
                seen_ids.add(headers.message_id)
            summary.imported += 1
            count += 1
            if ctx is not None and count % 50 == 0:
                ctx.progress(0.0, f"{imported.name}: {count}")

        total, unread = self._messages.counts_for_folder(folder.id)
        self._folders.update_counts(folder.id, total, unread)
        log.info("imported %d messages into %s", count, imported.name)
        return count
