"""Software-update domain: version comparison and release-asset selection.

Pure rules for deciding whether a fetched GitHub release is newer than the
running build and which downloadable asset to offer. No I/O — the HTTP call and
JSON parsing live in ``infra.updates``; orchestration in ``service.updates``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    """One downloadable file attached to a GitHub release."""

    name: str
    download_url: str


@dataclass(frozen=True, slots=True)
class Release:
    """A published release: its version, notes, and downloadable assets."""

    version: str
    notes: str
    assets: tuple[ReleaseAsset, ...]


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """A newer release the user can install, with the chosen asset resolved."""

    version: str
    download_url: str
    is_installer: bool
    release_notes: str


def parse_version(text: str) -> tuple[int, ...]:
    """Parse a dotted version (``"1.6"``, ``"v0.2.0"``) into a comparable tuple.

    A leading ``v`` and surrounding whitespace are ignored. Any non-numeric part
    makes the whole version sort as ``(0,)`` (treated as oldest), so a malformed
    tag can never masquerade as newer than the running build.
    """
    cleaned = text.strip().lstrip("vV").strip()
    if not cleaned:
        return (0,)
    try:
        return tuple(int(part) for part in cleaned.split("."))
    except ValueError:
        return (0,)


def is_newer(candidate: str, current: str) -> bool:
    """True if ``candidate`` is a strictly newer version than ``current``."""
    return parse_version(candidate) > parse_version(current)


def select_asset(
    assets: tuple[ReleaseAsset, ...], *, prefer_installer: bool
) -> tuple[str | None, bool]:
    """Choose a release asset. Returns ``(download_url, is_installer)``.

    Installed builds prefer the setup ``.exe`` (double-click to upgrade in
    place) and fall back to a ``.zip`` if no installer was published; otherwise
    the ``.zip`` is chosen. ``(None, False)`` when nothing suitable is present.
    """

    def find(suffix: str) -> str | None:
        for asset in assets:
            if asset.name.lower().endswith(suffix):
                return asset.download_url
        return None

    if prefer_installer:
        exe = find(".exe")
        if exe is not None:
            return exe, True
        return find(".zip"), False
    return find(".zip"), False


def evaluate_update(
    release: Release, current_version: str, *, prefer_installer: bool
) -> UpdateInfo | None:
    """Decide whether ``release`` is an update worth offering.

    Returns an :class:`UpdateInfo` when the release is newer than
    ``current_version`` and carries a usable asset; ``None`` otherwise (already
    up to date, or no downloadable asset).
    """
    if not is_newer(release.version, current_version):
        return None
    url, is_installer = select_asset(release.assets, prefer_installer=prefer_installer)
    if url is None:
        return None
    return UpdateInfo(
        version=release.version,
        download_url=url,
        is_installer=is_installer,
        release_notes=release.notes,
    )
