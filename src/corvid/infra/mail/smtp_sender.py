"""SMTP implementation for outbound mail (stdlib ``smtplib``)."""

from __future__ import annotations

import base64
import smtplib
import ssl
from email.message import EmailMessage

from ...domain.entities import ConnectionSecurity
from ...errors import AuthError, NetworkError, ProtocolError, TLSError
from ..oauth import xoauth2


class SmtpSender:
    """Sends pre-built RFC 822 messages via SMTP."""

    def __init__(
        self,
        host: str,
        port: int,
        security: ConnectionSecurity,
        username: str,
        password: str,
        *,
        access_token: str = "",
        timeout: float = 30.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._security = security
        self._username = username
        self._password = password
        self._access_token = access_token
        self._timeout = timeout
        self._ssl_context = ssl_context or ssl.create_default_context()

    def _open(self) -> smtplib.SMTP:
        try:
            if self._security is ConnectionSecurity.TLS:
                return smtplib.SMTP_SSL(
                    self._host, self._port, timeout=self._timeout, context=self._ssl_context
                )
            client = smtplib.SMTP(self._host, self._port, timeout=self._timeout)
            if self._security is ConnectionSecurity.STARTTLS:
                client.starttls(context=self._ssl_context)
            return client
        except ssl.SSLError as exc:
            raise TLSError(str(exc)) from exc
        except OSError as exc:
            raise NetworkError(str(exc)) from exc

    def _auth_xoauth2(self, client: smtplib.SMTP) -> None:
        client.ehlo()
        token = base64.b64encode(xoauth2(self._username, self._access_token)).decode("ascii")
        code, resp = client.docmd("AUTH", "XOAUTH2 " + token)
        if code == 334:  # server returned a base64 error challenge; cancel and fail
            client.docmd("")
            raise AuthError("SMTP XOAUTH2 authentication was rejected.")
        if code != 235:
            raise AuthError(f"SMTP XOAUTH2 authentication failed ({code}): {resp!r}")

    def send(self, message: EmailMessage) -> None:
        """Authenticate and send a fully-formed message."""
        client = self._open()
        try:
            if self._access_token:
                self._auth_xoauth2(client)
            elif self._username:
                try:
                    client.login(self._username, self._password)
                except smtplib.SMTPAuthenticationError as exc:
                    raise AuthError(str(exc)) from exc
            client.send_message(message)
        except smtplib.SMTPException as exc:
            raise ProtocolError(str(exc)) from exc
        finally:
            try:
                client.quit()
            except smtplib.SMTPException:
                pass
