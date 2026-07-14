"""Account and identity repositories."""

from __future__ import annotations

import sqlite3

from ...domain.entities import (
    Account,
    AccountKind,
    AuthMethod,
    ConnectionSecurity,
    Identity,
    ReceiveProtocol,
)
from ._rows import from_bool, last_id, text_to_dt, to_bool
from .base import Repository


def _account_from_row(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        display_name=row["display_name"],
        email=row["email"],
        username=row["username"],
        imap_host=row["imap_host"],
        imap_port=row["imap_port"],
        imap_security=ConnectionSecurity(row["imap_security"]),
        smtp_host=row["smtp_host"],
        smtp_port=row["smtp_port"],
        smtp_security=ConnectionSecurity(row["smtp_security"]),
        auth_method=AuthMethod(row["auth_method"]),
        kind=AccountKind(row["kind"]),
        receive_protocol=ReceiveProtocol(row["receive_protocol"]),
        nntp_host=row["nntp_host"],
        nntp_port=row["nntp_port"],
        nntp_security=ConnectionSecurity(row["nntp_security"]),
        pop3_host=row["pop3_host"],
        pop3_port=row["pop3_port"],
        pop3_security=ConnectionSecurity(row["pop3_security"]),
        pop3_leave_on_server=to_bool(row["pop3_leave_on_server"]),
        created_at=text_to_dt(row["created_at"]),
        updated_at=text_to_dt(row["updated_at"]),
    )


class AccountRepository(Repository):
    def add(self, account: Account) -> Account:
        cur = self.conn.execute(
            """
            INSERT INTO accounts (
                display_name, email, username,
                imap_host, imap_port, imap_security,
                smtp_host, smtp_port, smtp_security, auth_method,
                kind, receive_protocol, nntp_host, nntp_port, nntp_security,
                pop3_host, pop3_port, pop3_security, pop3_leave_on_server
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account.display_name,
                account.email,
                account.username,
                account.imap_host,
                account.imap_port,
                account.imap_security.value,
                account.smtp_host,
                account.smtp_port,
                account.smtp_security.value,
                account.auth_method.value,
                account.kind.value,
                account.receive_protocol.value,
                account.nntp_host,
                account.nntp_port,
                account.nntp_security.value,
                account.pop3_host,
                account.pop3_port,
                account.pop3_security.value,
                from_bool(account.pop3_leave_on_server),
            ),
        )
        row_id = last_id(cur)
        got = self.get(row_id)
        assert got is not None
        return got

    def get(self, account_id: int) -> Account | None:
        row = self.conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return _account_from_row(row) if row else None

    def list(self) -> list[Account]:
        rows = self.conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        return [_account_from_row(r) for r in rows]

    def update(self, account: Account) -> None:
        if account.id is None:
            raise ValueError("Cannot update an account without an id.")
        self.conn.execute(
            """
            UPDATE accounts SET
                display_name = ?, email = ?, username = ?,
                imap_host = ?, imap_port = ?, imap_security = ?,
                smtp_host = ?, smtp_port = ?, smtp_security = ?,
                auth_method = ?, kind = ?, receive_protocol = ?,
                nntp_host = ?, nntp_port = ?, nntp_security = ?,
                pop3_host = ?, pop3_port = ?, pop3_security = ?,
                pop3_leave_on_server = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                account.display_name,
                account.email,
                account.username,
                account.imap_host,
                account.imap_port,
                account.imap_security.value,
                account.smtp_host,
                account.smtp_port,
                account.smtp_security.value,
                account.auth_method.value,
                account.kind.value,
                account.receive_protocol.value,
                account.nntp_host,
                account.nntp_port,
                account.nntp_security.value,
                account.pop3_host,
                account.pop3_port,
                account.pop3_security.value,
                from_bool(account.pop3_leave_on_server),
                account.id,
            ),
        )

    def delete(self, account_id: int) -> None:
        self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


def _identity_from_row(row: sqlite3.Row) -> Identity:
    return Identity(
        id=row["id"],
        account_id=row["account_id"],
        display_name=row["display_name"],
        email=row["email"],
        reply_to=row["reply_to"],
        signature=row["signature"],
        is_default=to_bool(row["is_default"]),
    )


class IdentityRepository(Repository):
    def add(self, identity: Identity) -> Identity:
        cur = self.conn.execute(
            """
            INSERT INTO identities (
                account_id, display_name, email, reply_to, signature, is_default
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                identity.account_id,
                identity.display_name,
                identity.email,
                identity.reply_to,
                identity.signature,
                from_bool(identity.is_default),
            ),
        )
        identity.id = last_id(cur)
        return identity

    def list_for_account(self, account_id: int) -> list[Identity]:
        rows = self.conn.execute(
            "SELECT * FROM identities WHERE account_id = ? ORDER BY id", (account_id,)
        ).fetchall()
        return [_identity_from_row(r) for r in rows]

    def default_for_account(self, account_id: int) -> Identity | None:
        row = self.conn.execute(
            "SELECT * FROM identities WHERE account_id = ? ORDER BY is_default DESC, id LIMIT 1",
            (account_id,),
        ).fetchone()
        return _identity_from_row(row) if row else None

    def update(self, identity: Identity) -> None:
        if identity.id is None:
            raise ValueError("Cannot update an identity without an id.")
        self.conn.execute(
            """
            UPDATE identities SET display_name = ?, email = ?, reply_to = ?,
                signature = ?, is_default = ?
            WHERE id = ?
            """,
            (
                identity.display_name,
                identity.email,
                identity.reply_to,
                identity.signature,
                from_bool(identity.is_default),
                identity.id,
            ),
        )


__all__ = ["AccountRepository", "IdentityRepository"]
