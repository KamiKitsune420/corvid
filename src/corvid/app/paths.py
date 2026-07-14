"""Platform-appropriate application directories.

Resolves config/data/log/attachment locations per OS convention, with a
``paths_for_root`` helper for portable mode and tests (everything under one dir).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Corvid"
# Publisher folder, matching the installer's Program Files\ALS-Software\corvid
# layout. Installed builds live under read-only Program Files, so per-user data
# goes to %APPDATA%\ALS-Software\Corvid (and %LOCALAPPDATA%\...) instead.
APP_VENDOR = "ALS-Software"


def _windows_dirs() -> tuple[Path, Path]:
    roaming = os.environ.get("APPDATA")
    local = os.environ.get("LOCALAPPDATA")
    base_cfg = Path(roaming) if roaming else Path.home() / "AppData" / "Roaming"
    base_data = Path(local) if local else Path.home() / "AppData" / "Local"
    return base_cfg / APP_VENDOR / APP_NAME, base_data / APP_VENDOR / APP_NAME


def _macos_dirs() -> tuple[Path, Path]:
    base = Path.home() / "Library" / "Application Support" / APP_NAME
    return base, base


def _xdg_dirs() -> tuple[Path, Path]:
    cfg = os.environ.get("XDG_CONFIG_HOME")
    data = os.environ.get("XDG_DATA_HOME")
    base_cfg = Path(cfg) if cfg else Path.home() / ".config"
    base_data = Path(data) if data else Path.home() / ".local" / "share"
    return base_cfg / "corvid", base_data / "corvid"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved locations for all application files."""

    config_dir: Path
    data_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def database_file(self) -> Path:
        return self.data_dir / "corvid.sqlite3"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    @property
    def messages_dir(self) -> Path:
        """Cache of downloaded raw RFC 822 messages (``<message id>.eml``)."""
        return self.data_dir / "messages"

    def ensure(self) -> AppPaths:
        """Create all directories if they do not yet exist; returns self."""
        for directory in (
            self.config_dir,
            self.data_dir,
            self.log_dir,
            self.attachments_dir,
            self.messages_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def default_paths() -> AppPaths:
    """Resolve standard per-user directories for the current platform."""
    if sys.platform.startswith("win"):
        cfg, data = _windows_dirs()
    elif sys.platform == "darwin":
        cfg, data = _macos_dirs()
    else:
        cfg, data = _xdg_dirs()
    return AppPaths(config_dir=cfg, data_dir=data)


def paths_for_root(root: Path | str) -> AppPaths:
    """A self-contained layout rooted at a single directory (portable mode / tests)."""
    root = Path(root)
    return AppPaths(config_dir=root, data_dir=root)
