from __future__ import annotations

from pathlib import Path

import pytest

from corvid.app.paths import _windows_dirs, default_paths, paths_for_root


def test_windows_dirs_nest_under_vendor_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", r"C:\Users\x\AppData\Roaming")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
    cfg, data = _windows_dirs()
    assert cfg.as_posix().endswith("Roaming/ALS-Software/Corvid")
    assert data.as_posix().endswith("Local/ALS-Software/Corvid")


def test_paths_for_root_layout(tmp_path: Path) -> None:
    paths = paths_for_root(tmp_path)
    assert paths.config_file == tmp_path / "config.json"
    assert paths.database_file == tmp_path / "corvid.sqlite3"
    assert paths.log_dir == tmp_path / "logs"
    assert paths.attachments_dir == tmp_path / "attachments"


def test_ensure_creates_directories(tmp_path: Path) -> None:
    paths = paths_for_root(tmp_path / "nested").ensure()
    assert paths.config_dir.is_dir()
    assert paths.log_dir.is_dir()
    assert paths.attachments_dir.is_dir()


def test_default_paths_are_absolute() -> None:
    paths = default_paths()
    assert paths.config_dir.is_absolute()
    assert paths.data_dir.is_absolute()
