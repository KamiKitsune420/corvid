"""Application bootstrap and dependency wiring.

``bootstrap()`` resolves paths, loads config, configures logging, opens the
database, runs migrations, and starts the job queue - returning a single
:class:`AppContext` that the UI and services depend on.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from ..infra.db import apply_migrations, connect, current_version
from .config import AppConfig
from .jobs import JobQueue
from .logging_setup import configure_logging
from .paths import AppPaths, default_paths


@dataclass(slots=True)
class AppContext:
    """The wired-up application: shared singletons for the process lifetime."""

    paths: AppPaths
    config: AppConfig
    db: sqlite3.Connection
    jobs: JobQueue
    log: logging.Logger

    def close(self) -> None:
        self.jobs.shutdown(wait=True, cancel=True)
        self.db.close()

    def __enter__(self) -> AppContext:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def bootstrap(paths: AppPaths | None = None, *, create: bool = True) -> AppContext:
    """Build and return the application context."""
    paths = paths or default_paths()
    if create:
        paths.ensure()

    config = AppConfig.load_or_default(paths.config_file)
    log = configure_logging(config.logging, paths.log_dir)

    db = connect(paths.database_file)
    applied = apply_migrations(db)
    if applied:
        log.info("applied migrations: %s", applied)

    jobs = JobQueue(max_workers=config.sync.max_concurrent_jobs)
    log.info(
        "Corvid ready",
        extra={"fields": {"schema": current_version(db), "db": str(paths.database_file)}},
    )
    return AppContext(paths=paths, config=config, db=db, jobs=jobs, log=log)
