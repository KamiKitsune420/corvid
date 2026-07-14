"""A ``MailStore`` backed by NNTP, so newsgroups reuse the mail sync machinery.

Newsgroups map onto folders and articles onto messages: an article's *number*
plays the role of a UID, GROUP provides the folder status, XOVER supplies header
envelopes, and ARTICLE fetches the raw body. This lets :class:`SyncService` and
:class:`MessageBodyService` drive news exactly as they drive IMAP mail. Server-
side flag/move/delete operations are no-ops — news has no per-user server state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parseaddr, parsedate_to_datetime

from ...errors import ProtocolError
from .nntp_client import NntpClient
from .types import FolderInfo, FolderStatus, HeaderEnvelope

# XOVER field order (RFC 3977 §8.3 default): number, Subject, From, Date,
# Message-ID, References, :bytes, :lines, [extra headers...].
_OV_SUBJECT = 1
_OV_FROM = 2
_OV_DATE = 3
_OV_MESSAGE_ID = 4
_OV_BYTES = 6


def parse_overview_line(line: bytes) -> HeaderEnvelope | None:
    """Parse one tab-separated XOVER line into a :class:`HeaderEnvelope`."""
    fields = line.decode("utf-8", "replace").split("\t")
    if not fields or not fields[0].strip().isdigit():
        return None
    number = int(fields[0].strip())

    def field(index: int) -> str:
        return fields[index] if index < len(fields) else ""

    from_name, from_addr = parseaddr(field(_OV_FROM))
    date_utc: datetime | None = None
    raw_date = field(_OV_DATE)
    if raw_date:
        try:
            parsed = parsedate_to_datetime(raw_date)
            if parsed is not None:
                date_utc = (
                    parsed.replace(tzinfo=UTC)
                    if parsed.tzinfo is None
                    else parsed.astimezone(UTC)
                )
        except (TypeError, ValueError):
            date_utc = None
    try:
        size = int(field(_OV_BYTES) or 0)
    except ValueError:
        size = 0

    return HeaderEnvelope(
        uid=number,
        message_id=field(_OV_MESSAGE_ID).strip(),
        subject=field(_OV_SUBJECT),
        from_name=from_name,
        from_addr=from_addr,
        date_utc=date_utc,
        size=size,
    )


class NntpMailStore:
    """Adapts an :class:`NntpClient` to the ``MailStore`` port for subscribed groups."""

    def __init__(
        self,
        client: NntpClient,
        subscribed: list[str] | None = None,
        *,
        initial_limit: int = 500,
    ) -> None:
        self._client = client
        self._subscribed = subscribed or []
        self._initial_limit = initial_limit
        self._current: tuple[int, int] | None = None  # (first, last) of selected group

    # -- MailStore ----------------------------------------------------------
    def connect(self) -> None:
        self._client.connect()

    def close(self) -> None:
        self._client.close()

    def list_folders(self) -> list[FolderInfo]:
        return [
            FolderInfo(remote_name=g, display_name=g, is_newsgroup=True)
            for g in self._subscribed
        ]

    def select(self, remote_name: str, *, readonly: bool = True) -> FolderStatus:
        info = self._client.group(remote_name)
        self._current = (info.first, info.last)
        # News has no UIDVALIDITY; article numbers are stable within a group.
        return FolderStatus(uidvalidity=1, uidnext=info.last + 1, exists=info.count)

    def search_uids(self, min_uid: int | None = None) -> list[int]:
        if self._current is None:
            raise ProtocolError("No newsgroup selected.")
        first, last = self._current
        if min_uid is None:
            start = max(first, last - self._initial_limit + 1)
        else:
            start = max(first, min_uid + 1)
        return list(range(start, last + 1))

    def fetch_headers(self, uids: list[int]) -> list[HeaderEnvelope]:
        if not uids:
            return []
        wanted = set(uids)
        envelopes: list[HeaderEnvelope] = []
        for raw in self._client.over(min(uids), max(uids)):
            env = parse_overview_line(raw)
            if env is not None and env.uid in wanted:
                envelopes.append(env)
        return envelopes

    def fetch_raw(self, uid: int) -> bytes:
        return self._client.article(uid)

    def store_flags(self, uid: int, flags: tuple[str, ...], *, add: bool) -> None:
        return None  # news has no server-side per-user flags

    def move(self, uid: int, dest_remote_name: str) -> None:
        return None

    def delete(self, uid: int) -> None:
        return None

    def __enter__(self) -> NntpMailStore:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- news-specific ------------------------------------------------------
    def list_groups(self, pattern: str | None = None) -> list[str]:
        return sorted(g.name for g in self._client.list_active(pattern))

    def post(self, article: bytes) -> None:
        self._client.post(article)
