from __future__ import annotations

import base64
import hashlib
import urllib.parse

import pytest

from corvid.errors import AuthError
from corvid.infra.oauth import (
    GOOGLE,
    MICROSOFT,
    OAuthClient,
    build_auth_url,
    exchange_code,
    make_pkce,
    parse_redirect,
    parse_token_response,
    refresh_access_token,
    xoauth2,
)


def test_make_pkce_is_valid_s256() -> None:
    verifier, challenge = make_pkce()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert challenge == expected


def test_build_auth_url_google() -> None:
    client = OAuthClient(GOOGLE, client_id="cid.apps.googleusercontent.com")
    url = build_auth_url(client, "http://127.0.0.1:5000", "st8", "chal")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["client_id"] == ["cid.apps.googleusercontent.com"]
    assert q["code_challenge"] == ["chal"] and q["code_challenge_method"] == ["S256"]
    assert q["scope"] == ["https://mail.google.com/"]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]  # refresh-token opts


def test_build_auth_url_microsoft_has_offline_scope() -> None:
    client = OAuthClient(MICROSOFT, client_id="app-guid")
    url = build_auth_url(client, "http://127.0.0.1:5000", "st", "chal")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert "offline_access" in q["scope"][0]
    assert "IMAP.AccessAsUser.All" in q["scope"][0]


def test_parse_redirect() -> None:
    assert parse_redirect("/?code=abc&state=xyz") == ("abc", "xyz")
    with pytest.raises(AuthError, match="denied"):
        parse_redirect("/?error=access_denied")
    with pytest.raises(AuthError, match="no code"):
        parse_redirect("/?state=only")


def test_parse_token_response() -> None:
    tokens = parse_token_response(
        {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}
    )
    assert tokens.access_token == "AT" and tokens.refresh_token == "RT"
    assert tokens.expires_in == 3600
    with pytest.raises(AuthError, match="missing access_token"):
        parse_token_response({"token_type": "Bearer"})
    with pytest.raises(AuthError, match="error"):
        parse_token_response({"error": "invalid_grant"})


def test_xoauth2_format() -> None:
    raw = xoauth2("me@gmail.com", "tok123")
    assert raw == b"user=me@gmail.com\x01auth=Bearer tok123\x01\x01"


def test_exchange_code_includes_pkce_and_secret() -> None:
    seen: dict[str, str] = {}

    def fake_post(url: str, form: dict[str, str]) -> dict[str, object]:
        seen.update(form)
        seen["_url"] = url
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    client = OAuthClient(GOOGLE, client_id="cid", client_secret="sec")
    tokens = exchange_code(client, "code1", "verifier1", "http://127.0.0.1:9", post=fake_post)
    assert tokens.refresh_token == "RT"
    assert seen["grant_type"] == "authorization_code"
    assert seen["code"] == "code1" and seen["code_verifier"] == "verifier1"
    assert seen["client_secret"] == "sec"  # Google uses the secret
    assert seen["_url"] == GOOGLE.token_url


def test_exchange_code_microsoft_omits_secret() -> None:
    seen: dict[str, str] = {}

    def fake_post(url: str, form: dict[str, str]) -> dict[str, object]:
        seen.update(form)
        return {"access_token": "AT", "refresh_token": "RT"}

    client = OAuthClient(MICROSOFT, client_id="app", client_secret="ignored")
    exchange_code(client, "c", "v", "http://127.0.0.1:9", post=fake_post)
    assert "client_secret" not in seen  # public client


def test_refresh_access_token() -> None:
    def fake_post(url: str, form: dict[str, str]) -> dict[str, object]:
        assert form["grant_type"] == "refresh_token"
        assert form["refresh_token"] == "RT"
        return {"access_token": "AT2", "expires_in": 3600}

    client = OAuthClient(GOOGLE, client_id="cid", client_secret="sec")
    assert refresh_access_token(client, "RT", post=fake_post) == "AT2"
