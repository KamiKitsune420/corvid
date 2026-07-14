"""POP3 receive use-case: download new mail into the local Inbox.

POP3 has no server folders, so all mail lands in a single local ``Inbox`` folder
for the account. Messages arrive as full raw bytes and are stored via
:func:`deliver_raw` (header + cached body, ``uid = NULL``). Each message's UIDL is
recorded so re-polling only downloads new mail; with ``pop3_leave_on_server``
disabled the message is also deleted from the server after download.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..app.jobs import JobContext
from ..domain.entities import Account, Folder, FolderType
from ..infra.mail.pop3_receiver import Pop3Receiver
from ..infra.repositories import (
    FolderRepository,
    MessageRepository,
    Pop3UidlRepository,
)
from .delivery import deliver_raw
from .sync import SyncSummary

log = logging.getLogger("corvid.pop3")


class Pop3Service:
    def __init__(
        self,
        folders: FolderRepository,
        messages: MessageRepository,
        uidls: Pop3UidlRepository,
        messages_dir: Path,
    ) -> None:
        self._folders = folders
        self._messages = messages
        self._uidls = uidls
        self._dir = messages_dir

    def _inbox(self, account_id: int) -> Folder:
        return self._folders.upsert(
            Folder(
                id=None,
                account_id=account_id,
                remote_name="INBOX",
                display_name="Inbox",
                type=FolderType.INBOX,
            )
        )

    def sync(
        self, account: Account, receiver: Pop3Receiver, *, ctx: JobContext | None = None
    ) -> SyncSummary:
        assert account.id is not None
        self._dir.mkdir(parents=True, exist_ok=True)
        inbox = self._inbox(account.id)
        assert inbox.id is not None
        seen = self._uidls.seen(account.id)
        delete = not account.pop3_leave_on_server

        summary = SyncSummary(folders=1)
        count = 0
        for uidl, raw in receiver.fetch_new(seen, delete=delete):
            if ctx is not None:
                ctx.raise_if_cancelled()
            stored = deliver_raw(
                self._messages,
                self._dir,
                folder_id=inbox.id,
                account_id=account.id,
                raw=raw,
                seen=False,  # newly received mail is unread
            )
            self._uidls.add(account.id, uidl)  # record even on parse failure: don't refetch
            if stored is not None:
                count += 1
                if ctx is not None and count % 20 == 0:
                    ctx.progress(0.0, f"Inbox: {count}")

        total, unread = self._messages.counts_for_folder(inbox.id)
        self._folders.update_counts(inbox.id, total, unread)
        summary.new_messages = count
        summary.per_folder["INBOX"] = count
        log.info("POP3: downloaded %d new message(s) for %s", count, account.email)
        return summary
