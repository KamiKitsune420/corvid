"""Conversation threading: group messages into reply-chains.

Pure logic, unit-tested without I/O. Messages are clustered by their
``In-Reply-To`` / ``References`` headers using a union-find: any two messages
linked (directly or transitively) by a shared Message-ID land in the same
thread. Messages whose reply headers reference nothing we hold stay on their own.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from .entities import Message

# A timezone-aware floor used to sort messages/threads that have no date.
_MIN = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Thread:
    """A conversation: one or more messages ordered oldest-first (original first)."""

    messages: tuple[Message, ...]

    @property
    def is_conversation(self) -> bool:
        """True when the thread holds more than one message (a real reply-chain)."""
        return len(self.messages) > 1

    @property
    def newest(self) -> Message:
        return self.messages[-1]

    @property
    def latest_date(self) -> datetime:
        return max((m.date_utc for m in self.messages if m.date_utc), default=_MIN)


def normalize_message_id(value: str) -> str:
    """Canonicalize a Message-ID for matching: strip ``<>``/space, casefold.

    Message-IDs are compared case-insensitively here; while the RFC treats the
    local part as case-sensitive, real-world servers rewrite case, and a genuine
    cross-case collision is vanishingly unlikely.
    """
    return value.strip().strip("<>").strip().casefold()


def parse_reference_ids(value: str) -> list[str]:
    """Split a ``References``/``In-Reply-To`` header into normalized Message-IDs."""
    tokens = value.replace(",", " ").split()
    ids = [normalize_message_id(token) for token in tokens]
    return [mid for mid in ids if mid]


def build_threads(messages: Iterable[Message]) -> list[Thread]:
    """Cluster ``messages`` into threads, newest-thread-first.

    Within a thread messages are ordered oldest-first (so the original sits at
    the top and replies follow). Threads are ordered by their most recent
    message, matching the newest-first order of a folder listing.
    """
    items = list(messages)
    n = len(items)
    parent = list(range(n))

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # path compression
            parent[x], x = root, parent[x]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    # Map every held Message-ID to the messages that carry it.
    by_id: dict[str, list[int]] = {}
    for i, message in enumerate(items):
        mid = normalize_message_id(message.message_id)
        if mid:
            by_id.setdefault(mid, []).append(i)

    # Link each message to any held message its reply headers point at.
    for i, message in enumerate(items):
        refs = parse_reference_ids(message.references)
        refs += parse_reference_ids(message.in_reply_to)
        for ref in refs:
            for j in by_id.get(ref, ()):
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    threads: list[Thread] = []
    for members in clusters.values():
        ordered = sorted(
            (items[k] for k in members),
            key=lambda m: (m.date_utc is None, m.date_utc or _MIN),
        )
        threads.append(Thread(messages=tuple(ordered)))

    threads.sort(key=lambda t: t.latest_date, reverse=True)
    return threads
