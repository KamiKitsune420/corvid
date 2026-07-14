from __future__ import annotations

from corvid.domain.entities import ConnectionSecurity
from corvid.infra.autodiscovery import discover, domain_of


def test_domain_of() -> None:
    assert domain_of("Alice@Example.COM") == "example.com"
    assert domain_of("example.com") == "example.com"
    assert domain_of("  bob@gmail.com ") == "gmail.com"


def test_discover_gmail() -> None:
    s = discover("someone@gmail.com")
    assert s is not None
    assert s.name == "Gmail"
    assert (s.imap_host, s.imap_port, s.imap_security) == (
        "imap.gmail.com", 993, ConnectionSecurity.TLS,
    )
    assert (s.smtp_host, s.smtp_port, s.smtp_security) == (
        "smtp.gmail.com", 587, ConnectionSecurity.STARTTLS,
    )
    assert s.pop3_host == "pop.gmail.com"
    assert s.requires_app_password is True
    assert s.help_url.startswith("https://")


def test_discover_aliases_and_case() -> None:
    assert discover("x@googlemail.com").name == "Gmail"  # type: ignore[union-attr]
    assert discover("X@HOTMAIL.COM").name == "Outlook.com"  # type: ignore[union-attr]
    assert discover("y@ymail.com").name == "Yahoo Mail"  # type: ignore[union-attr]


def test_discover_unknown_returns_none() -> None:
    assert discover("nobody@example.com") is None
    assert discover("") is None


def test_gmx_does_not_require_app_password() -> None:
    s = discover("user@gmx.com")
    assert s is not None and s.requires_app_password is False
