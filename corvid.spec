# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Corvid.

Build a one-folder Windows app:

    pip install -e ".[ui]" pyinstaller
    pyinstaller corvid.spec

The result is dist/Corvid/Corvid.exe. wxPython ships its own PyInstaller hooks,
so no extra hidden imports are usually required.

One exception: the wx hook does not pick up WebView2Loader.dll, which the Edge
WebView2 backend needs. The message-reading pane depends on that backend (it's
what a screen reader can read), so we bundle the DLL explicitly below.
"""

import os

import wx

block_cipher = None

_WX_DIR = os.path.dirname(wx.__file__)
_webview2 = os.path.join(_WX_DIR, "WebView2Loader.dll")
_webview_binaries = [(_webview2, "wx")] if os.path.exists(_webview2) else []

a = Analysis(
    ["packaging/corvid_gui.py"],
    pathex=["src"],
    binaries=_webview_binaries,
    datas=[
        ("config.example.json", "."),
        ("src/corvid/ui/assets", "corvid/ui/assets"),  # app / tray icon
    ],
    hiddenimports=["corvid"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Corvid",
    debug=False,
    strip=False,
    upx=True,
    console=False,  # GUI app: no console window
    icon="src/corvid/ui/assets/corvid.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="Corvid",
)
