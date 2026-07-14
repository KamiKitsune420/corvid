from __future__ import annotations

import sqlite3

from corvid.domain.entities import Account, AuthMethod, ConnectionSecurity
from corvid.infra.credentials import MemoryCredentialStore, account_service
from corvid.infra.mail.imap_store import ImapMailStore
from corvid.infra.mail.smtp_sender import SmtpSender
from corvid.infra.oauth import GOOGLE, OAuthClient
from corvid.infra.repositories import AccountRepository, IdentityRepository
from corvid.service import accounts as accounts_module
from corvid.service.accounts import AccountService


def _oauth_account(db: sqlite3.Connection) -> Account:
    return AccountRepository(db).add(
        Account(
            id=None, display_name="Gmail user", email="me@gmail.com", username="me@gmail.com",
            imap_host="imap.gmail.com", imap_port=993, imap_security=ConnectionSecurity.TLS,
            smtp_host="smtp.gmail.com", smtp_port=587,
            smtp_security=ConnectionSecurity.STARTTLS, auth_method=AuthMethod.OAUTH2,
        )
    )


def _service(db: sqlite3.Connection, creds: MemoryCredentialStore) -> AccountService:
    return AccountService(
        AccountRepository(db),
        IdentityRepository(db),
        creds,
        oauth_clients={"google": OAuthClient(GOOGLE, "cid", "secret")},
    )


def test_open_store_uses_refreshed_access_token(
    db: sqlite3.Connection, monkeypatch
) -> None:
    account = _oauth_account(db)
    assert account.id is not None
    creds = MemoryCredentialStore()
    creds.set(account_service(account.id), account.username, "REFRESH")  # stored refresh token

    seen: dict[str, str] = {}

    def fake_refresh(client: OAuthClient, refresh_token: str) -> str:
        seen["client_id"] = client.client_id
        seen["refresh_token"] = refresh_token
        return "ACCESS-TOKEN"

    monkeypatch.setattr(accounts_module, "refresh_access_token", fake_refresh)

    store = _service(db, creds).open_store(account)
    assert isinstance(store, ImapMailStore)
    assert store._access_token == "ACCESS-TOKEN"  # type: ignore[attr-defined]
    assert store._username == "me@gmail.com"  # type: ignore[attr-defined]
    assert seen == {"client_id": "cid", "refresh_token": "REFRESH"}


def test_open_sender_uses_oauth(db: sqlite3.Connection, monkeypatch) -> None:
    account = _oauth_account(db)
    assert account.id is not None
    creds = MemoryCredentialStore()
    creds.set(account_service(account.id), account.username, "REFRESH")
    monkeypatch.setattr(accounts_module, "refresh_access_token", lambda c, r: "AT")

    sender = _service(db, creds).open_sender(account)
    assert isinstance(sender, SmtpSender)
    assert sender._access_token == "AT"  # type: ignore[attr-defined]


def test_open_store_without_configured_client_raises(db: sqlite3.Connection) -> None:
    account = _oauth_account(db)
    creds = MemoryCredentialStore()
    service = AccountService(
        AccountRepository(db), IdentityRepository(db), creds, oauth_clients={}
    )
    try:
        service.open_store(account)
    except Exception as exc:  # noqa: BLE001
        assert "not configured" in str(exc)
    else:
        raise AssertionError("expected a ValidationError when no OAuth client is set")
