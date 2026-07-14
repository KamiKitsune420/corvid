"""Look up incoming/outgoing server settings from an email address.

A built-in table of the common consumer providers (Gmail, Outlook/Hotmail,
Yahoo, iCloud, ...) so a beginner can type just their email and have the IMAP/
SMTP/POP3 fields filled in automatically — the "autodiscovery-assisted wizard"
from the product spec. Pure and offline; no network required.

Several of these providers have **disabled plain-password IMAP/SMTP**, so the
entry records whether an **app password** (not the normal account password) is
required, plus a help URL the UI can link to.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.entities import ConnectionSecurity

_TLS = ConnectionSecurity.TLS
_STARTTLS = ConnectionSecurity.STARTTLS


@dataclass(slots=True, frozen=True)
class ProviderSettings:
    name: str
    imap_host: str
    imap_port: int
    imap_security: ConnectionSecurity
    smtp_host: str
    smtp_port: int
    smtp_security: ConnectionSecurity
    pop3_host: str = ""
    pop3_port: int = 995
    pop3_security: ConnectionSecurity = _TLS
    requires_app_password: bool = False
    help_url: str = ""
    oauth: str = ""  # OAuth provider key ('google' / 'microsoft'), or '' if none


def _provider(
    name: str,
    domains: tuple[str, ...],
    *,
    imap: tuple[str, int],
    smtp: tuple[str, int, ConnectionSecurity],
    pop3: tuple[str, int] | None = None,
    app_password: bool = False,
    help_url: str = "",
    oauth: str = "",
) -> tuple[tuple[str, ...], ProviderSettings]:
    settings = ProviderSettings(
        name=name,
        imap_host=imap[0],
        imap_port=imap[1],
        imap_security=_TLS,
        smtp_host=smtp[0],
        smtp_port=smtp[1],
        smtp_security=smtp[2],
        pop3_host=pop3[0] if pop3 else "",
        pop3_port=pop3[1] if pop3 else 995,
        requires_app_password=app_password,
        help_url=help_url,
        oauth=oauth,
    )
    return domains, settings


_TABLE: tuple[tuple[tuple[str, ...], ProviderSettings], ...] = (
    _provider(
        "Gmail", ("gmail.com", "googlemail.com"),
        imap=("imap.gmail.com", 993), smtp=("smtp.gmail.com", 587, _STARTTLS),
        pop3=("pop.gmail.com", 995), app_password=True,
        help_url="https://myaccount.google.com/apppasswords", oauth="google",
    ),
    _provider(
        "Outlook.com", ("outlook.com", "hotmail.com", "live.com", "msn.com", "hotmail.co.uk"),
        imap=("outlook.office365.com", 993), smtp=("smtp.office365.com", 587, _STARTTLS),
        pop3=("outlook.office365.com", 995), app_password=True, oauth="microsoft",
        help_url="https://support.microsoft.com/account-billing/"
        "using-app-passwords-with-apps-that-don-t-support-two-step-verification-"
        "5896ed9b-4263-e681-128a-a6f2979a7944",
    ),
    _provider(
        "Yahoo Mail", ("yahoo.com", "ymail.com", "yahoo.co.uk", "rocketmail.com"),
        imap=("imap.mail.yahoo.com", 993), smtp=("smtp.mail.yahoo.com", 465, _TLS),
        pop3=("pop.mail.yahoo.com", 995), app_password=True,
        help_url="https://help.yahoo.com/kb/SLN15241.html",
    ),
    _provider(
        "iCloud Mail", ("icloud.com", "me.com", "mac.com"),
        imap=("imap.mail.me.com", 993), smtp=("smtp.mail.me.com", 587, _STARTTLS),
        app_password=True, help_url="https://support.apple.com/en-us/102654",
    ),
    _provider(
        "AOL Mail", ("aol.com",),
        imap=("imap.aol.com", 993), smtp=("smtp.aol.com", 465, _TLS),
        pop3=("pop.aol.com", 995), app_password=True,
        help_url="https://help.aol.com/articles/Create-and-manage-app-password",
    ),
    _provider(
        "Fastmail", ("fastmail.com", "fastmail.fm"),
        imap=("imap.fastmail.com", 993), smtp=("smtp.fastmail.com", 465, _TLS),
        pop3=("pop.fastmail.com", 995), app_password=True,
        help_url="https://www.fastmail.help/hc/en-us/articles/360058752854",
    ),
    _provider(
        "GMX", ("gmx.com", "gmx.net", "gmx.de", "gmx.co.uk"),
        imap=("imap.gmx.com", 993), smtp=("mail.gmx.com", 587, _STARTTLS),
        pop3=("pop.gmx.com", 995),
    ),
    _provider(
        "Zoho Mail", ("zoho.com", "zohomail.com"),
        imap=("imap.zoho.com", 993), smtp=("smtp.zoho.com", 465, _TLS),
        pop3=("pop.zoho.com", 995),
    ),
)

_PROVIDERS: dict[str, ProviderSettings] = {
    domain: settings for domains, settings in _TABLE for domain in domains
}


def domain_of(email_or_domain: str) -> str:
    text = email_or_domain.strip().lower()
    return text.rsplit("@", 1)[-1] if "@" in text else text


def discover(email_or_domain: str) -> ProviderSettings | None:
    """Return known server settings for an email/domain, or ``None`` if unknown."""
    return _PROVIDERS.get(domain_of(email_or_domain))


def oauth_provider(email_or_domain: str) -> str:
    """Return the OAuth provider key for an email ('google'/'microsoft'), or ''."""
    settings = discover(email_or_domain)
    return settings.oauth if settings else ""
