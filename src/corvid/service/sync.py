"""Folder and header synchronization use-cases."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..app.jobs import JobContext
from ..domain.entities import Account, Folder, FolderType, Message, MessageFlags
from ..errors import JobCancelled
from ..infra.mail.base import MailStore
from ..infra.mail.types import FolderInfo, HeaderEnvelope
from ..infra.repositories import FolderRepository, MessageRepository
from .rules import RuleService

log = logging.getLogger("corvid.sync")

_SPECIAL_USE_TO_TYPE: dict[str, FolderType] = {
    "\\inbox": FolderType.INBOX,
    "\\sent": FolderType.SENT,
    "\\drafts": FolderType.DRAFTS,
    "\\trash": FolderType.TRASH,
    "\\junk": FolderType.JUNK,
    "\\archive": FolderType.ARCHIVE,
}

_NAME_TO_TYPE: dict[str, FolderType] = {
    "inbox": FolderType.INBOX,
    "sent": FolderType.SENT,
    "sent items": FolderType.SENT,
    "drafts": FolderType.DRAFTS,
    "trash": FolderType.TRASH,
    "deleted": FolderType.TRASH,
    "deleted items": FolderType.TRASH,
    "junk": FolderType.JUNK,
    "spam": FolderType.JUNK,
    "archive": FolderType.ARCHIVE,
}


def classify_folder(info: FolderInfo) -> FolderType:
    """Map a server folder to a known role via special-use flag then by name."""
    if info.is_newsgroup:
        return FolderType.NEWSGROUP
    if info.special_use:
        mapped = _SPECIAL_USE_TO_TYPE.get(info.special_use.lower())
        if mapped is not None:
            return mapped
    return _NAME_TO_TYPE.get(info.display_name.lower(), FolderType.CUSTOM)


def envelope_to_message(account_id: int, folder_id: int, env: HeaderEnvelope) -> Message:
    return Message(
        id=None,
        folder_id=folder_id,
        account_id=account_id,
        uid=env.uid,
        message_id=env.message_id,
        subject=env.subject,
        in_reply_to=env.in_reply_to,
        references=env.references,
        from_name=env.from_name,
        from_addr=env.from_addr,
        to_addrs=env.to_addrs,
        cc_addrs=env.cc_addrs,
        date_utc=env.date_utc,
        size=env.size,
        snippet="",
        has_attachments=env.has_attachments,
        flags=MessageFlags(
            seen=env.seen,
            answered=env.answered,
            flagged=env.flagged,
            draft=env.draft,
            deleted=env.deleted,
        ),
    )


@dataclass(slots=True)
class SyncSummary:
    folders: int = 0
    new_messages: int = 0
    per_folder: dict[str, int] = field(default_factory=dict)


class SyncService:
    """Synchronizes folder lists and message headers from a connected store."""

    def __init__(
        self,
        folders: FolderRepository,
        messages: MessageRepository,
        *,
        rules: RuleService | None = None,
    ) -> None:
        self._folders = folders
        self._messages = messages
        self._rules = rules

    def sync_folders(self, account: Account, store: MailStore) -> list[Folder]:
        assert account.id is not None
        result: list[Folder] = []
        for info in store.list_folders():
            # Skip container-only mailboxes (e.g. Gmail's "[Gmail]") — they hold no
            # mail and can't be SELECTed, which otherwise aborts the whole sync.
            if any("noselect" in flag.lower() for flag in info.flags):
                continue
            folder = Folder(
                id=None,
                account_id=account.id,
                remote_name=info.remote_name,
                display_name=info.display_name,
                type=classify_folder(info),
            )
            result.append(self._folders.upsert(folder))
        log.info("synced %d folders for account %s", len(result), account.email)
        return result

    def sync_folder_headers(
        self,
        account: Account,
        folder: Folder,
        store: MailStore,
        *,
        ctx: JobContext | None = None,
        batch_size: int = 200,
    ) -> int:
        assert account.id is not None and folder.id is not None
        status = store.select(folder.remote_name)

        # UIDVALIDITY change invalidates all cached UIDs for this folder.
        if folder.uidvalidity is not None and folder.uidvalidity != status.uidvalidity:
            log.warning(
                "UIDVALIDITY changed for %s (%s -> %s); resyncing folder",
                folder.remote_name,
                folder.uidvalidity,
                status.uidvalidity,
            )
            self._messages.delete_for_folder(folder.id)
            since = None
        else:
            since = self._messages.max_uid(folder.id)

        uids = store.search_uids(since)
        existing = self._messages.existing_uids(folder.id)
        pending = [u for u in uids if u not in existing]

        engine = self._rules.engine() if self._rules is not None else None
        new_count = 0
        for start in range(0, len(pending), batch_size):
            if ctx is not None:
                ctx.raise_if_cancelled()
            chunk = pending[start : start + batch_size]
            for env in store.fetch_headers(chunk):
                message = self._messages.insert_header(
                    envelope_to_message(account.id, folder.id, env)
                )
                if self._rules is not None and engine is not None:
                    self._rules.apply_to_message(account.id, message, engine=engine)
                new_count += 1
            if ctx is not None and pending:
                ctx.progress(min(1.0, (start + len(chunk)) / len(pending)), folder.display_name)

        total, unread = self._messages.counts_for_folder(folder.id)
        self._folders.update_counts(folder.id, total, unread)
        self._folders.set_uid_state(folder.id, status.uidvalidity, status.uidnext)
        log.info("synced %d new headers in %s", new_count, folder.remote_name)
        return new_count

    def sync_account(
        self, account: Account, store: MailStore, *, ctx: JobContext | None = None
    ) -> SyncSummary:
        summary = SyncSummary()
        folders = self.sync_folders(account, store)
        summary.folders = len(folders)
        for folder in folders:
            if ctx is not None:
                ctx.raise_if_cancelled()
            try:
                count = self.sync_folder_headers(account, folder, store, ctx=ctx)
            except JobCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad folder must not abort the rest
                log.warning("skipping folder %s: %s", folder.remote_name, exc)
                continue
            summary.new_messages += count
            summary.per_folder[folder.remote_name] = count
        return summary
