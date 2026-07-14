"""Message repository (header-level; bodies arrive in a later phase)."""

from __future__ import annotations

import sqlite3

from ...domain.entities import Message, MessageFlags
from ._rows import dt_to_text, from_bool, text_to_dt, to_bool
from .base import Repository


def _message_from_row(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        folder_id=row["folder_id"],
        account_id=row["account_id"],
        uid=row["uid"],
        message_id=row["message_id"],
        subject=row["subject"],
        in_reply_to=row["in_reply_to"],
        references=row["reference_ids"],
        from_name=row["from_name"],
        from_addr=row["from_addr"],
        to_addrs=row["to_addrs"],
        cc_addrs=row["cc_addrs"],
        date_utc=text_to_dt(row["date_utc"]),
        size=row["size"],
        snippet=row["snippet"],
        has_attachments=to_bool(row["has_attachments"]),
        flags=MessageFlags(
            seen=to_bool(row["flag_seen"]),
            answered=to_bool(row["flag_answered"]),
            flagged=to_bool(row["flag_flagged"]),
            draft=to_bool(row["flag_draft"]),
            deleted=to_bool(row["flag_deleted"]),
        ),
        raw_path=row["raw_path"],
        body_fetched=to_bool(row["body_fetched"]),
    )


class MessageRepository(Repository):
    _fts: bool | None = None

    def _fts_enabled(self) -> bool:
        if self._fts is None:
            row = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages_fts'"
            ).fetchone()
            self._fts = row is not None
        return self._fts

    def _index(self, message: Message) -> None:
        if not self._fts_enabled() or message.id is None:
            return
        self.conn.execute(
            """
            INSERT INTO messages_fts(subject, sender, recipients, body, message_rowid)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                message.subject,
                f"{message.from_name} {message.from_addr}".strip(),
                f"{message.to_addrs} {message.cc_addrs}".strip(),
                "",
                message.id,
            ),
        )

    def insert_header(self, message: Message) -> Message:
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO messages (
                folder_id, account_id, uid, message_id, subject,
                in_reply_to, reference_ids,
                from_name, from_addr, to_addrs, cc_addrs, date_utc,
                size, snippet, has_attachments,
                flag_seen, flag_answered, flag_flagged, flag_draft, flag_deleted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.folder_id,
                message.account_id,
                message.uid,
                message.message_id,
                message.subject,
                message.in_reply_to,
                message.references,
                message.from_name,
                message.from_addr,
                message.to_addrs,
                message.cc_addrs,
                dt_to_text(message.date_utc),
                message.size,
                message.snippet,
                from_bool(message.has_attachments),
                from_bool(message.flags.seen),
                from_bool(message.flags.answered),
                from_bool(message.flags.flagged),
                from_bool(message.flags.draft),
                from_bool(message.flags.deleted),
            ),
        )
        if cur.lastrowid:
            message.id = int(cur.lastrowid)
            self._index(message)
        return message

    def get(self, message_id: int) -> Message | None:
        row = self.conn.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        return _message_from_row(row) if row else None

    def existing_uids(self, folder_id: int) -> set[int]:
        rows = self.conn.execute(
            "SELECT uid FROM messages WHERE folder_id = ? AND uid IS NOT NULL", (folder_id,)
        ).fetchall()
        return {int(r["uid"]) for r in rows}

    def existing_message_ids(self, folder_id: int) -> set[str]:
        """Non-empty RFC 822 Message-IDs already present in a folder.

        Used by the importer to skip re-importing the same messages.
        """
        rows = self.conn.execute(
            "SELECT message_id FROM messages WHERE folder_id = ? AND message_id <> ''",
            (folder_id,),
        ).fetchall()
        return {str(r["message_id"]) for r in rows}

    def max_uid(self, folder_id: int) -> int | None:
        row = self.conn.execute(
            "SELECT MAX(uid) AS m FROM messages WHERE folder_id = ?", (folder_id,)
        ).fetchone()
        return int(row["m"]) if row and row["m"] is not None else None

    def list_for_folder(
        self, folder_id: int, *, limit: int = 200, offset: int = 0
    ) -> list[Message]:
        rows = self.conn.execute(
            """
            SELECT * FROM messages WHERE folder_id = ?
            ORDER BY COALESCE(date_utc, '') DESC, uid DESC
            LIMIT ? OFFSET ?
            """,
            (folder_id, limit, offset),
        ).fetchall()
        return [_message_from_row(r) for r in rows]

    def counts_for_folder(self, folder_id: int) -> tuple[int, int]:
        """Return (total, unread)."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN flag_seen = 0 THEN 1 ELSE 0 END) AS unread
            FROM messages WHERE folder_id = ?
            """,
            (folder_id,),
        ).fetchone()
        return int(row["total"]), int(row["unread"] or 0)

    def set_seen(self, message_id: int, seen: bool) -> None:
        self.conn.execute(
            "UPDATE messages SET flag_seen = ? WHERE id = ?", (from_bool(seen), message_id)
        )

    def set_flagged(self, message_id: int, flagged: bool) -> None:
        self.conn.execute(
            "UPDATE messages SET flag_flagged = ? WHERE id = ?",
            (from_bool(flagged), message_id),
        )

    def set_deleted(self, message_id: int, deleted: bool) -> None:
        self.conn.execute(
            "UPDATE messages SET flag_deleted = ? WHERE id = ?",
            (from_bool(deleted), message_id),
        )

    def move_to_folder(self, message_id: int, folder_id: int) -> None:
        self.conn.execute(
            "UPDATE messages SET folder_id = ? WHERE id = ?", (folder_id, message_id)
        )

    def mark_body_fetched(self, message_id: int, raw_path: str) -> None:
        self.conn.execute(
            "UPDATE messages SET body_fetched = 1, raw_path = ? WHERE id = ?",
            (raw_path, message_id),
        )

    def delete(self, message_id: int) -> None:
        if self._fts_enabled():
            self.conn.execute(
                "DELETE FROM messages_fts WHERE message_rowid = ?", (message_id,)
            )
        self.conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))

    def delete_for_folder(self, folder_id: int) -> None:
        if self._fts_enabled():
            self.conn.execute(
                "DELETE FROM messages_fts WHERE message_rowid IN "
                "(SELECT id FROM messages WHERE folder_id = ?)",
                (folder_id,),
            )
        self.conn.execute("DELETE FROM messages WHERE folder_id = ?", (folder_id,))
