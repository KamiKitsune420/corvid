"""Shared repository base."""

from __future__ import annotations

import sqlite3


class Repository:
    """Base class holding a SQLite connection.

    Concrete repositories add typed CRUD methods that map domain entities to and
    from rows. Kept deliberately thin in Phase 1.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn
