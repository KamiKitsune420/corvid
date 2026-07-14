from __future__ import annotations

from pathlib import Path

from corvid.infra.db import apply_migrations, connect, current_version
from corvid.infra.db.migrations import MIGRATIONS


def _table_names(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def test_fresh_database_applies_all(tmp_path: Path) -> None:
    conn = connect(tmp_path / "corvid.sqlite3")
    applied = apply_migrations(conn)
    assert applied == [m.version for m in MIGRATIONS]
    assert current_version(conn) == max(m.version for m in MIGRATIONS)

    tables = _table_names(conn)
    for expected in {"accounts", "identities", "folders", "messages", "attachments",
                     "contacts", "contact_emails", "rules", "app_meta"}:
        assert expected in tables
    conn.close()


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "corvid.sqlite3")
    assert apply_migrations(conn) == [m.version for m in MIGRATIONS]
    # Second run applies nothing and does not error.
    assert apply_migrations(conn) == []
    assert current_version(conn) == max(m.version for m in MIGRATIONS)
    conn.close()


def test_foreign_keys_enforced(tmp_path: Path) -> None:
    conn = connect(tmp_path / "corvid.sqlite3")
    apply_migrations(conn)
    row = conn.execute("PRAGMA foreign_keys").fetchone()
    assert row[0] == 1
    conn.close()
