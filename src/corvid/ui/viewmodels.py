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
