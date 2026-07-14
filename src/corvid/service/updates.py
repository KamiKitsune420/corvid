"""Use-case: check GitHub Releases for a newer Corvid and download it.

Ties the pure decision logic in :mod:`corvid.domain.updates` to the HTTP client
in :mod:`corvid.infra.updates`. The check distinguishes three outcomes:

- a newer release exists            -> returns an :class:`UpdateInfo`
- already up to date / no asset      -> returns ``None``
- the check itself failed (offline)  -> raises :class:`~corvid.errors.NetworkError`
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import __version__
from ..domain.updates import UpdateInfo, evaluate_update
from ..infra.updates import GitHubUpdateClient, Opener

# The public repository whose Releases feed Corvid's updater.
GITHUB_REPO = "KamiKitsune420/corvid"


class UpdateService:
    """Checks for and downloads Corvid updates from GitHub Releases."""

    def __init__(
        self,
        client: GitHubUpdateClient,
        *,
        current_version: str = __version__,
        prefer_installer: bool = True,
    ) -> None:
        self._client = client
        self._current_version = current_version
        self._prefer_installer = prefer_installer

    @property
    def current_version(self) -> str:
        return self._current_version

    def check_for_updates(self) -> UpdateInfo | None:
        """Return an :class:`UpdateInfo` if a newer release exists, else ``None``.

        Raises :class:`~corvid.errors.NetworkError` when the check cannot be
        completed, so callers can tell "up to date" (``None``) apart from
        "couldn't check" (exception).
        """
        release = self._client.fetch_latest_release()
        return evaluate_update(
            release, self._current_version, prefer_installer=self._prefer_installer
        )

    def download(
        self,
        update: UpdateInfo,
        dest_dir: Path,
        *,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Download ``update``'s asset into ``dest_dir``; return the saved path."""
        if update.is_installer:
            dest = dest_dir / f"CorvidSetup-{update.version}.exe"
        else:
            dest = dest_dir / f"Corvid-{update.version}.zip"
        self._client.download(update.download_url, dest, progress_cb=progress_cb)
        return dest


def build_update_service(
    *,
    current_version: str = __version__,
    opener: Opener | None = None,
) -> UpdateService:
    """Assemble an :class:`UpdateService` for the Corvid GitHub repository.

    Corvid is distributed as a Windows installer, so the setup ``.exe`` asset is
    always preferred (an installed build lives in read-only Program Files and can
    only upgrade itself by re-running the installer).
    """
    client = GitHubUpdateClient(
        GITHUB_REPO,
        user_agent=f"Corvid/{current_version}",
        opener=opener,
    )
    return UpdateService(client, current_version=current_version, prefer_installer=True)
