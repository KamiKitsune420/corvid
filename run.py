#!/usr/bin/env python3
"""Launch the Corvid desktop app without typing CLI commands.

    python run.py          # normal per-user data location (%LOCALAPPDATA%\\Corvid)
    python run.py --dev    # throwaway ./_devdata folder, handy for testing

Double-clicking this file (or run.bat on Windows) also works.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable without installing it.
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

from corvid.app.paths import paths_for_root  # noqa: E402  (after sys.path setup)
from corvid.ui.app import run  # noqa: E402


def main() -> int:
    if "--dev" in sys.argv[1:]:
        return run(paths_for_root(_ROOT / "_devdata"))
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
