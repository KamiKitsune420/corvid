"""IMAP implementation of the mail-store port (stdlib ``imaplib``)."""

from __future__ import annotations

import imaplib
import re
import ssl
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import formataddr, getaddresses, parseaddr, parsedate_to_datetime

from ...domain.entities import ConnectionSecurity
from ...errors import AuthError, NetworkError, ProtocolError, TLSError
from ..oauth import xoauth2
from .types import FolderInfo, FolderStatus, HeaderEnvelope

_LIST_RE = re.compile(rb'\((?P<flags>[^)]*)\)\s+(?P<delim>"[^"]*"|NIL)\s+(?P<name>"[^"]*"|\S+)')
_UID_RE = re.compile(rb"UID\s+(\d+)")
_SIZE_RE = re.compile(rb"RFC822\.SIZE\s+(\d+)")
_FLAGS_RE = re.compile(rb"FLAGS\s+\(([^)]*)\)")

_SPECIAL_USE_FLAGS = {"\\sent", "\\drafts", "\\trash", "\\junk", "\\archive", "\\all", "\\flagged"}
_HEADER_FIELDS = (
    "DATE FROM TO CC SUBJECT MESSAGE-ID CONTENT-TYPE IN-REPLY-TO REFERENCES"
)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 - malformed encodings degrade gracefully
        return value


def _unquote(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def parse_list_line(line: bytes) -> FolderInfo | None:
    """Parse one IMAP LIST response line into a :class:`FolderInfo`."""
    match = _LIST_RE.search(line)
    if not match:
        return None
    flags = tuple(f.decode("ascii", "replace") for f in match.group("flags").split())
    delim_raw = match.group("delim")
    delimiter = "/" if delim_raw == b"NIL" else _unquote(delim_raw)
    name = _unquote(match.group("name"))
    special = next((f for f in flags if f.lower() in _SPECIAL_USE_FLAGS), None)
    if special is None and name.upper() == "INBOX":
        special = "\\Inbox"
    display = name.rsplit(delimiter, 1)[-1] if delimiter and delimiter in name else name
    return FolderInfo(
        remote_name=name,
        display_name=display,
        delimiter=delimiter,
        flags=flags,
        special_use=special,
    )


def parse_envelope(meta: bytes, header_bytes: bytes) -> HeaderEnvelope:
    """Build a :class:`HeaderEnvelope` from a FETCH metadata blob + header bytes."""
    uid_match = _UID_RE.search(meta)
    uid = int(uid_match.group(1)) if uid_match else 0
    size_match = _SIZE_RE.search(meta)
    size = int(size_match.group(1)) if size_match else 0
    flags_match = _FLAGS_RE.search(meta)
    flags = (
        frozenset(f.decode("ascii", "replace") for f in flags_match.group(1).split())
        if flags_match
        else frozenset()
    )

    msg = message_from_bytes(header_bytes)
    from_name, from_addr = parseaddr(msg.get("From", ""))
    to_addrs = ", ".join(
        formataddr((_decode(n), a)) for n, a in getaddresses(msg.get_all("To", []))
    )
    cc_addrs = ", ".join(
        formataddr((_decode(n), a)) for n, a in getaddresses(msg.get_all("Cc", []))
    )
    date_utc = None
    raw_date = msg.get("Date")
    if raw_date:
        try:
            date_utc = parsedate_to_datetime(raw_date)
        except (TypeError, ValueError):
            date_utc = None
    content_type = (msg.get("Content-Type") or "").lower()
    has_attachments = "multipart/mixed" in content_type

    return HeaderEnvelope(
        uid=uid,
        message_id=(msg.get("Message-ID") or "").strip(),
        subject=_decode(msg.get("Subject")),
        in_reply_to=(msg.get("In-Reply-To") or "").strip(),
        references=" ".join(str(msg.get("References") or "").split()),
        from_name=_decode(from_name),
        from_addr=from_addr,
        to_addrs=to_addrs,
        cc_addrs=cc_addrs,
        date_utc=date_utc,
        size=size,
        has_attachments=has_attachments,
        flags=flags,
    )


def parse_fetch_response(data: list[object]) -> list[HeaderEnvelope]:
    """Parse the payload of ``imap.uid('FETCH', ...)`` into envelopes."""
    envelopes: list[HeaderEnvelope] = []
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            meta, header_bytes = item[0], item[1]
            if isinstance(meta, bytes) and isinstance(header_bytes, bytes):
                envelopes.append(parse_envelope(meta, header_bytes))
    return envelopes


class ImapMailStore:
    """A connected IMAP mailbox implementing the :class:`MailStore` protocol."""

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
        self._imap: imaplib.IMAP4 | None = None

    # -- lifecycle ----------------------------------------------------------
    def connect(self) -> None:
        try:
            if self._security is ConnectionSecurity.TLS:
                self._imap = imaplib.IMAP4_SSL(
                    self._host, self._port, ssl_context=self._ssl_context, timeout=self._timeout
                )
            else:
                imap = imaplib.IMAP4(self._host, self._port, timeout=self._timeout)
                if self._security is ConnectionSecurity.STARTTLS:
                    imap.starttls(ssl_context=self._ssl_context)
                self._imap = imap
        except ssl.SSLError as exc:
            raise TLSError(str(exc)) from exc
        except OSError as exc:
            raise NetworkError(str(exc)) from exc

        try:
            if self._access_token:
                self._imap.authenticate(
                    "XOAUTH2", lambda _challenge: xoauth2(self._username, self._access_token)
                )
            else:
                self._imap.login(self._username, self._password)
        except imaplib.IMAP4.error as exc:
            raise AuthError(str(exc)) from exc

    def close(self) -> None:
        if self._imap is None:
            return
        try:
            self._imap.logout()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass
        finally:
            self._imap = None

    def __enter__(self) -> ImapMailStore:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- operations ---------------------------------------------------------
    @property
    def _client(self) -> imaplib.IMAP4:
        if self._imap is None:
            raise NetworkError("IMAP store is not connected.")
        return self._imap

    def list_folders(self) -> list[FolderInfo]:
        typ, data = self._client.list()
        if typ != "OK":
            raise ProtocolError(f"LIST failed: {typ}")
        folders: list[FolderInfo] = []
        for line in data:
            if isinstance(line, bytes):
                info = parse_list_line(line)
                if info is not None:
                    folders.append(info)
        return folders

    def select(self, remote_name: str, *, readonly: bool = True) -> FolderStatus:
        typ, data = self._client.status(
            self._quote(remote_name), "(UIDVALIDITY UIDNEXT MESSAGES)"
        )
        if typ != "OK" or not data or not isinstance(data[0], bytes):
            raise ProtocolError(f"STATUS failed for {remote_name!r}: {typ}")
        status = self._parse_status(data[0])
        sel_typ, _ = self._client.select(self._quote(remote_name), readonly=readonly)
        if sel_typ != "OK":
            raise ProtocolError(f"SELECT failed for {remote_name!r}: {sel_typ}")
        return status

    def search_uids(self, min_uid: int | None = None) -> list[int]:
        criterion = "ALL" if min_uid is None else f"UID {min_uid + 1}:*"
        typ, data = self._client.uid("SEARCH", criterion)
        if typ != "OK":
            raise ProtocolError(f"SEARCH failed: {typ}")
        if not data or not data[0]:
            return []
        raw = data[0] if isinstance(data[0], bytes) else b""
        uids = sorted(int(tok) for tok in raw.split())
        if min_uid is not None:
            uids = [u for u in uids if u > min_uid]  # n:* may echo the last UID
        return uids

    def append(
        self, remote_name: str, message_bytes: bytes, *, flags: tuple[str, ...] = ("\\Seen",)
    ) -> None:
        """Append a message to a mailbox (e.g. record a sent message in Sent)."""
        flag_str = f"({' '.join(flags)})" if flags else None
        typ, _ = self._client.append(self._quote(remote_name), flag_str, None, message_bytes)
        if typ != "OK":
            raise ProtocolError(f"APPEND failed for {remote_name!r}: {typ}")

    def fetch_headers(self, uids: list[int]) -> list[HeaderEnvelope]:
        if not uids:
            return []
        spec = f"(UID FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS ({_HEADER_FIELDS})])"
        typ, data = self._client.uid("FETCH", ",".join(str(u) for u in uids), spec)
        if typ != "OK":
            raise ProtocolError(f"FETCH failed: {typ}")
        return parse_fetch_response(data)

    def fetch_raw(self, uid: int) -> bytes:
        typ, data = self._client.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if typ != "OK":
            raise ProtocolError(f"FETCH (body) failed for UID {uid}: {typ}")
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return item[1]
        raise ProtocolError(f"No body returned for UID {uid}")

    def store_flags(self, uid: int, flags: tuple[str, ...], *, add: bool) -> None:
        """Add or remove IMAP flags on a message (the mailbox must be selected
        read-write)."""
        op = "+FLAGS.SILENT" if add else "-FLAGS.SILENT"
        typ, _ = self._client.uid("STORE", str(uid), op, f"({' '.join(flags)})")
        if typ != "OK":
            raise ProtocolError(f"STORE failed for UID {uid}: {typ}")

    def move(self, uid: int, dest_remote_name: str) -> None:
        """Move a message to another mailbox (UID MOVE, with a COPY+delete fallback)."""
        dest = self._quote(dest_remote_name)
        try:
            typ, _ = self._client.uid("MOVE", str(uid), dest)
            if typ == "OK":
                return
        except imaplib.IMAP4.error:
            pass  # server lacks the MOVE extension; fall back
        typ, _ = self._client.uid("COPY", str(uid), dest)
        if typ != "OK":
            raise ProtocolError(f"COPY failed for UID {uid}: {typ}")
        self.delete(uid)

    def delete(self, uid: int) -> None:
        """Flag a message \\Deleted and expunge it (mailbox must be read-write)."""
        self.store_flags(uid, ("\\Deleted",), add=True)
        try:
            self._client.uid("EXPUNGE", str(uid))  # UIDPLUS (RFC 4315)
        except imaplib.IMAP4.error:
            self._client.expunge()  # fallback: expunge all \Deleted in the mailbox

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _quote(name: str) -> str:
        return f'"{name}"' if " " in name or not name else name

    @staticmethod
    def _parse_status(raw: bytes) -> FolderStatus:
        def field(key: str) -> int:
            m = re.search(rf"{key}\s+(\d+)".encode(), raw)
            return int(m.group(1)) if m else 0

        return FolderStatus(
            uidvalidity=field("UIDVALIDITY"),
            uidnext=field("UIDNEXT"),
            exists=field("MESSAGES"),
        )
