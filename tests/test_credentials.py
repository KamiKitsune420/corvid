from __future__ import annotations

import sys
from pathlib import Path

import pytest

from corvid.infra.credentials import (
    DpapiCredentialStore,
    MemoryCredentialStore,
    account_service,
    get_default_store,
)


def test_memory_store_roundtrip() -> None:
    store = MemoryCredentialStore()
    store.set("svc", "alice", "hunter2")
    assert store.get("svc", "alice") == "hunter2"
    store.delete("svc", "alice")
    assert store.get("svc", "alice") is None


def test_account_service_key() -> None:
    assert account_service(7) == "corvid.account.7"


def test_get_default_store_returns_store(tmp_path: Path) -> None:
    store = get_default_store(tmp_path)
    assert hasattr(store, "get") and hasattr(store, "set")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="DPAPI is Windows-only")
def test_dpapi_roundtrip(tmp_path: Path) -> None:
    store = DpapiCredentialStore(tmp_path / "credentials.json")
    store.set(account_service(1), "alice", "s3cret-päss")
    # Persisted on disk, protected (not plaintext).
    blob = (tmp_path / "credentials.json").read_text(encoding="utf-8")
    assert "s3cret" not in blob
    # New instance reads it back (same user context).
    assert DpapiCredentialStore(tmp_path / "credentials.json").get(
        account_service(1), "alice"
    ) == "s3cret-päss"
    store.delete(account_service(1), "alice")
    assert store.get(account_service(1), "alice") is None
