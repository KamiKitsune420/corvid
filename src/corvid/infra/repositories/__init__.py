"""SQLite-backed repositories mapping domain entities to rows."""

from .accounts import AccountRepository, IdentityRepository
from .base import Repository
from .contacts import ContactRepository
from .drafts import DraftRepository
from .events import EventRepository
from .folders import FolderRepository
from .messages import MessageRepository
from .pop3 import Pop3UidlRepository
from .rules import RuleRepository

__all__ = [
    "Repository",
    "AccountRepository",
    "IdentityRepository",
    "FolderRepository",
    "MessageRepository",
    "DraftRepository",
    "RuleRepository",
    "ContactRepository",
    "Pop3UidlRepository",
    "EventRepository",
]
