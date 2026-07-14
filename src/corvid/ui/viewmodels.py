"""Plain view-model structures shared by presenters and wx views.

These carry no wx types so presenters can be unit-tested headlessly.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class FolderNode:
    folder_id: int
    account_id: int
    label: str
    type: str
    unread: int
    total: int


@dataclass(slots=True)
class AccountNode:
    account_id: int
    label: str
    folders: list[FolderNode] = field(default_factory=list)


@dataclass(slots=True)
class MessageRow:
    message_id: int
    subject: str
    sender: str
    date_display: str
    unread: bool
    has_attachments: bool
    flagged: bool
    speech: str = ""  # how a screen reader should announce the row


@dataclass(slots=True)
class ConversationGroup:
    """A conversation for the message tree: a summary plus its member rows.

    A group with a single message renders as a lone row; one with several renders
    as an expandable parent (the ``speech`` summary) over its ``messages`` (each
    oldest-first, so the original is first). ``unread`` is true if any member is.
    """

    key: str
    subject: str
    messages: list[MessageRow]
    unread: bool
    unread_count: int
    speech: str = ""  # spoken summary line for the group's parent node

    @property
    def is_conversation(self) -> bool:
        return len(self.messages) > 1

    @property
    def newest_message_id(self) -> int:
        # messages are oldest-first, so the last row is the most recent.
        return self.messages[-1].message_id
