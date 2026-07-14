"""POP3 receive adapter (stdlib ``poplib``).

POP3 has a single maildrop and no server-side folders or flags, so unlike IMAP it
does not implement the ``MailStore`` port. Messages are identified by their UIDL
(a stable per-message id); the caller passes the set of UIDLs already downloaded
so only new mail is retrieved. Optionally deletes messages from the server after
a successful download. Transport/auth failures map to the error taxonomy.
"""

from __future__ import annotations

import logging
import poplib
import ssl
from collections.abc import Iterator

from ...domain.entities import ConnectionSecurity
from ...errors import AuthError, NetworkError, ProtocolError, TLSError

log = logging.getLogger("corvid.pop3")


class Pop3Receiver:
    def __init__(
        self,
        host: str,
        port: int,
        security: ConnectionSecurity,
        username: str,
        password: str,
        *,
        timeout: float = 30.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._security = security
        self._username = username
        self._password = password
        self._timeout = timeout
        self._ssl_context = ssl_context or ssl.create_default_context()
        self._client: poplib.POP3 | None = None

    def connect(self) -> None:
        try:
            if self._security is ConnectionSecurity.TLS:
                client: poplib.POP3 = poplib.POP3_SSL(
                    self._host, self._port, timeout=self._timeout, context=self._ssl_context
                )
            else:
                client = poplib.POP3(self._host, self._port, timeout=self._timeout)
                if self._security is ConnectionSecurity.STARTTLS:
                    client.stls(context=self._ssl_context)
            self._client = client
        except ssl.SSLError as exc:
            raise TLSError(str(exc)) from exc
        except OSError as exc:
            raise NetworkError(str(exc)) from exc
        try:
            client.user(self._username)
            client.pass_(self._password)
        except poplib.error_proto as exc:
            raise AuthError(str(exc)) from exc

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.quit()  # QUIT commits pending DELEs
            except (poplib.error_proto, OSError):
                try:
                    self._client.close()
                except OSError:
                    pass
            finally:
                self._client = None

    def __enter__(self) -> Pop3Receiver:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _uidls(self) -> list[tuple[int, str]]:
        """Return (message_number, uidl) pairs for the maildrop."""
        assert self._client is not None
        try:
            _resp, lines, _ = self._client.uidl()
        except poplib.error_proto as exc:
            raise ProtocolError(f"POP3 UIDL not supported: {exc}") from exc
        pairs: list[tuple[int, str]] = []
        for line in lines:
            parts = line.split(maxsplit=1) if isinstance(line, str) else line.split(maxsplit=1)
            text = [p.decode() if isinstance(p, bytes) else p for p in parts]
            if len(text) == 2 and text[0].isdigit():
                pairs.append((int(text[0]), text[1]))
        return pairs

    def fetch_new(
        self, seen: set[str], *, delete: bool = False
    ) -> Iterator[tuple[str, bytes]]:
        """Yield (uidl, raw_bytes) for each message whose UIDL is not in ``seen``.

        With ``delete=True`` the message is marked for deletion on the server; the
        deletion is committed when :meth:`close` issues QUIT.
        """
        assert self._client is not None
        for number, uidl in self._uidls():
            if uidl in seen:
                continue
            try:
                _resp, lines, _ = self._client.retr(number)
            except poplib.error_proto as exc:
                log.warning("POP3 RETR %d failed: %s", number, exc)
                continue
            raw = b"\r\n".join(lines)
            yield uidl, raw
            if delete:
                try:
                    self._client.dele(number)
                except poplib.error_proto as exc:
                    log.warning("POP3 DELE %d failed: %s", number, exc)
