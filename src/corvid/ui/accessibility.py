"""Accessibility helpers for the wx UI.

Applied consistently so the app is operable by keyboard and intelligible to
screen readers (WCAG 2.1.1 Keyboard, 2.4.3 Focus Order, 4.1.2 Name/Role/Value):

* ``accessible_name`` sets a control's screen-reader name. wxPython announces a
  generic name for text controls that have no own label, so fields described by
  an adjacent ``StaticText`` get their name set explicitly.
* ``clean_label`` derives that name from a UI label (dropping ``&`` mnemonics
  and a trailing colon).
* ``labeled_row`` adds a label + control pair to a FlexGridSizer and wires the
  accessible name in one step.

Colors and fonts are left to native theming so OS high-contrast and font-scaling
settings apply; meaning is never conveyed by color alone.
"""

from __future__ import annotations

import wx


def clean_label(text: str) -> str:
    """Turn a UI label like ``"&IMAP host:"`` into an accessible name ``"IMAP host"``."""
    return text.replace("&", "").rstrip(":").strip()


if hasattr(wx, "Accessible"):  # Windows/MSAA builds

    class _NamedAccessible(wx.Accessible):
        """Exposes a fixed accessible name for a control (announced on focus).

        ``wx.Window.SetName`` alone does not become the MSAA/UIA *name* that NVDA
        reads for composite controls (tree/list), so we override ``GetName`` for
        the control itself (child id 0) and defer for child items so their own
        names still work.
        """

        def __init__(self, name: str) -> None:
            super().__init__()
            self._name = name

        def GetName(self, child_id: int):  # type: ignore[override]
            if child_id == 0:  # wx.ACC_SELF — the control itself
                return (wx.ACC_OK, self._name)
            return (wx.ACC_NOT_IMPLEMENTED, "")

else:  # pragma: no cover - non-Windows builds without wxUSE_ACCESSIBILITY
    _NamedAccessible = None  # type: ignore[assignment,misc]


def accessible_name(window: wx.Window, name: str) -> wx.Window:
    """Set a control's accessible (screen-reader) name, announced on focus."""
    clean = clean_label(name)
    window.SetName(clean)
    if _NamedAccessible is not None:
        window.SetAccessible(_NamedAccessible(clean))
    return window


def labeled_row(
    parent: wx.Window, sizer: wx.FlexGridSizer, label: str, ctrl: wx.Window
) -> wx.Window:
    """Add a ``StaticText`` label + control to a 2-column grid, naming the control."""
    sizer.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
    accessible_name(ctrl, label)
    sizer.Add(ctrl, 1, wx.EXPAND)
    return ctrl
