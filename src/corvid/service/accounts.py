"""Account management use-cases."""

from __future__ import annotations

from collections.abc import Callable

from ..domain.entities import Account, AccountKind, AuthMethod, Identity, ReceiveProtocol
from ..errors import ValidationError
from ..infra.autodiscovery import oauth_provider
from ..infra.credentials import CredentialStore, account_service
from ..infra.mail.base import MailStore
from ..infra.mail.imap_store import ImapMailStore
from ..infra.mail.nntp_client import NntpClient
from ..infra.mail.nntp_store import NntpMailStore
from ..infra.mail.pop3_receiver import Pop3Receiver
from ..infra.mail.smtp_sender import SmtpSender
from ..infra.oauth import OAuthClient, refresh_access_token
from ..infra.repositories import AccountRepository, IdentityRepository

StoreFactory = Callable[[Account, str], MailStore]


def _default_store_factory(account: Account, password: str) -> MailStore:
    return ImapMailStore(
        host=account.imap_host,
        port=account.imap_port,
        security=account.imap_security,
        username=account.username,
        password=password,
    )


class AccountService:
    def __init__(
        self,
        accounts: AccountRepository,
        identities: IdentityRepository,
        credentials: CredentialStore,
        *,
        store_factory: StoreFactory | None = None,
        oauth_clients: dict[str, OAuthClient] | None = None,
    ) -> None:
        self._accounts = accounts
        self._identities = identities
        self._credentials = credentials
        self._store_factory = store_factory or _default_store_factory
        self._oauth_clients = oauth_clients or {}

    def add_account(
        self, account: Account, password: str, *, create_default_identity: bool = True
    ) -> Account:
        if not account.email or "@" not in account.email:
            raise ValidationError(f"Invalid email address: {account.email!r}")
        if account.kind is AccountKind.NEWS:
            if not account.nntp_host:
                raise ValidationError("A news (NNTP) server host is required.")
        elif account.receive_protocol is ReceiveProtocol.POP3:
            if not account.pop3_host or not account.smtp_host:
                raise ValidationError("Both POP3 and SMTP hosts are required.")
        elif not account.imap_host or not account.smtp_host:
            raise ValidationError("Both IMAP and SMTP hosts are required.")

        saved = self._accounts.add(account)
        assert saved.id is not None
        if password or account.username:
            self._credentials.set(account_service(saved.id), saved.username, password)
        if create_default_identity:
            self._identities.add(
                Identity(
                    id=None,
                    account_id=saved.id,
                    display_name=saved.display_name,
                    email=saved.email,
                    is_default=True,
                )
            )
        return saved

    def password_for(self, account: Account) -> str | None:
        if account.id is None:
            return None
        return self._credentials.get(account_service(account.id), account.username)

    def remove_account(self, account: Account) -> None:
        if account.id is None:
            return
        self._credentials.delete(account_service(account.id), account.username)
        self._accounts.delete(account.id)

    # -- OAuth --------------------------------------------------------------
    def _oauth_access_token(self, account: Account) -> str:
        """Exchange the stored refresh token for a fresh access token."""
        client = self._oauth_clients.get(oauth_provider(account.email))
        if client is None:
            raise ValidationError(
                f"OAuth is not configured for {account.email}.",
                user_message=(
                    "Sign-in for this provider isn't set up. Add its OAuth client "
                    "ID in Settings first."
                ),
            )
        refresh_token = self.password_for(account)
        if not refresh_token:
            raise ValidationError("No stored sign-in token; sign in again.")
        return refresh_access_token(client, refresh_token)

    def test_credentials(self, account: Account, password: str) -> None:
        """Connect and authenticate with the given password; raise on failure.

        Used to verify an account before saving it. Tests the receive side (IMAP,
        POP3, or NNTP); the outgoing SMTP server typically shares these
        credentials. Raises an :class:`~corvid.errors.CorvidError` subclass
        (auth/TLS/network/protocol) if the connection or login fails.
        """
        if account.kind is AccountKind.NEWS:
            client = NntpClient(
                host=account.nntp_host,
                port=account.nntp_port,
                security=account.nntp_security,
                username=account.username,
                password=password,
            )
            client.connect()
            client.close()
            return
        if account.receive_protocol is ReceiveProtocol.POP3:
            receiver = Pop3Receiver(
                host=account.pop3_host,
                port=account.pop3_port,
                security=account.pop3_security,
                username=account.username,
                password=password,
            )
            receiver.connect()
            receiver.close()
            return
        store = self._store_factory(account, password)
        store.connect()
        store.close()

    # -- adapters -----------------------------------------------------------
    def open_store(self, account: Account) -> MailStore:
        if account.auth_method is AuthMethod.OAUTH2:
            return ImapMailStore(
                host=account.imap_host,
                port=account.imap_port,
                security=account.imap_security,
                username=account.email,
                password="",
                access_token=self._oauth_access_token(account),
            )
        password = self.password_for(account)
        if password is None:
            raise ValidationError("No stored password for this account.")
        return self._store_factory(account, password)

    def open_news_store(
        self, account: Account, subscribed: list[str] | None = None
    ) -> NntpMailStore:
        """Build an NNTP-backed store. Auth is used only if a username is set."""
        password = self.password_for(account) or "" if account.username else ""
        client = NntpClient(
            host=account.nntp_host,
            port=account.nntp_port,
            security=account.nntp_security,
            username=account.username,
            password=password,
        )
        return NntpMailStore(client, subscribed or [])

    def open_pop3_receiver(self, account: Account) -> Pop3Receiver:
        password = self.password_for(account)
        if password is None:
            raise ValidationError("No stored password for this account.")
        return Pop3Receiver(
            host=account.pop3_host,
            port=account.pop3_port,
            security=account.pop3_security,
            username=account.username,
            password=password,
        )

    def open_sender(self, account: Account) -> SmtpSender:
        if account.auth_method is AuthMethod.OAUTH2:
            return SmtpSender(
                host=account.smtp_host,
                port=account.smtp_port,
                security=account.smtp_security,
                username=account.email,
                password="",
                access_token=self._oauth_access_token(account),
            )
        password = self.password_for(account)
        if password is None:
            raise ValidationError("No stored password for this account.")
        return SmtpSender(
            host=account.smtp_host,
            port=account.smtp_port,
            security=account.smtp_security,
            username=account.username,
            password=password,
        )
