"""Frozen-app entry point: launch the Corvid desktop UI directly.

Used by PyInstaller (see ``corvid.spec``). Double-clicking the packaged
executable lands here and opens the main window.
"""

from __future__ import annotations

import sys

from corvid.ui.app import run

if __name__ == "__main__":
    sys.exit(run())
