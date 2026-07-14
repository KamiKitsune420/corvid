from __future__ import annotations

from pathlib import Path

from corvid.app.crash import write_crash_report


def test_write_crash_report(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    try:
        raise ValueError("kaboom-42")
    except ValueError as exc:
        path = write_crash_report(log_dir, type(exc), exc, exc.__traceback__)

    assert path.exists()
    assert path.parent == log_dir
    text = path.read_text(encoding="utf-8")
    assert "ValueError" in text
    assert "kaboom-42" in text
