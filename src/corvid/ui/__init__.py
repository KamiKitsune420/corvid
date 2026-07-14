"""Presentation layer (wxPython views, dialogs, presenters).

The 3-pane shell, folder tree, message list, and preview pane land in Phase 3.
The UI depends only on ``app.AppContext`` and domain use-cases - never directly
on SQLite or protocol adapters.
"""
