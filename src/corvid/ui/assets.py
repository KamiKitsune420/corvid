"""Bundled UI assets (the app / tray icon)."""

from __future__ import annotations

from pathlib import Path

import wx

_ASSETS = Path(__file__).resolve().parent / "assets"


def app_icon() -> wx.Icon | None:
    """Return the Corvid app icon, or ``None`` if the asset is missing."""
    ico = _ASSETS / "corvid.ico"
    if ico.exists():
        return wx.Icon(str(ico), wx.BITMAP_TYPE_ICO)
    png = _ASSETS / "corvid_64.png"
    if png.exists():
        return wx.Icon(wx.Bitmap(str(png), wx.BITMAP_TYPE_PNG))
    return None
