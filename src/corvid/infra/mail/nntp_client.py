"""A small NNTP client (RFC 3977) over stdlib sockets + TLS.

Written directly on ``socket``/``ssl`` rather than ``nntplib`` because the latter
is deprecated (3.11) and removed from the standard library in Python 3.13. Only
the commands Corvid needs are implemented: authentication, GROUP, OVER/XOVER,
ARTICLE, LIST ACTIVE, and POST. Transport and protocol failures are translated
into the :mod:`corvid.errors` taxonomy, mirroring the SMTP/IMAP adapters.
"""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from typing import IO

from ...domain.entities import ConnectionSecurity
from ...errors import AuthError, NetworkError, ProtocolError, TLSError


@dataclass(slots=True)
class GroupInfo:
    name: str
    count: int
    first: int
    last: int


@dataclass(slots=True)
class ActiveGroup:
    name: str
    last: int
    first: int
    posting: str  # 'y', 'n', or 'm' (moderated)


class NntpClient:
    """A connected NNTP session. Not thread-safe; one per worker connection."""

    def __init__(
        self,
        host: str,
        port: int,
        security: ConnectionSecurity,
        username: str = "",
        password: str = "",
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
        self._sock: socket.socket | None = None
        self._reader: IO[bytes] | None = None
        self.can_post = False

    # -- connection ---------------------------------------------------------
    def connect(self) -> None:
        try:
            raw = socket.create_connection((self._host, self._port), timeout=self._timeout)
            if self._security is ConnectionSecurity.TLS:
                raw = self._ssl_context.wrap_socket(raw, server_hostname=self._host)
            self._sock = raw
            self._reader = raw.makefile("rb")
            code, _ = self._read_status()
            self.can_post = code == 200
            if self._security is ConnectionSecurity.STARTTLS:
                self._starttls()
            if self._username:
                self._authenticate()
        except ssl.SSLError as exc:
            raise TLSError(str(exc)) from exc
        except (TimeoutError, OSError) as exc:
            raise NetworkError(str(exc)) from exc

    def _starttls(self) -> None:
        code, _ = self._command("STARTTLS")
        if code != 382:
            raise TLSError(f"Server refused STARTTLS ({code}).")
        assert self._sock is not None
        self._sock = self._ssl_context.wrap_socket(self._sock, server_hostname=self._host)
        self._reader = self._sock.makefile("rb")

    def _authenticate(self) -> None:
        code, _ = self._command(f"AUTHINFO USER {self._username}")
        if code == 281:
            return
        if code == 381:
            code, _ = self._command(f"AUTHINFO PASS {self._password}")
            if code == 281:
                return
        raise AuthError(f"NNTP authentication failed ({code}).")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._command("QUIT")
            except (OSError, ProtocolError):
                pass
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._reader = None

    def __enter__(self) -> NntpClient:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low-level I/O ------------------------------------------------------
    def _send(self, line: str) -> None:
        if self._sock is None:
            raise NetworkError("NNTP connection is not open.")
        try:
            self._sock.sendall(line.encode("utf-8") + b"\r\n")
        except OSError as exc:
            raise NetworkError(str(exc)) from exc

    def _read_line_bytes(self) -> bytes:
        assert self._reader is not None
        line = self._reader.readline()
        if not line:
            raise NetworkError("NNTP connection closed unexpectedly.")
        return line

    def _read_status(self) -> tuple[int, str]:
        line = self._read_line_bytes().decode("utf-8", "replace").rstrip("\r\n")
        try:
            return int(line[:3]), line[4:] if len(line) > 4 else ""
        except ValueError as exc:
            raise ProtocolError(f"Malformed NNTP response: {line!r}") from exc

    def _command(self, line: str) -> tuple[int, str]:
        self._send(line)
        return self._read_status()

    def _read_multiline(self) -> list[bytes]:
        """Read a dot-terminated block, undoing dot-stuffing; lines lack CRLF."""
        out: list[bytes] = []
        while True:
            raw = self._read_line_bytes()
            line = raw.rstrip(b"\r\n")
            if line == b".":
                return out
            if line.startswith(b".."):
                line = line[1:]
            out.append(line)

    # -- commands -----------------------------------------------------------
    def group(self, name: str) -> GroupInfo:
        code, text = self._command(f"GROUP {name}")
        if code != 211:
            raise ProtocolError(f"Cannot select group {name!r} ({code}).")
        parts = text.split()
        count, first, last = int(parts[0]), int(parts[1]), int(parts[2])
        return GroupInfo(name=name, count=count, first=first, last=last)

    def over(self, first: int, last: int) -> list[bytes]:
        """Return overview lines for articles ``first``..``last`` inclusive."""
        if last < first:
            return []
        code, _ = self._command(f"XOVER {first}-{last}")
        if code == 412:
            raise ProtocolError("No newsgroup selected for XOVER.")
        if code not in (224,):
            return []
        return self._read_multiline()

    def article(self, number: int) -> bytes:
        code, _ = self._command(f"ARTICLE {number}")
        if code != 220:
            raise ProtocolError(f"Article {number} unavailable ({code}).")
        return b"\r\n".join(self._read_multiline())

    def list_active(self, pattern: str | None = None) -> list[ActiveGroup]:
        cmd = "LIST ACTIVE" + (f" {pattern}" if pattern else "")
        code, _ = self._command(cmd)
        if code != 215:
            raise ProtocolError(f"LIST ACTIVE failed ({code}).")
        groups: list[ActiveGroup] = []
        for raw in self._read_multiline():
            parts = raw.decode("utf-8", "replace").split()
            if len(parts) >= 4:
                try:
                    groups.append(
                        ActiveGroup(parts[0], int(parts[1]), int(parts[2]), parts[3])
                    )
                except ValueError:
                    continue
        return groups

    def post(self, article: bytes) -> None:
        """Post a fully-formed article (headers + blank line + body)."""
        if not self.can_post:
            raise ProtocolError("This server does not permit posting.")
        code, _ = self._command("POST")
        if code != 340:
            raise ProtocolError(f"Server refused POST ({code}).")
        body = article.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        stuffed = b"\r\n".join(
            (b"." + line if line.startswith(b".") else line)
            for line in body.split(b"\r\n")
        )
        assert self._sock is not None
        try:
            self._sock.sendall(stuffed + b"\r\n.\r\n")
        except OSError as exc:
            raise NetworkError(str(exc)) from exc
        code, text = self._read_status()
        if code != 240:
            raise ProtocolError(f"Posting rejected ({code}): {text}")
