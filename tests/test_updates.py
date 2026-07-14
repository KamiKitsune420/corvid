from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from corvid.domain.updates import (
    Release,
    ReleaseAsset,
    UpdateInfo,
    evaluate_update,
    is_newer,
    parse_version,
    select_asset,
)
from corvid.errors import NetworkError
from corvid.infra.updates import GitHubUpdateClient
from corvid.service.updates import UpdateService


# --------------------------------------------------------------------------
# domain
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.6", (1, 6)),
        ("v0.2.0", (0, 2, 0)),
        ("  V1.10.3 ", (1, 10, 3)),
        ("", (0,)),
        ("nightly", (0,)),
    ],
)
def test_parse_version(text: str, expected: tuple[int, ...]) -> None:
    assert parse_version(text) == expected


def test_is_newer_semantics() -> None:
    assert is_newer("0.3.0", "0.2.0")
    assert is_newer("1.10.0", "1.9.9")
    assert not is_newer("0.2.0", "0.2.0")
    assert not is_newer("0.1.0", "0.2.0")
    # A malformed candidate sorts as oldest, never masquerading as newer.
    assert not is_newer("garbage", "0.1.0")


def test_select_asset_prefers_installer_then_zip() -> None:
    assets = (
        ReleaseAsset("Corvid-0.3.0.zip", "http://x/zip"),
        ReleaseAsset("CorvidSetup-0.3.0.exe", "http://x/exe"),
    )
    assert select_asset(assets, prefer_installer=True) == ("http://x/exe", True)
    assert select_asset(assets, prefer_installer=False) == ("http://x/zip", False)


def test_select_asset_falls_back_to_zip_when_no_exe() -> None:
    assets = (ReleaseAsset("Corvid-0.3.0.zip", "http://x/zip"),)
    assert select_asset(assets, prefer_installer=True) == ("http://x/zip", False)


def test_select_asset_none_when_empty() -> None:
    assert select_asset((), prefer_installer=True) == (None, False)


def test_evaluate_update_returns_info_for_newer_release() -> None:
    release = Release(
        version="0.3.0",
        notes="Bug fixes",
        assets=(ReleaseAsset("CorvidSetup-0.3.0.exe", "http://x/exe"),),
    )
    info = evaluate_update(release, "0.2.0", prefer_installer=True)
    assert info == UpdateInfo(
        version="0.3.0",
        download_url="http://x/exe",
        is_installer=True,
        release_notes="Bug fixes",
    )


def test_evaluate_update_none_when_up_to_date() -> None:
    release = Release("0.2.0", "", (ReleaseAsset("CorvidSetup-0.2.0.exe", "u"),))
    assert evaluate_update(release, "0.2.0", prefer_installer=True) is None


def test_evaluate_update_none_when_no_asset() -> None:
    release = Release("0.3.0", "", ())
    assert evaluate_update(release, "0.2.0", prefer_installer=True) is None


# --------------------------------------------------------------------------
# infra: fake HTTP opener
# --------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self._pos = 0
        self.headers = headers or {}

    def read(self, amt: int = -1) -> bytes:
        if amt is None or amt < 0:
            chunk = self._body[self._pos :]
            self._pos = len(self._body)
        else:
            chunk = self._body[self._pos : self._pos + amt]
            self._pos += len(chunk)
        return chunk

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _opener_for(body: bytes, headers: dict[str, str] | None = None):
    def _open(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        return _FakeResponse(body, headers)

    return _open


_RELEASE_JSON = json.dumps(
    {
        "tag_name": "v0.3.0",
        "body": "  Shiny new things  ",
        "assets": [
            {"name": "CorvidSetup-0.3.0.exe", "browser_download_url": "http://x/exe"},
            {"name": "notes.txt", "browser_download_url": "http://x/txt"},
        ],
    }
).encode("utf-8")


def test_fetch_latest_release_parses_json() -> None:
    client = GitHubUpdateClient("o/r", user_agent="t", opener=_opener_for(_RELEASE_JSON))
    release = client.fetch_latest_release()
    assert release.version == "0.3.0"  # leading "v" stripped
    assert release.notes == "Shiny new things"
    assert release.assets == (
        ReleaseAsset("CorvidSetup-0.3.0.exe", "http://x/exe"),
        ReleaseAsset("notes.txt", "http://x/txt"),
    )


def test_fetch_latest_release_wraps_network_error() -> None:
    def _boom(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        raise urllib.error.URLError("offline")

    client = GitHubUpdateClient("o/r", user_agent="t", opener=_boom)
    with pytest.raises(NetworkError):
        client.fetch_latest_release()


def test_fetch_latest_release_wraps_bad_json() -> None:
    client = GitHubUpdateClient("o/r", user_agent="t", opener=_opener_for(b"not json"))
    with pytest.raises(NetworkError):
        client.fetch_latest_release()


def test_download_streams_and_reports_progress(tmp_path: Path) -> None:
    body = b"A" * 1000
    opener = _opener_for(body, {"Content-Length": "1000"})
    client = GitHubUpdateClient("o/r", user_agent="t", opener=opener)
    seen: list[tuple[int, int]] = []
    dest = tmp_path / "sub" / "Corvid.exe"
    client.download("http://x/exe", dest, progress_cb=lambda d, t: seen.append((d, t)))
    assert dest.read_bytes() == body
    assert seen[-1] == (1000, 1000)  # finishes at 100%


def test_download_wraps_network_error(tmp_path: Path) -> None:
    def _boom(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        raise urllib.error.URLError("dropped")

    client = GitHubUpdateClient("o/r", user_agent="t", opener=_boom)
    with pytest.raises(NetworkError):
        client.download("http://x/exe", tmp_path / "f.exe")


# --------------------------------------------------------------------------
# service
# --------------------------------------------------------------------------
def test_service_check_reports_newer_release() -> None:
    client = GitHubUpdateClient("o/r", user_agent="t", opener=_opener_for(_RELEASE_JSON))
    service = UpdateService(client, current_version="0.2.0")
    info = service.check_for_updates()
    assert info is not None
    assert info.version == "0.3.0"
    assert info.is_installer is True


def test_service_check_none_when_current_is_latest() -> None:
    client = GitHubUpdateClient("o/r", user_agent="t", opener=_opener_for(_RELEASE_JSON))
    service = UpdateService(client, current_version="0.3.0")
    assert service.check_for_updates() is None


def test_service_download_names_installer_file(tmp_path: Path) -> None:
    opener = _opener_for(b"binary", {"Content-Length": "6"})
    client = GitHubUpdateClient("o/r", user_agent="t", opener=opener)
    service = UpdateService(client, current_version="0.2.0")
    info = UpdateInfo("0.3.0", "http://x/exe", is_installer=True, release_notes="")
    path = service.download(info, tmp_path)
    assert path == tmp_path / "CorvidSetup-0.3.0.exe"
    assert path.read_bytes() == b"binary"
