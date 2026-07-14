"""Contact (address book) repository."""

from __future__ import annotations

import builtins
import sqlite3

from ...domain.entities import Contact, EmailAddress
from ._rows import from_bool, last_id
from .base import Repository


def _emails_for(conn: sqlite3.Connection, contact_id: int) -> builtins.list[EmailAddress]:
    rows = conn.execute(
        "SELECT email, label, is_primary FROM contact_emails "
        "WHERE contact_id = ? ORDER BY is_primary DESC, id",
        (contact_id,),
    ).fetchall()
    return [EmailAddress(address=r["email"], name=r["label"]) for r in rows]


def _contact_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> Contact:
    return Contact(
        id=row["id"],
        display_name=row["display_name"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        organization=row["organization"],
        notes=row["notes"],
        emails=_emails_for(conn, row["id"]),
    )


class ContactRepository(Repository):
    def add(self, contact: Contact) -> Contact:
        cur = self.conn.execute(
            """
            INSERT INTO contacts (display_name, first_name, last_name, organization, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                contact.display_name,
                contact.first_name,
                contact.last_name,
                contact.organization,
                contact.notes,
            ),
        )
        contact.id = last_id(cur)
        self._replace_emails(contact.id, contact.emails)
        return contact

    def update(self, contact: Contact) -> None:
        if contact.id is None:
            raise ValueError("Cannot update a contact without an id.")
        self.conn.execute(
            """
            UPDATE contacts SET display_name = ?, first_name = ?, last_name = ?,
                organization = ?, notes = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                contact.display_name,
                contact.first_name,
                contact.last_name,
                contact.organization,
                contact.notes,
                contact.id,
            ),
        )
        self._replace_emails(contact.id, contact.emails)

    def _replace_emails(self, contact_id: int, emails: builtins.list[EmailAddress]) -> None:
        self.conn.execute("DELETE FROM contact_emails WHERE contact_id = ?", (contact_id,))
        for index, email in enumerate(emails):
            self.conn.execute(
                """
                INSERT INTO contact_emails (contact_id, email, label, is_primary)
                VALUES (?, ?, ?, ?)
                """,
                (contact_id, email.address, email.name, from_bool(index == 0)),
            )

    def get(self, contact_id: int) -> Contact | None:
        row = self.conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        return _contact_from_row(self.conn, row) if row else None

    def list(self) -> builtins.list[Contact]:
        rows = self.conn.execute(
            "SELECT * FROM contacts ORDER BY display_name COLLATE NOCASE"
        ).fetchall()
        return [_contact_from_row(self.conn, r) for r in rows]

    def find_by_email(self, email: str) -> Contact | None:
        row = self.conn.execute(
            "SELECT c.* FROM contacts c JOIN contact_emails e ON e.contact_id = c.id "
            "WHERE e.email = ? COLLATE NOCASE LIMIT 1",
            (email,),
        ).fetchone()
        return _contact_from_row(self.conn, row) if row else None

    def search(self, prefix: str, *, limit: int = 20) -> builtins.list[tuple[str, str]]:
        """Return (display_name, email) pairs matching a name/email prefix."""
        rows = self.conn.execute(
            """
            SELECT c.display_name AS name, e.email AS email
            FROM contact_emails e JOIN contacts c ON c.id = e.contact_id
            WHERE e.email LIKE ? COLLATE NOCASE OR c.display_name LIKE ? COLLATE NOCASE
            ORDER BY c.display_name COLLATE NOCASE
            LIMIT ?
            """,
            (f"{prefix}%", f"%{prefix}%", limit),
        ).fetchall()
        return [(r["name"], r["email"]) for r in rows]

    def delete(self, contact_id: int) -> None:
        self.conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
