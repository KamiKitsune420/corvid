from __future__ import annotations

from corvid.app.bootstrap import bootstrap
from corvid.app.paths import AppPaths
from corvid.infra.db import current_version


def test_bootstrap_creates_everything(tmp_paths: AppPaths) -> None:
    with bootstrap(tmp_paths) as ctx:
        assert ctx.paths.database_file.exists()
        assert current_version(ctx.db) >= 1
        # Job queue is live.
        handle = ctx.jobs.submit("ping", lambda c: "pong")
        assert handle.result(timeout=5) == "pong"


def test_bootstrap_is_repeatable(tmp_paths: AppPaths) -> None:
    bootstrap(tmp_paths).close()
    # Second bootstrap over the same dir must not re-run migrations or error.
    with bootstrap(tmp_paths) as ctx:
        assert current_version(ctx.db) >= 1
