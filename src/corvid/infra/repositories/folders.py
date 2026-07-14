"""Folder repository."""

from __future__ import annotations

import sqlite3

from ...domain.entities import Folder, FolderType
from ._rows import last_id
from .base import Repository


def _folder_from_row(row: sqlite3.Row) -> Folder:
    return Folder(
        id=row["id"],
        account_id=row["account_id"],
        remote_name=row["remote_name"],
        display_name=row["display_name"],
        type=FolderType(row["type"]),
        parent_id=row["parent_id"],
        uidvalidity=row["uidvalidity"],
        uidnext=row["uidnext"],
        unread_count=row["unread_count"],
        total_count=row["total_count"],
    )


class FolderRepository(Repository):
    def upsert(self, folder: Folder) -> Folder:
        """Insert or update a folder identified by (account_id, remote_name).

        Returns the persisted folder, including server-state columns
        (uidvalidity/uidnext/counts) that are preserved across updates.
        """
        existing = self.get_by_remote(folder.account_id, folder.remote_name)
        if existing is None:
            cur = self.conn.execute(
                """
                INSERT INTO folders (
                    account_id, remote_name, display_name, type, parent_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    folder.account_id,
                    folder.remote_name,
                    folder.display_name,
                    folder.type.value,
                    folder.parent_id,
                ),
            )
            row_id = last_id(cur)
        else:
            self.conn.execute(
                "UPDATE folders SET display_name = ?, type = ?, parent_id = ? WHERE id = ?",
                (folder.display_name, folder.type.value, folder.parent_id, existing.id),
            )
            row_id = existing.id  # type: ignore[assignment]
        persisted = self.get(row_id)
        assert persisted is not None
        return persisted

    def get(self, folder_id: int) -> Folder | None:
        row = self.conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
        return _folder_from_row(row) if row else None

    def get_by_remote(self, account_id: int, remote_name: str) -> Folder | None:
        row = self.conn.execute(
            "SELECT * FROM folders WHERE account_id = ? AND remote_name = ?",
            (account_id, remote_name),
        ).fetchone()
        return _folder_from_row(row) if row else None

    def list_for_account(self, account_id: int) -> list[Folder]:
        rows = self.conn.execute(
            "SELECT * FROM folders WHERE account_id = ? ORDER BY display_name", (account_id,)
        ).fetchall()
        return [_folder_from_row(r) for r in rows]

    def list_newsgroups(self, account_id: int) -> list[Folder]:
        rows = self.conn.execute(
            "SELECT * FROM folders WHERE account_id = ? AND type = ? ORDER BY display_name",
            (account_id, FolderType.NEWSGROUP.value),
        ).fetchall()
        return [_folder_from_row(r) for r in rows]

    def delete(self, folder_id: int) -> None:
        self.conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))

    def set_uid_state(
        self, folder_id: int, uidvalidity: int | None, uidnext: int | None
    ) -> None:
        self.conn.execute(
            "UPDATE folders SET uidvalidity = ?, uidnext = ? WHERE id = ?",
            (uidvalidity, uidnext, folder_id),
        )

    def update_counts(self, folder_id: int, total: int, unread: int) -> None:
        self.conn.execute(
            "UPDATE folders SET total_count = ?, unread_count = ? WHERE id = ?",
            (total, unread, folder_id),
        )
