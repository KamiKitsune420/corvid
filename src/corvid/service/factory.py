"""Helpers to assemble services from a database connection.

SQLite connections are thread-affine, so each thread (UI vs. background sync
worker) builds its own services over its own connection to the same WAL database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..infra.credentials import CredentialStore, get_default_store
from ..infra.oauth import OAuthClient
from ..infra.repositories import (
    AccountRepository,
    ContactRepository,
    EventRepository,
    FolderRepository,
    IdentityRepository,
    MessageRepository,
    Pop3UidlRepository,
    RuleRepository,
)
from .accounts import AccountService, StoreFactory
from .calendar import CalendarService
from .contact_import import ContactImportService
from .import_store import ImportService
from .news import NewsService
from .pop3 import Pop3Service
from .rules import RuleService
from .sync import SyncService


def build_account_service(
    conn: sqlite3.Connection,
    data_dir: Path,
    *,
    credentials: CredentialStore | None = None,
    store_factory: StoreFactory | None = None,
    oauth_clients: dict[str, OAuthClient] | None = None,
) -> AccountService:
    return AccountService(
        AccountRepository(conn),
        IdentityRepository(conn),
        credentials or get_default_store(data_dir),
        store_factory=store_factory,
        oauth_clients=oauth_clients,
    )


def build_sync_service(conn: sqlite3.Connection, *, apply_rules: bool = True) -> SyncService:
    folders = FolderRepository(conn)
    messages = MessageRepository(conn)
    rules = (
        RuleService(RuleRepository(conn), messages, folders) if apply_rules else None
    )
    return SyncService(folders, messages, rules=rules)


def build_import_service(conn: sqlite3.Connection, messages_dir: Path) -> ImportService:
    return ImportService(FolderRepository(conn), MessageRepository(conn), messages_dir)


def build_news_service(conn: sqlite3.Connection) -> NewsService:
    return NewsService(FolderRepository(conn), MessageRepository(conn))


def build_contact_import_service(conn: sqlite3.Connection) -> ContactImportService:
    return ContactImportService(ContactRepository(conn))


def build_calendar_service(conn: sqlite3.Connection) -> CalendarService:
    return CalendarService(EventRepository(conn))


def build_pop3_service(conn: sqlite3.Connection, messages_dir: Path) -> Pop3Service:
    return Pop3Service(
        FolderRepository(conn),
        MessageRepository(conn),
        Pop3UidlRepository(conn),
        messages_dir,
    )
