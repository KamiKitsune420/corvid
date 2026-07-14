"""Message actions that write through to the server and the local database.

Each method assumes ``store`` is connected and selected **read-write** on the
message's source folder (the caller, running on a background thread, handles
that). Server state is changed first; on success the local mirror is updated and
affected folder counts are recomputed.
"""

from __future__ import annotations

import logging

from ..domain.entities import Folder, Message
from ..infra.mail.base import MailStore
from ..infra.repositories import FolderRepository, MessageRepository

log = logging.getLogger("corvid.actions")


class MessageActionService:
    def __init__(self, messages: MessageRepository, folders: FolderRepository) -> None:
        self._messages = messages
        self._folders = folders

    def mark_seen(self, message: Message, store: MailStore, *, seen: bool = True) -> None:
        if message.id is None:
            return
        if message.uid is not None:
            store.store_flags(message.uid, ("\\Seen",), add=seen)
        self._messages.set_seen(message.id, seen)
        self._recount(message.folder_id)

    def set_flagged(self, message: Message, store: MailStore, *, flagged: bool = True) -> None:
        if message.id is None:
            return
        if message.uid is not None:
            store.store_flags(message.uid, ("\\Flagged",), add=flagged)
        self._messages.set_flagged(message.id, flagged)

    def move(self, message: Message, store: MailStore, dest: Folder) -> None:
        if message.id is None or dest.id is None:
            return
        if message.uid is not None:
            store.move(message.uid, dest.remote_name)
        source = message.folder_id
        self._messages.move_to_folder(message.id, dest.id)
        self._recount(source)
        self._recount(dest.id)

    def delete(self, message: Message, store: MailStore, trash: Folder | None) -> None:
        """Delete a message: move to Trash if available, else expunge on the server."""
        if message.id is None:
            return
        if trash is not None and trash.id is not None and trash.id != message.folder_id:
            self.move(message, store, trash)
            return
        if message.uid is not None:
            store.delete(message.uid)
        source = message.folder_id
        self._messages.delete(message.id)
        self._recount(source)

    def _recount(self, folder_id: int | None) -> None:
        if folder_id is None:
            return
        total, unread = self._messages.counts_for_folder(folder_id)
        self._folders.update_counts(folder_id, total, unread)
