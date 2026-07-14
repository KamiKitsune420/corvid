from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from corvid.app.paths import AppPaths, paths_for_root
from corvid.infra.db import apply_migrations, connect


@pytest.fixture()
def tmp_paths(tmp_path: Path) -> AppPaths:
    return paths_for_root(tmp_path).ensure()


@pytest.fixture()
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(tmp_path / "corvid.sqlite3")
    apply_migrations(conn)
    yield conn
    conn.close()
