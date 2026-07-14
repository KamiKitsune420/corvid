"""SQLite database access: connection factory and schema migrations."""

from .connection import connect, fts5_available
from .migrations import apply_migrations, current_version

__all__ = ["connect", "fts5_available", "apply_migrations", "current_version"]
