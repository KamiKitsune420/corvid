"""wxPython application entry point."""

from __future__ import annotations

from ..app.bootstrap import AppContext, bootstrap
from ..app.crash import install_crash_handler
from ..app.paths import AppPaths


def run(paths: AppPaths | None = None) -> int:
    """Launch the desktop UI. Blocks until the main window is closed."""
    import wx  # imported lazily so headless tooling can import the package
    import wx.adv

    from .main_frame import MainFrame

    ctx: AppContext = bootstrap(paths)
    install_crash_handler(ctx.paths.log_dir)
    app = wx.App()
    app.SetAppName("Corvid")
    app.SetAppDisplayName("Corvid")
    # Windows names toast notifications after the app; without this they'd read
    # "Python". MSWUseToasts registers a Start-menu shortcut with our display name
    # so notifications say "Corvid".
    if hasattr(wx.adv.NotificationMessage, "MSWUseToasts"):
        try:
            wx.adv.NotificationMessage.MSWUseToasts(shortcutPath="", appId="Corvid.Mail")
        except Exception:  # noqa: BLE001 - best-effort; falls back to default naming
            pass
    try:
        frame = MainFrame(ctx)
        frame.Show()
        app.MainLoop()
    finally:
        ctx.close()
    return 0
