"""Ledger of POP3 UIDLs already downloaded per account (dedupe on re-poll)."""

from __future__ import annotations

from .base import Repository


class Pop3UidlRepository(Repository):
    def seen(self, account_id: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT uidl FROM pop3_uidls WHERE account_id = ?", (account_id,)
        ).fetchall()
        return {str(r["uidl"]) for r in rows}

    def add(self, account_id: int, uidl: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO pop3_uidls (account_id, uidl) VALUES (?, ?)",
            (account_id, uidl),
        )
