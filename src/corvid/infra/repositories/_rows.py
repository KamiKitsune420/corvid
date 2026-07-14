"""Row (de)serialization helpers shared by repositories.

Timestamps are stored as ISO-8601 UTC text; booleans as 0/1 integers.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


def last_id(cur: sqlite3.Cursor) -> int:
    """Return the row id of the just-executed INSERT (never ``None`` after one)."""
    assert cur.lastrowid is not None
    return cur.lastrowid


def dt_to_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def text_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Accept both 'Z' and offset forms; SQLite datetime('now') yields naive UTC.
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def to_bool(value: object) -> bool:
    return bool(value)


def from_bool(value: bool) -> int:
    return 1 if value else 0
