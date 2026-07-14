from __future__ import annotations

import sqlite3

import pytest

from corvid.domain.entities import Account, ConnectionSecurity
from corvid.errors import AuthError
from corvid.infra.credentials import MemoryCredentialStore, account_service
from corvid.infra.repositories import AccountRepository, IdentityRepository
from corvid.service.accounts import AccountService


def _imap_account() -> Account:
    return Account(
        id=None, display_name="Alice", email="alice@example.com", username="alice",
        imap_host="imap.example.com", imap_port=993, imap_security=ConnectionSecurity.TLS,
        smtp_host="smtp.example.com", smtp_port=587,
        smtp_security=ConnectionSecurity.STARTTLS,
    )


class _OkStore:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True


class _FailStore:
    def connect(self) -> None:
        raise AuthError("Authentication failed. Please check your username and password.")

    def close(self) -> None:  # pragma: no cover - connect raises first
        pass


def _service(db: sqlite3.Connection, store) -> AccountService:  # type: ignore[no-untyped-def]
    return AccountService(
        AccountRepository(db),
        IdentityRepository(db),
        MemoryCredentialStore(),
        store_factory=lambda _a, _p: store,  # type: ignore[arg-type,return-value]
    )


def test_test_credentials_success(db: sqlite3.Connection) -> None:
    store = _OkStore()
    _service(db, store).test_credentials(_imap_account(), "correct-password")
    assert store.connected is True and store.closed is True  # connected and cleaned up


def test_test_credentials_failure_propagates(db: sqlite3.Connection) -> None:
    service = _service(db, _FailStore())
    with pytest.raises(AuthError):
        service.test_credentials(_imap_account(), "wrong-password")


def test_remove_account_deletes_account_and_credential(db: sqlite3.Connection) -> None:
    creds = MemoryCredentialStore()
    service = AccountService(AccountRepository(db), IdentityRepository(db), creds)
    saved = service.add_account(_imap_account(), "app-pw")
    assert saved.id is not None
    assert creds.get(account_service(saved.id), saved.username) == "app-pw"

    service.remove_account(saved)
    assert AccountRepository(db).list() == []
    assert creds.get(account_service(saved.id), saved.username) is None
