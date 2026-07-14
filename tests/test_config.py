from __future__ import annotations

from pathlib import Path

import pytest

from corvid.app.config import AppConfig
from corvid.errors import ConfigError


def test_default_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    AppConfig.default().save(path)
    loaded = AppConfig.load(path)
    assert loaded == AppConfig.default()


def test_load_or_default_missing(tmp_path: Path) -> None:
    assert AppConfig.load_or_default(tmp_path / "absent.json") == AppConfig.default()


def test_from_dict_partial_uses_defaults() -> None:
    cfg = AppConfig.from_dict({"theme": "dark", "sync": {"interval_seconds": 60}})
    assert cfg.theme == "dark"
    assert cfg.sync.interval_seconds == 60
    assert cfg.sync.max_concurrent_jobs == 4  # default preserved
    assert cfg.security.enforce_tls is True


def test_ui_and_autosync_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    cfg = AppConfig.default()
    cfg.ui.minimize_to_tray = True
    cfg.ui.show_notifications = False
    cfg.sync.auto_sync = False
    cfg.save(path)
    loaded = AppConfig.load(path)
    assert loaded.ui.minimize_to_tray is True
    assert loaded.ui.show_notifications is False
    assert loaded.sync.auto_sync is False


def test_ui_defaults() -> None:
    cfg = AppConfig.default()
    assert cfg.ui.minimize_to_tray is False   # closing exits unless enabled
    assert cfg.ui.show_notifications is True
    assert cfg.sync.auto_sync is True


def test_invalid_level_rejected() -> None:
    cfg = AppConfig.default()
    cfg.logging.level = "LOUD"
    with pytest.raises(ConfigError):
        cfg.validate()


def test_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        AppConfig.load(path)
