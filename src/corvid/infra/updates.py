"""GitHub Releases client: fetch the latest release and download an asset.

The network + JSON boundary for the updater. Pure decisions (is-it-newer, which
asset) live in :mod:`corvid.domain.updates`; :mod:`corvid.service.updates`
orchestrates. The HTTP opener is injectable so the client can be tested without
network access.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from types import TracebackType
from typing import Protocol, cast

from ..domain.updates import Release, ReleaseAsset
from ..errors import NetworkError

_API_VERSION = "2022-11-28"
_CHUNK = 65536


class _Response(Protocol):
    """The subset of an ``http`` response the client relies on."""

    @property
    def headers(self) -> Mapping[str, str]: ...

    def read(self, amt: int = -1, /) -> bytes: ...

    def __enter__(self) -> _Response: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


# (request, timeout_seconds) -> response context manager.
Opener = Callable[[urllib.request.Request, float], _Response]
ProgressCallback = Callable[[int, int], None]


def _default_opener(request: urllib.request.Request, timeout: float) -> _Response:
    return cast(_Response, urllib.request.urlopen(request, timeout=timeout))  # noqa: S310


class GitHubUpdateClient:
    """Talks to the GitHub Releases REST API for a single repository."""

    def __init__(
        self,
        repo: str,
        *,
        user_agent: str,
        token: str = "",
        opener: Opener | None = None,
    ) -> None:
        self._repo = repo
        self._user_agent = user_agent
        self._token = token
        self._open: Opener = opener or _default_opener

    def fetch_latest_release(self) -> Release:
        """Return the repository's latest published release.

        Raises :class:`NetworkError` if GitHub is unreachable or the response is
        not the JSON shape we expect.
        """
        url = f"https://api.github.com/repos/{self._repo}/releases/latest"
        request = self._build_request(url, accept="application/vnd.github+json")
        try:
            with self._open(request, 15.0) as response:
                payload = response.read()
        except (urllib.error.URLError, OSError) as exc:
            raise NetworkError(
                f"Could not reach the update server: {exc}",
                user_message="Could not check for updates. Please try again later.",
            ) from exc
        try:
            data = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise NetworkError(
                f"Malformed release data from GitHub: {exc}",
                user_message="The update server returned an unexpected response.",
            ) from exc
        return _release_from_json(data)

    def download(
        self,
        url: str,
        dest: Path,
        *,
        progress_cb: ProgressCallback | None = None,
    ) -> None:
        """Stream ``url`` to ``dest``, reporting ``(bytes_so_far, total)``.

        ``total`` is ``0`` when the server omits ``Content-Length``. Raises
        :class:`NetworkError` on any network or I/O failure.
        """
        request = self._build_request(url, accept="application/octet-stream")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._open(request, 120.0) as response:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                with dest.open("wb") as handle:
                    while True:
                        chunk = response.read(_CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb is not None:
                            progress_cb(downloaded, total)
        except (urllib.error.URLError, OSError) as exc:
            raise NetworkError(
                f"Download failed: {exc}",
                user_message="The update could not be downloaded. Please try again.",
            ) from exc

    def _build_request(self, url: str, *, accept: str) -> urllib.request.Request:
        request = urllib.request.Request(url)  # noqa: S310 - https URL, fixed host
        request.add_header("Accept", accept)
        request.add_header("X-GitHub-Api-Version", _API_VERSION)
        request.add_header("User-Agent", self._user_agent)
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        return request


def _release_from_json(data: object) -> Release:
    """Build a :class:`Release` from GitHub's release JSON, defensively.

    Unknown or missing fields degrade to empty values rather than raising, so a
    partial payload yields an empty release (treated as "no update") instead of
    a crash. The ``v`` prefix common on tags is stripped for display.
    """
    if not isinstance(data, dict):
        raise NetworkError(
            "Unexpected release payload (expected a JSON object).",
            user_message="The update server returned an unexpected response.",
        )
    raw_tag = str(data.get("tag_name") or "").strip()
    version = raw_tag[1:] if raw_tag[:1] in "vV" else raw_tag
    notes = str(data.get("body") or "").strip()
    assets: list[ReleaseAsset] = []
    raw_assets = data.get("assets")
    if isinstance(raw_assets, list):
        for item in raw_assets:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            download_url = str(item.get("browser_download_url") or "")
            if name and download_url:
                assets.append(ReleaseAsset(name=name, download_url=download_url))
    return Release(version=version, notes=notes, assets=tuple(assets))
