"""Draft repository (locally-stored, unsent messages)."""

from __future__ import annotations

import json
import sqlite3

from ...domain.compose import DraftMessage, parse_address_list
from ._rows import last_id
from .base import Repository


def _draft_from_row(row: sqlite3.Row) -> DraftMessage:
    return DraftMessage(
        id=row["id"],
        account_id=row["account_id"],
        identity_id=row["identity_id"],
        from_addr="",  # resolved from identity when opened for editing
        to=parse_address_list(row["to_addrs"]),
        cc=parse_address_list(row["cc_addrs"]),
        bcc=parse_address_list(row["bcc_addrs"]),
        subject=row["subject"],
        body_text=row["body_text"],
        body_html=row["body_html"],
        attachments=list(json.loads(row["attachments_json"] or "[]")),
        in_reply_to=row["in_reply_to"],
    )


class DraftRepository(Repository):
    def save(self, draft: DraftMessage) -> DraftMessage:
        """Insert a new draft or update an existing one (by ``draft.id``)."""
        if draft.account_id is None:
            raise ValueError("Draft requires an account_id.")
        values = (
            draft.account_id,
            draft.identity_id,
            ", ".join(draft.to),
            ", ".join(draft.cc),
            ", ".join(draft.bcc),
            draft.subject,
            draft.body_text,
            draft.body_html,
            json.dumps(draft.attachments),
            draft.in_reply_to,
        )
        if draft.id is None:
            cur = self.conn.execute(
                """
                INSERT INTO drafts (
                    account_id, identity_id, to_addrs, cc_addrs, bcc_addrs,
                    subject, body_text, body_html, attachments_json, in_reply_to
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            draft.id = last_id(cur)
        else:
            self.conn.execute(
                """
                UPDATE drafts SET
                    account_id = ?, identity_id = ?, to_addrs = ?, cc_addrs = ?,
                    bcc_addrs = ?, subject = ?, body_text = ?, body_html = ?,
                    attachments_json = ?, in_reply_to = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (*values, draft.id),
            )
        return draft

    def get(self, draft_id: int) -> DraftMessage | None:
        row = self.conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        return _draft_from_row(row) if row else None

    def list_for_account(self, account_id: int) -> list[DraftMessage]:
        rows = self.conn.execute(
            "SELECT * FROM drafts WHERE account_id = ? ORDER BY updated_at DESC", (account_id,)
        ).fetchall()
        return [_draft_from_row(r) for r in rows]

    def delete(self, draft_id: int) -> None:
        self.conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
