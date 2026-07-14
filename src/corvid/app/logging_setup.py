"""Structured logging configuration.

Console output is human-readable; the rotating file handler emits one JSON
object per line (JSONL) so logs can be ingested by tooling. Arbitrary structured
context can be attached via ``logger.info("...", extra={"fields": {...}})``.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import LoggingConfig

LOGGER_ROOT = "corvid"

_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"fields", "message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Render a log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Explicit structured fields take priority.
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        # Also fold in any ad-hoc extras passed directly to the logging call.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(cfg: LoggingConfig, log_dir: Path) -> logging.Logger:
    """Configure and return the application's root logger (``corvid``)."""
    logger = logging.getLogger(LOGGER_ROOT)
    logger.setLevel(cfg.level)
    logger.handlers.clear()
    logger.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    )
    logger.addHandler(console)

    if cfg.json_file:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "corvid.jsonl",
            maxBytes=cfg.max_bytes,
            backupCount=cfg.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)

    return logger
