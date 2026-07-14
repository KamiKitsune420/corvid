"""Uncaught-exception handling: write a crash report and log it.

Installing this gives users a diagnosable artifact (a timestamped crash log next
to the normal logs) instead of a silent failure or a raw console traceback.
"""

from __future__ import annotations

import logging
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

log = logging.getLogger("corvid.crash")


def write_crash_report(
    log_dir: Path,
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
) -> Path:
    """Write a formatted traceback to a timestamped file and return its path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = log_dir / f"crash-{stamp}.log"
    report = "".join(traceback.format_exception(exc_type, exc, tb))
    path.write_text(report, encoding="utf-8")
    return path


def install_crash_handler(log_dir: Path) -> None:
    """Route uncaught exceptions through :func:`write_crash_report`."""

    def hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        try:
            path = write_crash_report(log_dir, exc_type, exc, tb)
            log.error(
                "uncaught exception; crash report written to %s",
                path,
                exc_info=(exc_type, exc, tb),
            )
        except Exception:  # noqa: BLE001 - never fail inside the crash handler
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook
