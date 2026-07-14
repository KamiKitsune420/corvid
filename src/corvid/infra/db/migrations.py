"""Forward-only schema migrations.

Each :class:`Migration` runs inside its own transaction and is recorded in
``schema_migrations``. Migrations are idempotent at the runner level: already
applied versions are skipped. Statements are executed individually (never via
``executescript``, which would implicitly commit and break atomicity).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ...errors import MigrationError
from .connection import fts5_available

log = logging.getLogger("corvid.db")

MigrationFn = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: MigrationFn


def _run(conn: sqlite3.Connection, statements: Sequence[str]) -> None:
    for statement in statements:
        conn.execute(statement)


# -- v1: core schema --------------------------------------------------------
_CORE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE accounts (
        id              INTEGER PRIMARY KEY,
        display_name    TEXT NOT NULL,
        email           TEXT NOT NULL,
        username        TEXT NOT NULL,
        imap_host       TEXT NOT NULL,
        imap_port       INTEGER NOT NULL,
        imap_security   TEXT NOT NULL DEFAULT 'tls',
        smtp_host       TEXT NOT NULL,
        smtp_port       INTEGER NOT NULL,
        smtp_security   TEXT NOT NULL DEFAULT 'starttls',
        auth_method     TEXT NOT NULL DEFAULT 'password',
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE identities (
        id              INTEGER PRIMARY KEY,
        account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        display_name    TEXT NOT NULL,
        email           TEXT NOT NULL,
        reply_to        TEXT NOT NULL DEFAULT '',
        signature       TEXT NOT NULL DEFAULT '',
        is_default      INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE folders (
        id              INTEGER PRIMARY KEY,
        account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        remote_name     TEXT NOT NULL,
        display_name    TEXT NOT NULL,
        type            TEXT NOT NULL DEFAULT 'custom',
        parent_id       INTEGER REFERENCES folders(id) ON DELETE SET NULL,
        uidvalidity     INTEGER,
        uidnext         INTEGER,
        unread_count    INTEGER NOT NULL DEFAULT 0,
        total_count     INTEGER NOT NULL DEFAULT 0,
        UNIQUE (account_id, remote_name)
    )
    """,
    """
    CREATE TABLE messages (
        id              INTEGER PRIMARY KEY,
        folder_id       INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
        account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        uid             INTEGER,
        message_id      TEXT NOT NULL DEFAULT '',
        subject         TEXT NOT NULL DEFAULT '',
        from_name       TEXT NOT NULL DEFAULT '',
        from_addr       TEXT NOT NULL DEFAULT '',
        to_addrs        TEXT NOT NULL DEFAULT '',
        cc_addrs        TEXT NOT NULL DEFAULT '',
        date_utc        TEXT,
        size            INTEGER NOT NULL DEFAULT 0,
        snippet         TEXT NOT NULL DEFAULT '',
        has_attachments INTEGER NOT NULL DEFAULT 0,
        flag_seen       INTEGER NOT NULL DEFAULT 0,
        flag_answered   INTEGER NOT NULL DEFAULT 0,
        flag_flagged    INTEGER NOT NULL DEFAULT 0,
        flag_draft      INTEGER NOT NULL DEFAULT 0,
        flag_deleted    INTEGER NOT NULL DEFAULT 0,
        raw_path        TEXT NOT NULL DEFAULT '',
        body_fetched    INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (folder_id, uid)
    )
    """,
    "CREATE INDEX idx_messages_folder ON messages(folder_id)",
    "CREATE INDEX idx_messages_account ON messages(account_id)",
    "CREATE INDEX idx_messages_date ON messages(date_utc)",
    "CREATE INDEX idx_messages_unread ON messages(folder_id, flag_seen)",
    """
    CREATE TABLE attachments (
        id              INTEGER PRIMARY KEY,
        message_id      INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        filename        TEXT NOT NULL,
        content_type    TEXT NOT NULL DEFAULT 'application/octet-stream',
        size            INTEGER NOT NULL DEFAULT 0,
        content_id      TEXT NOT NULL DEFAULT '',
        is_inline       INTEGER NOT NULL DEFAULT 0,
        storage_path    TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX idx_attachments_message ON attachments(message_id)",
    """
    CREATE TABLE contacts (
        id              INTEGER PRIMARY KEY,
        display_name    TEXT NOT NULL,
        first_name      TEXT NOT NULL DEFAULT '',
        last_name       TEXT NOT NULL DEFAULT '',
        organization    TEXT NOT NULL DEFAULT '',
        notes           TEXT NOT NULL DEFAULT '',
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE contact_emails (
        id              INTEGER PRIMARY KEY,
        contact_id      INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        email           TEXT NOT NULL,
        label           TEXT NOT NULL DEFAULT '',
        is_primary      INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX idx_contact_emails_email ON contact_emails(email)",
    "CREATE INDEX idx_contact_emails_contact ON contact_emails(contact_id)",
    """
    CREATE TABLE rules (
        id              INTEGER PRIMARY KEY,
        name            TEXT NOT NULL,
        enabled         INTEGER NOT NULL DEFAULT 1,
        priority        INTEGER NOT NULL DEFAULT 0,
        match_json      TEXT NOT NULL DEFAULT '{}',
        actions_json    TEXT NOT NULL DEFAULT '[]',
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE app_meta (
        key             TEXT PRIMARY KEY,
        value           TEXT NOT NULL
    )
    """,
)


def _m0001_initial(conn: sqlite3.Connection) -> None:
    _run(conn, _CORE_STATEMENTS)


# -- v2: full-text search index ---------------------------------------------
def _m0002_search(conn: sqlite3.Connection) -> None:
    if not fts5_available(conn):
        log.warning("SQLite FTS5 is unavailable; full-text search will be disabled.")
        conn.execute(
            "INSERT OR REPLACE INTO app_meta(key, value) VALUES ('fts5', 'unavailable')"
        )
        return
    # Contentless external index; populated by the search service (later phase).
    conn.execute(
        """
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            subject,
            sender,
            recipients,
            body,
            message_rowid UNINDEXED
        )
        """
    )
    conn.execute("INSERT OR REPLACE INTO app_meta(key, value) VALUES ('fts5', 'available')")


def _m0003_drafts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE drafts (
            id              INTEGER PRIMARY KEY,
            account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            identity_id     INTEGER REFERENCES identities(id) ON DELETE SET NULL,
            to_addrs        TEXT NOT NULL DEFAULT '',
            cc_addrs        TEXT NOT NULL DEFAULT '',
            bcc_addrs       TEXT NOT NULL DEFAULT '',
            subject         TEXT NOT NULL DEFAULT '',
            body_text       TEXT NOT NULL DEFAULT '',
            body_html       TEXT NOT NULL DEFAULT '',
            attachments_json TEXT NOT NULL DEFAULT '[]',
            in_reply_to     TEXT NOT NULL DEFAULT '',
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX idx_drafts_account ON drafts(account_id)")


def _m0004_news(conn: sqlite3.Connection) -> None:
    """Add news (NNTP) account support: an account kind and NNTP server fields."""
    _run(
        conn,
        (
            "ALTER TABLE accounts ADD COLUMN kind TEXT NOT NULL DEFAULT 'mail'",
            "ALTER TABLE accounts ADD COLUMN nntp_host TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE accounts ADD COLUMN nntp_port INTEGER NOT NULL DEFAULT 119",
            "ALTER TABLE accounts ADD COLUMN nntp_security TEXT NOT NULL DEFAULT 'tls'",
        ),
    )


def _m0005_pop3(conn: sqlite3.Connection) -> None:
    """Add POP3 receive support: a receive protocol, POP3 server fields, and a
    per-account UIDL ledger so already-downloaded messages are not re-fetched."""
    _run(
        conn,
        (
            "ALTER TABLE accounts ADD COLUMN receive_protocol TEXT NOT NULL DEFAULT 'imap'",
            "ALTER TABLE accounts ADD COLUMN pop3_host TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE accounts ADD COLUMN pop3_port INTEGER NOT NULL DEFAULT 995",
            "ALTER TABLE accounts ADD COLUMN pop3_security TEXT NOT NULL DEFAULT 'tls'",
            "ALTER TABLE accounts ADD COLUMN pop3_leave_on_server INTEGER NOT NULL DEFAULT 1",
            """
            CREATE TABLE pop3_uidls (
                account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                uidl        TEXT NOT NULL,
                PRIMARY KEY (account_id, uidl)
            )
            """,
        ),
    )


def _m0006_calendar(conn: sqlite3.Connection) -> None:
    """Add a local calendar of events."""
    _run(
        conn,
        (
            """
            CREATE TABLE events (
                id          INTEGER PRIMARY KEY,
                title       TEXT NOT NULL DEFAULT '',
                location    TEXT NOT NULL DEFAULT '',
                notes       TEXT NOT NULL DEFAULT '',
                start_utc   TEXT NOT NULL,
                end_utc     TEXT NOT NULL,
                all_day     INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
            "CREATE INDEX idx_events_start ON events(start_utc)",
        ),
    )


def _m0007_threading(conn: sqlite3.Connection) -> None:
    """Store reply headers so messages can be grouped into conversations.

    ``references`` is a SQL keyword, so the column is named ``reference_ids``.
    Existing rows default to empty; they thread once re-synced (which now fetches
    these headers)."""
    _run(
        conn,
        (
            "ALTER TABLE messages ADD COLUMN in_reply_to TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE messages ADD COLUMN reference_ids TEXT NOT NULL DEFAULT ''",
        ),
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "initial schema", _m0001_initial),
    Migration(2, "full-text search index", _m0002_search),
    Migration(3, "drafts table", _m0003_drafts),
    Migration(4, "news account support", _m0004_news),
    Migration(5, "pop3 receive support", _m0005_pop3),
    Migration(6, "calendar events", _m0006_calendar),
    Migration(7, "message threading headers", _m0007_threading),
)


def _ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def current_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied migration version (0 if none)."""
    _ensure_meta(conn)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return int(row["v"]) if row and row["v"] is not None else 0


def apply_migrations(conn: sqlite3.Connection) -> list[int]:
    """Apply all pending migrations in order; return the versions applied."""
    _ensure_meta(conn)
    current = current_version(conn)
    applied: list[int] = []
    for migration in sorted(MIGRATIONS, key=lambda m: m.version):
        if migration.version <= current:
            continue
        try:
            conn.execute("BEGIN")
            migration.apply(conn)
            conn.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) failed: {exc}"
            ) from exc
        applied.append(migration.version)
        log.info("applied migration %d: %s", migration.version, migration.name)
    return applied
