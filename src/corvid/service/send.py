"""Outbound send use-case."""

from __future__ import annotations

import logging
from collections.abc import Callable
from email.message import EmailMessage
from typing import Protocol

from ..domain.compose import DraftMessage, build_email_message

log = logging.getLogger("corvid.send")


class Sender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class SentRecorder(Protocol):
    """Records a successfully sent message (e.g. IMAP APPEND to Sent)."""

    def record_sent(self, message: EmailMessage) -> None: ...


class Appender(Protocol):
    """A mailbox that can have messages appended (structurally an ImapMailStore)."""

    def append(
        self, remote_name: str, message_bytes: bytes, *, flags: tuple[str, ...] = ...
    ) -> None: ...

    def __enter__(self) -> Appender: ...
    def __exit__(self, *exc: object) -> None: ...


class MailboxSentRecorder:
    """Records sent mail via IMAP APPEND to a Sent mailbox."""

    def __init__(self, store_factory: Callable[[], Appender], sent_folder: str) -> None:
        self._store_factory = store_factory
        self._sent_folder = sent_folder

    def record_sent(self, message: EmailMessage) -> None:
        with self._store_factory() as store:
            store.append(self._sent_folder, message.as_bytes(), flags=("\\Seen",))


class SendService:
    def __init__(self, sender: Sender, recorder: SentRecorder | None = None) -> None:
        self._sender = sender
        self._recorder = recorder

    def send(self, draft: DraftMessage) -> EmailMessage:
        """Build, send, and (best-effort) record a draft. Returns the sent message."""
        message = build_email_message(draft)
        self._sender.send(message)
        if self._recorder is not None:
            try:
                self._recorder.record_sent(message)
            except Exception as exc:  # noqa: BLE001 - send succeeded; recording is best-effort
                log.warning("could not record sent message: %s", exc)
        return message
