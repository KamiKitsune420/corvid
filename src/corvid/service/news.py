"""Newsgroup use-cases: subscribe, sync headers, and post articles.

Newsgroups are stored as :class:`FolderType.NEWSGROUP` folders and articles as
messages, so the folder tree, message list, preview, and search all work on news
unchanged. Header download reuses :class:`SyncService`; only subscription
management and posting are news-specific.
"""

from __future__ import annotations

import logging

from ..app.jobs import JobContext
from ..domain.entities import Account, Folder, FolderType
from ..domain.news import build_article
from ..infra.mail.nntp_store import NntpMailStore
from ..infra.repositories import FolderRepository, MessageRepository
from .sync import SyncService, SyncSummary

log = logging.getLogger("corvid.news")


class NewsService:
    def __init__(self, folders: FolderRepository, messages: MessageRepository) -> None:
        self._folders = folders
        self._messages = messages
        self._sync = SyncService(folders, messages)

    def subscribed_groups(self, account_id: int) -> list[str]:
        return [f.remote_name for f in self._folders.list_newsgroups(account_id)]

    def available_groups(self, store: NntpMailStore, pattern: str | None = None) -> list[str]:
        return store.list_groups(pattern)

    def subscribe(self, account_id: int, group: str) -> Folder:
        return self._folders.upsert(
            Folder(
                id=None,
                account_id=account_id,
                remote_name=group,
                display_name=group,
                type=FolderType.NEWSGROUP,
            )
        )

    def unsubscribe(self, folder: Folder) -> None:
        if folder.id is None:
            return
        self._messages.delete_for_folder(folder.id)
        self._folders.delete(folder.id)

    def sync(
        self, account: Account, store: NntpMailStore, *, ctx: JobContext | None = None
    ) -> SyncSummary:
        """Download new article headers for every subscribed group."""
        assert account.id is not None
        summary = SyncSummary()
        groups = self._folders.list_newsgroups(account.id)
        summary.folders = len(groups)
        for folder in groups:
            if ctx is not None:
                ctx.raise_if_cancelled()
            count = self._sync.sync_folder_headers(account, folder, store, ctx=ctx)
            summary.new_messages += count
            summary.per_folder[folder.remote_name] = count
        return summary

    def post(
        self,
        account: Account,
        store: NntpMailStore,
        *,
        newsgroups: str,
        subject: str,
        body: str,
        references: str = "",
        from_name: str = "",
    ) -> None:
        article = build_article(
            from_addr=account.email,
            from_name=from_name or account.display_name,
            newsgroups=newsgroups,
            subject=subject,
            body=body,
            references=references,
        )
        store.post(article)
        log.info("posted article to %s", newsgroups)
