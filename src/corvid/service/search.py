"""Local full-text search over message headers (FTS5 with a LIKE fallback)."""

from __future__ import annotations

import sqlite3

from ..domain.entities import Message
from ..infra.repositories.messages import _message_from_row


def _fts_available(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages_fts'"
    ).fetchone()
    return row is not None


def _sanitize_fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 prefix query (term* AND term*)."""
    terms = [t for t in (w.strip() for w in query.replace('"', " ").split()) if t]
    return " AND ".join(f'"{t}"*' for t in terms)


class SearchService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._fts = _fts_available(conn)

    def search(
        self,
        query: str,
        *,
        account_id: int | None = None,
        folder_id: int | None = None,
        limit: int = 200,
    ) -> list[Message]:
        query = query.strip()
        if not query:
            return []
        if self._fts:
            return self._search_fts(query, account_id, folder_id, limit)
        return self._search_like(query, account_id, folder_id, limit)

    def _search_fts(
        self, query: str, account_id: int | None, folder_id: int | None, limit: int
    ) -> list[Message]:
        match = _sanitize_fts_query(query)
        if not match:
            return []
        sql = (
            "SELECT DISTINCT m.* FROM messages_fts f "  # DISTINCT: never repeat a message
            "JOIN messages m ON m.id = f.message_rowid "
            "WHERE messages_fts MATCH ? "
        )
        params: list[object] = [match]
        if account_id is not None:
            sql += "AND m.account_id = ? "
            params.append(account_id)
        if folder_id is not None:
            sql += "AND m.folder_id = ? "
            params.append(folder_id)
        sql += "ORDER BY COALESCE(m.date_utc, '') DESC LIMIT ?"  # newest first
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [_message_from_row(r) for r in rows]

    def _search_like(
        self, query: str, account_id: int | None, folder_id: int | None, limit: int
    ) -> list[Message]:
        like = f"%{query}%"
        sql = (
            "SELECT * FROM messages WHERE (subject LIKE ? OR from_addr LIKE ? "
            "OR from_name LIKE ? OR to_addrs LIKE ?) "
        )
        params: list[object] = [like, like, like, like]
        if account_id is not None:
            sql += "AND account_id = ? "
            params.append(account_id)
        if folder_id is not None:
            sql += "AND folder_id = ? "
            params.append(folder_id)
        sql += "ORDER BY COALESCE(date_utc, '') DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [_message_from_row(r) for r in rows]
