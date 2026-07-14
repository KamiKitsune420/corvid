"""Corvid error taxonomy.

Every error raised by application code should derive from :class:`CorvidError`.
Each error carries a ``user_message`` suitable for surfacing in the UI without
leaking internal detail, while ``str(err)`` keeps the developer-facing message.
"""

from __future__ import annotations


class CorvidError(Exception):
    """Base class for all Corvid errors."""

    default_user_message = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, user_message: str | None = None) -> None:
        super().__init__(message or self.default_user_message)
        self.user_message = user_message or self.default_user_message


# -- Configuration ----------------------------------------------------------
class ConfigError(CorvidError):
    default_user_message = "There is a problem with the configuration."


# -- Storage ----------------------------------------------------------------
class StorageError(CorvidError):
    default_user_message = "A storage error occurred."


class MigrationError(StorageError):
    default_user_message = "The local database could not be upgraded."


# -- Networking / protocol --------------------------------------------------
class NetworkError(CorvidError):
    default_user_message = "A network error occurred. Please check your connection."


class AuthError(NetworkError):
    default_user_message = "Authentication failed. Please check your username and password."


class TLSError(NetworkError):
    default_user_message = "A secure (TLS) connection could not be established."


class ProtocolError(NetworkError):
    default_user_message = "The mail server returned an unexpected response."


# -- Validation / control flow ----------------------------------------------
class ValidationError(CorvidError):
    default_user_message = "The provided data is invalid."


class JobCancelled(CorvidError):
    default_user_message = "The operation was cancelled."
