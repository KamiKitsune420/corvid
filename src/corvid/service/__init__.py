"""Application services: use-cases wiring repositories to protocol adapters.

This layer sits between the UI and ``infra``. It depends on repositories and the
mail-store/SMTP adapters (the latter via the ``MailStore`` port) so that the UI
deals only in high-level operations: add account, sync, send.
"""

from .accounts import AccountService
from .actions import MessageActionService
from .contacts import ContactService
from .factory import build_account_service, build_sync_service
from .messages import MessageBodyService
from .rules import RuleService
from .search import SearchService
from .send import MailboxSentRecorder, SendService
from .sync import SyncService, SyncSummary

__all__ = [
    "AccountService",
    "SyncService",
    "SyncSummary",
    "SendService",
    "MailboxSentRecorder",
    "SearchService",
    "RuleService",
    "ContactService",
    "MessageBodyService",
    "MessageActionService",
    "build_account_service",
    "build_sync_service",
]
