"""SQLite connection factory.

Connections are opened in WAL mode with foreign keys enforced and autocommit
(``isolation_level=None``) so that migrations can manage transactions explicitly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a tuned SQLite connection. ``path`` may be ``":memory:"``."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def fts5_available(conn: sqlite3.Connection) -> bool:
    """Return True if this SQLite build supports the FTS5 extension."""
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.__corvid_fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp.__corvid_fts_probe")
        return True
    except sqlite3.OperationalError:
        return False
