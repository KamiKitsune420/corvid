"""Mail protocol adapters (IMAP/SMTP) and their shared port types."""

from .base import MailStore
from .types import FolderInfo, FolderStatus, HeaderEnvelope

__all__ = ["MailStore", "FolderInfo", "FolderStatus", "HeaderEnvelope"]
