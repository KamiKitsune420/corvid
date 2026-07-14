"""Message body retrieval: fetch on demand, cache on disk, parse for display."""

from __future__ import annotations

import logging
from pathlib import Path

from ..domain.entities import Message
from ..infra.mail.base import MailStore
from ..infra.mail.parsing import ParsedMessage, parse_message
from ..infra.repositories import MessageRepository

log = logging.getLogger("corvid.body")


class MessageBodyService:
    """Downloads and caches full message bodies, returning a parsed view.

    Raw RFC 822 bytes are cached under ``messages_dir`` as ``<id>.eml`` so a
    message is fetched from the server at most once.
    """

    def __init__(self, messages: MessageRepository, messages_dir: Path) -> None:
        self._messages = messages
        self._dir = messages_dir

    def cached_path(self, message: Message) -> Path:
        if message.raw_path:
            return Path(message.raw_path)
        return self._dir / f"{message.id}.eml"

    def get_cached(self, message: Message) -> ParsedMessage | None:
        """Return the parsed body if already downloaded, else None."""
        if not message.body_fetched:
            return None
        path = self.cached_path(message)
        if not path.exists():
            return None
        return parse_message(path.read_bytes())

    def fetch_and_cache(self, message: Message, store: MailStore) -> ParsedMessage:
        """Download the body via a connected store, cache it, and parse it."""
        if message.id is None or message.uid is None:
            raise ValueError("Message must be persisted with a UID to fetch its body.")
        raw = store.fetch_raw(message.uid)
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{message.id}.eml"
        path.write_bytes(raw)
        self._messages.mark_body_fetched(message.id, str(path))
        message.body_fetched = True
        message.raw_path = str(path)
        log.info("cached body for message %d (%d bytes)", message.id, len(raw))
        return parse_message(raw)
