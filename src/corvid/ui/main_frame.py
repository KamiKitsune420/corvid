"""The classic 3-pane main window: folder tree, message list, preview."""

from __future__ import annotations

import logging
import threading
from html import escape

import wx
import wx.adv

from ..app.bootstrap import AppContext
from ..app.jobs import JobContext
from ..domain.compose import DraftMessage
from ..domain.entities import Account, AccountKind, FolderType, Message, ReceiveProtocol
from ..infra.autodiscovery import discover
from ..infra.db import connect
from ..infra.mail.parsing import ParsedMessage
from ..infra.oauth import build_clients as build_oauth_clients
from ..infra.repositories import (
    AccountRepository,
    ContactRepository,
    DraftRepository,
    FolderRepository,
    IdentityRepository,
    MessageRepository,
    RuleRepository,
)
from ..service.actions import MessageActionService
from ..service.contacts import ContactService
from ..service.factory import (
    build_account_service,
    build_calendar_service,
    build_news_service,
    build_pop3_service,
    build_sync_service,
)
from ..service.messages import MessageBodyService
from ..service.search import SearchService
from ..service.send import MailboxSentRecorder, SendService
from ..service.sync import SyncSummary
from .accessibility import accessible_name
from .account_dialog import AccountDialog
from .assets import app_icon
from .calendar_panel import CalendarPanel
from .compose_frame import ComposeFrame
from .contacts_dialog import ContactsDialog
from .credentials_dialog import CredentialsDialog
from .find_dialog import FindDialog
from .import_dialog import ImportDialog
from .newsgroups_dialog import NewsgroupsDialog
from .post_dialog import PostDialog
from .presenters import (
    FolderTreePresenter,
    MessageListPresenter,
    message_to_row,
)
from .preview_panel import PreviewPanel
from .rules_dialog import RulesDialog
from .settings_dialog import SettingsDialog
from .viewmodels import MessageRow

log = logging.getLogger("corvid.ui")

ID_SYNC = wx.NewIdRef()
ID_ADD_ACCOUNT = wx.NewIdRef()
ID_NEW_MESSAGE = wx.NewIdRef()
ID_REPLY = wx.NewIdRef()
ID_RULES = wx.NewIdRef()
ID_CONTACTS = wx.NewIdRef()
ID_SETTINGS = wx.NewIdRef()
ID_MARK_READ = wx.NewIdRef()
ID_MARK_UNREAD = wx.NewIdRef()
ID_FLAG = wx.NewIdRef()
ID_DELETE = wx.NewIdRef()
ID_IMPORT = wx.NewIdRef()
ID_REMOVE_ACCOUNT = wx.NewIdRef()
ID_NEWSGROUPS = wx.NewIdRef()
ID_VIEW_MAIL = wx.NewIdRef()
ID_VIEW_CALENDAR = wx.NewIdRef()
ID_TOGGLE_VIEW = wx.NewIdRef()

_EMPTY_BODY = ParsedMessage(text="(No content.)")


class _LocalOnlyStore:
    """A no-op stand-in for message actions on local-only mail (no server state)."""

    def store_flags(self, *_a: object, **_k: object) -> None: ...
    def move(self, *_a: object, **_k: object) -> None: ...
    def delete(self, *_a: object, **_k: object) -> None: ...


class _CorvidTrayIcon(wx.adv.TaskBarIcon):
    """System-tray icon: restore, quick Send/Receive, and Exit."""

    def __init__(self, frame: MainFrame) -> None:
        super().__init__()
        self._frame = frame
        icon = app_icon()
        if icon is not None:
            self.SetIcon(icon, "Corvid")
        self.Bind(
            wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda _e: self._frame.restore_from_tray()
        )

    def CreatePopupMenu(self) -> wx.Menu:  # noqa: N802 - wx API name
        menu = wx.Menu()
        restore = menu.Append(wx.ID_ANY, "Open Corvid")
        sync = menu.Append(wx.ID_ANY, "Send / Receive")
        menu.AppendSeparator()
        quit_item = menu.Append(wx.ID_EXIT, "Exit")
        self.Bind(wx.EVT_MENU, lambda _e: self._frame.restore_from_tray(), restore)
        self.Bind(wx.EVT_MENU, lambda _e: self._frame.on_sync(_e), sync)
        self.Bind(wx.EVT_MENU, lambda _e: self._frame.quit_app(), quit_item)
        return menu


class MainFrame(wx.Frame):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(None, title="Corvid", size=(1000, 680))
        self.ctx = ctx
        self._folder_presenter = FolderTreePresenter(
            AccountRepository(ctx.db), FolderRepository(ctx.db)
        )
        self._list_presenter = MessageListPresenter(MessageRepository(ctx.db))
        self._body_service = MessageBodyService(
            MessageRepository(ctx.db), ctx.paths.messages_dir
        )
        self._pending_syncs = 0
        _o = ctx.config.oauth
        self._oauth = build_oauth_clients(
            _o.google_client_id, _o.google_client_secret, _o.microsoft_client_id
        )

        self._quitting = False
        self._notify_new = False
        self._round_new = 0
        self._synced_once = False  # suppress the toast for the first (backfill) sync
        self._current_folder_id: int | None = None  # folder whose messages are shown
        self._tray: _CorvidTrayIcon | None = None

        icon = app_icon()
        if icon is not None:
            self.SetIcon(icon)
        self._build_menu()
        self._build_toolbar()
        self.CreateStatusBar()
        self._build_panes()
        self.reload_tree()
        self.SetStatusText("Ready")

        # Background operation: tray, periodic auto-sync, and toast on new mail.
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self._sync_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_auto_sync, self._sync_timer)
        self._apply_tray_setting()
        self._restart_sync_timer()

    # -- chrome -------------------------------------------------------------
    def _build_menu(self) -> None:
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        file_menu.Append(ID_NEW_MESSAGE, "&New Message\tCtrl+N")
        file_menu.Append(ID_REPLY, "&Reply\tCtrl+R")
        file_menu.Append(ID_SYNC, "Send / &Receive\tF9")
        file_menu.AppendSeparator()
        file_menu.Append(ID_ADD_ACCOUNT, "Add &Account...")
        file_menu.Append(ID_REMOVE_ACCOUNT, "Remove Selected Acc&ount...")
        file_menu.Append(ID_IMPORT, "&Import Messages...")
        file_menu.Append(wx.ID_EXIT, "E&xit\tCtrl+Q")
        menubar.Append(file_menu, "&File")

        message_menu = wx.Menu()
        message_menu.Append(ID_MARK_READ, "Mark as &Read\tCtrl+Q")
        message_menu.Append(ID_MARK_UNREAD, "Mark as &Unread\tCtrl+Shift+Q")
        message_menu.Append(ID_FLAG, "Toggle &Flag")
        message_menu.Append(ID_DELETE, "&Delete\tDel")
        menubar.Append(message_menu, "&Message")

        view_menu = wx.Menu()
        view_menu.Append(ID_VIEW_MAIL, "&Mail\tCtrl+1")
        view_menu.Append(ID_VIEW_CALENDAR, "&Calendar\tCtrl+2")
        view_menu.AppendSeparator()
        view_menu.Append(ID_TOGGLE_VIEW, "S&witch Mail/Calendar\tCtrl+Tab")
        menubar.Append(view_menu, "&View")

        tools_menu = wx.Menu()
        tools_menu.Append(ID_CONTACTS, "Address &Book...\tCtrl+Shift+B")
        tools_menu.Append(ID_RULES, "Message R&ules...")
        tools_menu.Append(ID_NEWSGROUPS, "&Newsgroups...")
        tools_menu.Append(ID_SETTINGS, "&Settings...\tCtrl+,")
        menubar.Append(tools_menu, "&Tools")

        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, lambda _e: self._show_view(0), id=ID_VIEW_MAIL)
        self.Bind(wx.EVT_MENU, lambda _e: self._show_view(1), id=ID_VIEW_CALENDAR)
        self.Bind(wx.EVT_MENU, self.on_toggle_view, id=ID_TOGGLE_VIEW)
        # Ctrl+Tab isn't reliable as a menu accelerator, so back it with a table.
        self.SetAcceleratorTable(
            wx.AcceleratorTable([(wx.ACCEL_CTRL, wx.WXK_TAB, ID_TOGGLE_VIEW)])
        )
        self.Bind(wx.EVT_MENU, self.on_add_account, id=ID_ADD_ACCOUNT)
        self.Bind(wx.EVT_MENU, self.on_remove_account, id=ID_REMOVE_ACCOUNT)
        self.Bind(wx.EVT_MENU, self.on_import, id=ID_IMPORT)
        self.Bind(wx.EVT_MENU, self.on_sync, id=ID_SYNC)
        self.Bind(wx.EVT_MENU, self.on_new_message, id=ID_NEW_MESSAGE)
        self.Bind(wx.EVT_MENU, self.on_reply, id=ID_REPLY)
        self.Bind(wx.EVT_MENU, self.on_rules, id=ID_RULES)
        self.Bind(wx.EVT_MENU, self.on_newsgroups, id=ID_NEWSGROUPS)
        self.Bind(wx.EVT_MENU, self.on_contacts, id=ID_CONTACTS)
        self.Bind(wx.EVT_MENU, self.on_settings, id=ID_SETTINGS)
        self.Bind(wx.EVT_MENU, self.on_mark_read, id=ID_MARK_READ)
        self.Bind(wx.EVT_MENU, self.on_mark_unread, id=ID_MARK_UNREAD)
        self.Bind(wx.EVT_MENU, self.on_toggle_flag, id=ID_FLAG)
        self.Bind(wx.EVT_MENU, self.on_delete_message, id=ID_DELETE)
        self.Bind(wx.EVT_MENU, lambda _e: self.quit_app(), id=wx.ID_EXIT)

    def _build_toolbar(self) -> None:
        toolbar = self.CreateToolBar(wx.TB_TEXT | wx.TB_HORIZONTAL)
        sync_art = wx.ArtProvider.GetBitmap(wx.ART_GO_DOWN, wx.ART_TOOLBAR, (16, 16))
        new_art = wx.ArtProvider.GetBitmap(wx.ART_NEW, wx.ART_TOOLBAR, (16, 16))
        reply_art = wx.ArtProvider.GetBitmap(wx.ART_GO_BACK, wx.ART_TOOLBAR, (16, 16))
        add_art = wx.ArtProvider.GetBitmap(wx.ART_PLUS, wx.ART_TOOLBAR, (16, 16))
        toolbar.AddTool(ID_SYNC, "Send/Receive", sync_art)
        toolbar.AddTool(ID_NEW_MESSAGE, "New", new_art)
        toolbar.AddTool(ID_REPLY, "Reply", reply_art)
        toolbar.AddTool(ID_ADD_ACCOUNT, "Add Account", add_art)
        toolbar.AddStretchableSpace()
        self._search = wx.SearchCtrl(toolbar, size=(240, -1), style=wx.TE_PROCESS_ENTER)
        self._search.SetDescriptiveText("Search messages")
        self._search.ShowCancelButton(True)
        self._search.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self._search.Bind(wx.EVT_SEARCH, self.on_search)
        self._search.Bind(wx.EVT_SEARCH_CANCEL, self.on_search_cancel)
        toolbar.AddControl(self._search)
        toolbar.Realize()

    def _titled(self, parent: wx.Window, title: str, control: wx.Window) -> wx.Panel:
        """Wrap a control under a bold caption so each pane is visibly labelled."""
        panel = wx.Panel(parent)
        caption = wx.StaticText(panel, label=title)
        caption.SetFont(caption.GetFont().Bold())
        control.Reparent(panel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(caption, 0, wx.ALL, 4)
        sizer.Add(control, 1, wx.EXPAND)
        panel.SetSizer(sizer)
        return panel

    def _build_panes(self) -> None:
        # A tab-less book swaps between the mail 3-pane and the calendar (Ctrl+Tab).
        self._book = wx.Simplebook(self)
        mail = wx.Panel(self._book)

        outer = wx.SplitterWindow(mail, style=wx.SP_LIVE_UPDATE)
        self._tree = wx.TreeCtrl(
            outer, style=wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS | wx.TR_SINGLE
        )
        accessible_name(self._tree, "Folders")
        self._tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_folder_selected)
        tree_pane = self._titled(outer, "Folders", self._tree)
        self._outer = outer
        self._tree_pane = tree_pane
        self._tree_sash = 240
        self._reading = False  # True while a single message fills the window

        right = wx.SplitterWindow(outer, style=wx.SP_LIVE_UPDATE)
        self._right = right
        self._preview_sash = 360
        # A single column holds one composed line per message ("Unread, sender,
        # subject. sent today at 6:48AM.") so a screen reader speaks exactly that,
        # rather than reading three column cells with header names interleaved.
        self._list = wx.ListCtrl(right, style=wx.LC_REPORT)  # multi-select for Ctrl+A
        accessible_name(self._list, "Messages")
        self._list.InsertColumn(0, "Message", width=700)
        # Arrowing/selecting only navigates (screen reader reads the row); the
        # message opens — and the reading pane appears — on Enter or double-click.
        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_message_selected)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_message_opened)
        self._list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)  # Ctrl+A, Ctrl+F
        self._list.Bind(wx.EVT_SIZE, self._on_list_size)  # keep the column full-width
        self._list_pane = self._titled(right, "Messages", self._list)

        self._preview = PreviewPanel(right)
        self._preview.set_block_remote(self.ctx.config.security.block_remote_content)
        self._preview.set_escape_handler(self._exit_reading)  # Esc leaves reading mode

        right.SplitHorizontally(self._list_pane, self._preview, 360)
        right.SetMinimumPaneSize(120)
        outer.SplitVertically(tree_pane, right, 240)
        outer.SetMinimumPaneSize(160)
        self._show_list_only()  # start in browsing state (no reading pane)
        # Backup Escape route for the list/tree and the HtmlWindow fallback; the
        # WebView catches its own Escape via injected script.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        # Repaint the WebView when we're re-activated (Edge can blank on Alt+Tab).
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)

        mail_sizer = wx.BoxSizer(wx.VERTICAL)
        mail_sizer.Add(outer, 1, wx.EXPAND)
        mail.SetSizer(mail_sizer)
        self._book.AddPage(mail, "Mail")

        self._calendar = CalendarPanel(self._book, build_calendar_service(self.ctx.db))
        self._book.AddPage(self._calendar, "Calendar")

        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(self._book, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

    # -- data loading -------------------------------------------------------
    def reload_tree(self) -> None:
        self._tree.DeleteAllItems()
        root = self._tree.AddRoot("root")
        accounts = self._folder_presenter.build()
        for account in accounts:
            acct_item = self._tree.AppendItem(root, account.label)
            self._tree.SetItemData(acct_item, ("account", account.account_id))
            for folder in account.folders:
                item = self._tree.AppendItem(acct_item, folder.label)
                self._tree.SetItemData(item, ("folder", folder.folder_id))
            self._tree.Expand(acct_item)
        if not accounts:
            # First run: make the empty tree self-explanatory.
            self._tree.AppendItem(root, "No accounts yet - use File > Add Account")
            self._show_welcome()

    def _show_welcome(self) -> None:
        self._show_preview()
        self._preview.show_html(
            "<h2>Welcome to Corvid</h2>"
            "<p>This window is the classic three-pane layout:</p>"
            "<ul>"
            "<li><b>Folders</b> (left) &mdash; your accounts and their folders.</li>"
            "<li><b>Messages</b> (top) &mdash; the message list for the selected folder.</li>"
            "<li>This <b>preview</b> pane &mdash; the selected message.</li>"
            "</ul>"
            "<p>To get started, choose <b>File &gt; Add Account</b>, then "
            "<b>Send / Receive</b> (F9). You can also <b>File &gt; Import "
            "Messages</b> to bring in an existing mailbox.</p>"
        )

    def _selected_folder_id(self) -> int | None:
        item = self._tree.GetSelection()
        if not item.IsOk():
            return None
        data = self._tree.GetItemData(item)
        if data and data[0] == "folder":
            return int(data[1])
        return None

    def _populate_list(self, rows: list[MessageRow]) -> None:
        self._list.DeleteAllItems()
        for index, row in enumerate(rows):
            list_index = self._list.InsertItem(index, row.speech)
            self._list.SetItemData(list_index, row.message_id)
            if row.unread:
                font = self._list.GetItemFont(list_index)
                font.MakeBold()
                self._list.SetItemFont(list_index, font)

    def _on_list_size(self, event: wx.SizeEvent) -> None:
        # Stretch the single column to the list's width (minus the scrollbar).
        width = self._list.GetClientSize().width
        if width > 0:
            self._list.SetColumnWidth(0, width)
        event.Skip()

    def load_messages(self, folder_id: int) -> None:
        self._current_folder_id = folder_id  # the folder Find should search
        rows = self._list_presenter.rows(folder_id)
        self._populate_list(rows)
        self.SetStatusText(f"{len(rows)} message(s)")

    def _on_list_key(self, event: wx.KeyEvent) -> None:
        if event.ControlDown() and event.GetKeyCode() == ord("A"):
            for i in range(self._list.GetItemCount()):
                self._list.Select(i, True)  # Ctrl+A: select every message
        elif event.ControlDown() and event.GetKeyCode() == ord("F"):
            self.on_find()  # Ctrl+F: open the Find dialog
        else:
            event.Skip()

    def on_find(self) -> None:
        """Open the Find dialog scoped to the current folder; reveal the pick."""
        # Search the folder whose messages are showing (not just the tree cursor),
        # so results don't span a duplicate account's copy of the same mail.
        folder_id = self._current_folder_id
        if folder_id is None:
            folder_id = self._selected_folder_id()

        def search_fn(query: str) -> list[Message]:
            return SearchService(self.ctx.db).search(query, folder_id=folder_id)

        dialog = FindDialog(self, search_fn)
        try:
            if dialog.ShowModal() == wx.ID_OK and dialog.selected_message_id is not None:
                self._reveal_message(dialog.selected_message_id)
        finally:
            dialog.Destroy()

    def _select_folder_in_tree(self, folder_id: int) -> bool:
        root = self._tree.GetRootItem()
        account, cookie = self._tree.GetFirstChild(root)
        while account.IsOk():
            child, child_cookie = self._tree.GetFirstChild(account)
            while child.IsOk():
                data = self._tree.GetItemData(child)
                if data and data[0] == "folder" and int(data[1]) == folder_id:
                    self._tree.SelectItem(child)  # fires on_folder_selected -> loads list
                    return True
                child, child_cookie = self._tree.GetNextChild(account, child_cookie)
            account, cookie = self._tree.GetNextChild(root, cookie)
        return False

    def _reveal_message(self, message_id: int) -> None:
        """Go to the message's folder and put focus on its row in the list."""
        message = MessageRepository(self.ctx.db).get(message_id)
        if message is None:
            return
        if not self._select_folder_in_tree(message.folder_id):
            self.load_messages(message.folder_id)
        for i in range(self._list.GetItemCount()):
            if int(self._list.GetItemData(i)) == message_id:
                self._list.Select(i, True)
                self._list.Focus(i)
                self._list.EnsureVisible(i)
                self._list.SetFocus()
                return
        # Not in the visible page (older mail) — open it directly so it's not lost.
        self._open_message(message)

    def on_search(self, _event: wx.CommandEvent) -> None:
        query = self._search.GetValue().strip()
        if not query:
            self.on_search_cancel(_event)
            return
        # Scope the find to the folder currently open (e.g. the Inbox).
        folder_id = self._selected_folder_id()
        results = SearchService(self.ctx.db).search(query, folder_id=folder_id)
        rows = [r for r in (message_to_row(m) for m in results) if r is not None]
        self._populate_list(rows)
        self._hide_preview()
        where = "this folder" if folder_id is not None else "all mail"
        self.SetStatusText(f"{len(rows)} result(s) for '{query}' in {where}")

    def on_search_cancel(self, _event: wx.CommandEvent) -> None:
        self._search.SetValue("")
        folder_id = self._selected_folder_id()
        if folder_id is not None:
            self.load_messages(folder_id)
        else:
            self._populate_list([])

    # -- events -------------------------------------------------------------
    def on_folder_selected(self, _event: wx.TreeEvent) -> None:
        folder_id = self._selected_folder_id()
        self._hide_preview()  # opening a folder closes any open message
        if folder_id is not None:
            self.load_messages(folder_id)

    @staticmethod
    def _header_html(message: Message) -> str:
        # Plain paragraphs, not a table: a screen reader reads them as ordinary
        # lines instead of announcing table/grouping boundaries on every field.
        def line(label: str, value: str) -> str:
            return f"<p><b>{escape(label)}</b> {escape(value)}</p>" if value else ""

        sender = f"{message.from_name} <{message.from_addr}>".strip()
        local = message.date_utc.astimezone() if message.date_utc else None
        date = local.strftime("%Y-%m-%d %H:%M") if local else ""
        return (
            line("From:", sender)
            + line("To:", message.to_addrs)
            + line("Cc:", message.cc_addrs)
            + line("Date:", date)
            + line("Subject:", message.subject or "(no subject)")
        )

    # -- reading pane: two states, browsing vs. a single message full-window -
    def _right_keep(self, keep: wx.Window) -> None:
        """Make the right splitter show only ``keep`` (the list pane or preview).

        A wxSplitterWindow can't be told "show window X" directly, so if it's
        already unsplit on the *wrong* window we re-split to regain both, then
        drop the one we don't want. Getting this right is what keeps the preview
        from lingering (and stealing Tab focus) after leaving reading mode.
        """
        other = self._preview if keep is self._list_pane else self._list_pane
        if self._right.IsSplit():
            self._preview_sash = self._right.GetSashPosition()
            self._right.Unsplit(other)
        elif self._right.GetWindow1() is not keep:
            self._right.SplitHorizontally(self._list_pane, self._preview, self._preview_sash)
            self._right.Unsplit(other)

    def _show_list_only(self) -> None:
        """Browsing state: folder tree + message list, reading pane hidden."""
        self._reading = False
        self._right_keep(self._list_pane)
        if not self._outer.IsSplit():
            self._outer.SplitVertically(self._tree_pane, self._right, self._tree_sash)

    def _show_reading_only(self) -> None:
        """Focused reading: only the email is visible, so nothing to tab into."""
        self._reading = True
        if self._outer.IsSplit():
            self._tree_sash = self._outer.GetSashPosition()
            self._outer.Unsplit(self._tree_pane)  # hide the tree
        self._right_keep(self._preview)  # hide the list, show the message

    def _exit_reading(self) -> None:
        """Esc from the open message: return to the message list."""
        if not self._reading:
            return
        self._show_list_only()  # hides the preview, so it releases keyboard focus
        row = self._list.GetFirstSelected()
        if row == -1 and self._list.GetItemCount() > 0:
            row = 0
            self._list.Select(0, True)
        self._focus_list_row(row)
        # Re-assert once the Unsplit/focus churn settles; Edge can grab focus back.
        wx.CallAfter(self._focus_list_row, row)

    def _focus_list_row(self, row: int) -> None:
        self._list.SetFocus()
        if row != -1:
            self._list.Focus(row)  # the focused item NVDA announces
            self._list.EnsureVisible(row)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE and self._reading:
            self._exit_reading()
            return
        event.Skip()

    def _on_activate(self, event: wx.ActivateEvent) -> None:
        if event.GetActive() and self._reading:
            self._preview.refresh()  # Edge can paint blank after being occluded
        event.Skip()

    # Back-compat aliases used by the folder/search/selection handlers.
    def _hide_preview(self) -> None:
        self._show_list_only()

    def _show_preview(self) -> None:
        if not self._right.IsSplit():
            self._right.SplitHorizontally(self._list_pane, self._preview, self._preview_sash)

    def on_message_selected(self, _event: wx.ListEvent) -> None:
        # Just navigation — the screen reader reads the list row; the reading
        # pane stays closed until the message is opened with Enter/double-click.
        self._hide_preview()

    def on_message_opened(self, event: wx.ListEvent) -> None:
        message = MessageRepository(self.ctx.db).get(int(self._list.GetItemData(event.GetIndex())))
        if message is not None:
            self._open_message(message)

    def _open_message(self, message: Message) -> None:
        header = self._header_html(message)
        self._show_reading_only()
        cached = self._body_service.get_cached(message)
        if cached is not None:
            self._preview.show(header, cached)
            self._preview.focus_body()
            return
        if message.uid is None:
            self._preview.show(header, _EMPTY_BODY)
            self._preview.focus_body()
            return
        self._preview.show_loading(header)
        self._fetch_body(message, header)

    def _fetch_body(self, message: Message, header: str) -> None:
        account = AccountRepository(self.ctx.db).get(message.account_id)
        folder = FolderRepository(self.ctx.db).get(message.folder_id)
        if account is None or folder is None:
            return
        data_dir = self.ctx.paths.data_dir
        messages_dir = self.ctx.paths.messages_dir
        db_path = self.ctx.paths.database_file
        selected_id = message.id

        def job(_job_ctx: JobContext) -> ParsedMessage:
            conn = connect(db_path)
            try:
                service = build_account_service(conn, data_dir, oauth_clients=self._oauth)
                repo = MessageRepository(conn)
                body_service = MessageBodyService(repo, messages_dir)
                fresh = repo.get(selected_id)  # type: ignore[arg-type]
                assert fresh is not None
                if account.kind is AccountKind.NEWS:
                    store_cm = service.open_news_store(account, [folder.remote_name])
                else:
                    store_cm = service.open_store(account)
                with store_cm as store:
                    store.select(folder.remote_name, readonly=False)
                    parsed = body_service.fetch_and_cache(fresh, store)
                    if not fresh.flags.seen:  # mark read on open (no-op server-side for news)
                        MessageActionService(repo, FolderRepository(conn)).mark_seen(fresh, store)
                    return parsed
            finally:
                conn.close()

        handle = self.ctx.jobs.submit(f"body:{selected_id}", job)
        handle.future.add_done_callback(
            lambda fut, mid=selected_id, hdr=header: wx.CallAfter(
                self._on_body_fetched, mid, hdr, fut
            )
        )

    def _on_body_fetched(self, message_id: int, header: str, future) -> None:
        try:
            body = future.result()
        except Exception as exc:  # noqa: BLE001 - show the failure in the pane
            body = ParsedMessage(text=f"[Could not download message: {exc}]")
        # Reflect the now-read state in the folder counts and list row.
        self.reload_tree()
        selected = self._list.GetFirstSelected()
        if selected == -1 or int(self._list.GetItemData(selected)) != message_id:
            return
        self._unbold_row(selected)
        if not self._reading:
            # The user pressed Esc while it was loading; don't pull them back.
            return
        self._preview.show(header, body)
        self._preview.focus_body()

    def _unbold_row(self, row: int) -> None:
        font = self._list.GetItemFont(row)
        font.SetWeight(wx.FONTWEIGHT_NORMAL)
        self._list.SetItemFont(row, font)

    # -- message actions (server write-back) --------------------------------
    def _selected_message_id(self) -> int | None:
        row = self._list.GetFirstSelected()
        return int(self._list.GetItemData(row)) if row != -1 else None

    def _selected_message_ids(self) -> list[int]:
        ids: list[int] = []
        row = self._list.GetFirstSelected()
        while row != -1:
            ids.append(int(self._list.GetItemData(row)))
            row = self._list.GetNextSelected(row)
        return ids

    def _bulk_delete(self, ids: list[int]) -> None:
        """Move several selected messages to Trash in one connection."""
        first = MessageRepository(self.ctx.db).get(ids[0])
        if first is None:
            return
        account = AccountRepository(self.ctx.db).get(first.account_id)
        folder = FolderRepository(self.ctx.db).get(first.folder_id)
        if account is None or folder is None:
            return
        if wx.MessageBox(
            f"Move {len(ids)} messages to Trash?", "Delete", wx.YES_NO | wx.ICON_QUESTION
        ) != wx.YES:
            return
        data_dir = self.ctx.paths.data_dir
        db_path = self.ctx.paths.database_file
        oauth = self._oauth

        def job(_job_ctx: JobContext) -> int:
            conn = connect(db_path)
            try:
                service = build_account_service(conn, data_dir, oauth_clients=oauth)
                repo = MessageRepository(conn)
                folders = FolderRepository(conn)
                actions = MessageActionService(repo, folders)
                trash = next(
                    (f for f in folders.list_for_account(account.id)  # type: ignore[arg-type]
                     if f.type is FolderType.TRASH),
                    None,
                )
                messages = [m for m in (repo.get(i) for i in ids) if m is not None]
                needs_server = account.kind is not AccountKind.NEWS and any(
                    m.uid is not None for m in messages
                )
                if needs_server:
                    with service.open_store(account) as store:
                        store.select(folder.remote_name, readonly=False)
                        for message in messages:
                            actions.delete(message, store, trash)
                else:
                    local = _LocalOnlyStore()
                    for message in messages:
                        actions.delete(message, local, trash)  # type: ignore[arg-type]
                return len(messages)
            finally:
                conn.close()

        handle = self.ctx.jobs.submit(f"bulk-delete:{len(ids)}", job)
        handle.future.add_done_callback(
            lambda fut: wx.CallAfter(self._after_action, f"Delete {len(ids)}", fut)
        )

    def _run_message_action(self, label: str, fn) -> None:
        message_id = self._selected_message_id()
        if message_id is None:
            self.SetStatusText("Select a message first.")
            return
        message = MessageRepository(self.ctx.db).get(message_id)
        if message is None:
            return
        account = AccountRepository(self.ctx.db).get(message.account_id)
        folder = FolderRepository(self.ctx.db).get(message.folder_id)
        if account is None or folder is None:
            return
        data_dir = self.ctx.paths.data_dir
        db_path = self.ctx.paths.database_file

        def job(_job_ctx: JobContext) -> None:
            conn = connect(db_path)
            try:
                service = build_account_service(conn, data_dir, oauth_clients=self._oauth)
                repo = MessageRepository(conn)
                folders = FolderRepository(conn)
                actions = MessageActionService(repo, folders)
                fresh = repo.get(message_id)
                if fresh is None:
                    return
                trash = next(
                    (f for f in folders.list_for_account(account.id)  # type: ignore[arg-type]
                     if f.type is FolderType.TRASH),
                    None,
                )
                # Local-only messages (imported, POP3-delivered) and news articles
                # have no IMAP server state — act locally without a connection.
                if fresh.uid is None or account.kind is AccountKind.NEWS:
                    fn(actions, _LocalOnlyStore(), fresh, trash)
                else:
                    with service.open_store(account) as store:
                        store.select(folder.remote_name, readonly=False)
                        fn(actions, store, fresh, trash)
            finally:
                conn.close()

        handle = self.ctx.jobs.submit(f"{label}:{message_id}", job)
        handle.future.add_done_callback(
            lambda fut: wx.CallAfter(self._after_action, label, fut)
        )

    def _after_action(self, label: str, future) -> None:
        try:
            future.result()
            self.SetStatusText(f"{label} complete")
        except Exception as exc:  # noqa: BLE001 - report, leave server state intact
            self.SetStatusText(f"{label} failed: {exc}")
            log.warning("%s failed: %s", label, exc)
        self.reload_tree()
        folder_id = self._selected_folder_id()
        if folder_id is not None:
            self.load_messages(folder_id)

    def on_mark_read(self, _event: wx.CommandEvent) -> None:
        self._run_message_action("Mark read", lambda a, s, m, t: a.mark_seen(m, s, seen=True))

    def on_mark_unread(self, _event: wx.CommandEvent) -> None:
        self._run_message_action("Mark unread", lambda a, s, m, t: a.mark_seen(m, s, seen=False))

    def on_toggle_flag(self, _event: wx.CommandEvent) -> None:
        self._run_message_action(
            "Flag", lambda a, s, m, t: a.set_flagged(m, s, flagged=not m.flags.flagged)
        )

    def on_delete_message(self, event: wx.CommandEvent) -> None:
        # Del in the folder tree on an account removes it; elsewhere it deletes
        # the selected message.
        if self.FindFocus() is self._tree:
            item = self._tree.GetSelection()
            if item.IsOk():
                data = self._tree.GetItemData(item)
                if data and data[0] == "account":
                    self.on_remove_account(event)
                    return
        ids = self._selected_message_ids()
        if len(ids) > 1:
            self._bulk_delete(ids)
        else:
            self._run_message_action("Delete", lambda a, s, m, t: a.delete(m, s, t))

    def on_add_account(self, _event: wx.CommandEvent) -> None:
        dialog = AccountDialog(self, oauth_clients=self._oauth)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            account, oauth_cred = dialog.get_account()
        except ValueError:
            wx.MessageBox("Ports must be numeric.", "Invalid input", wx.ICON_ERROR)
            return
        finally:
            dialog.Destroy()
        existing = [
            a for a in AccountRepository(self.ctx.db).list()
            if a.email.lower() == account.email.lower()
        ]
        if existing and wx.MessageBox(
            f"An account for {account.email} already exists. Add it again anyway?",
            "Account already exists", wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        if oauth_cred:  # OAuth sign-in was used (a refresh token) — save directly
            self._save_account(account, oauth_cred, verified=False)
            return
        password = self._collect_password(account)
        if password is not None:
            self._verify_and_save(account, password)

    def _receive_host(self, account: Account) -> str:
        if account.kind is AccountKind.NEWS:
            return account.nntp_host
        if account.receive_protocol is ReceiveProtocol.POP3:
            return account.pop3_host
        return account.imap_host

    def _collect_password(self, account: Account) -> str | None:
        """Prompt for the password (with app-password guidance). None = cancelled."""
        if account.kind is AccountKind.NEWS and not account.username:
            return ""  # anonymous news server needs no password
        settings = discover(account.email)
        dialog = CredentialsDialog(
            self,
            email=account.email,
            provider_name=settings.name if settings else "",
            help_url=settings.help_url if settings else "",
            app_password=bool(settings and settings.requires_app_password),
        )
        try:
            return dialog.get_password() if dialog.ShowModal() == wx.ID_OK else None
        finally:
            dialog.Destroy()

    def _verify_and_save(self, account: Account, password: str) -> None:
        """Test the credentials on a worker thread, then save (or offer a retry)."""
        progress = wx.ProgressDialog(
            "Add Account",
            f"Verifying sign-in to {self._receive_host(account)}...",
            parent=self,
            style=wx.PD_APP_MODAL,
        )
        progress.Pulse()
        pulse = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: progress.Pulse(), pulse)
        pulse.Start(120)

        data_dir = self.ctx.paths.data_dir
        db_path = self.ctx.paths.database_file
        oauth = self._oauth
        result: dict[str, object] = {}

        def work() -> None:
            conn = connect(db_path)
            try:
                svc = build_account_service(conn, data_dir, oauth_clients=oauth)
                svc.test_credentials(account, password)
                result["ok"] = True
            except Exception as exc:  # noqa: BLE001 - reported on the UI thread
                result["ok"] = False
                result["error"] = exc
            finally:
                conn.close()
            wx.CallAfter(finish)

        def finish() -> None:
            pulse.Stop()
            self.Unbind(wx.EVT_TIMER, source=pulse)
            progress.Destroy()
            if result.get("ok"):
                self._save_account(account, password, verified=True)
                return
            error = result.get("error")
            detail = getattr(error, "user_message", str(error))
            retry = wx.MessageBox(
                f"Couldn't sign in to {account.email}:\n\n{detail}\n\n"
                "Check the password (or server settings) and try again?",
                "Sign-in failed",
                wx.YES_NO | wx.ICON_ERROR,
            )
            if retry == wx.YES:
                again = self._collect_password(account)
                if again is not None:
                    self._verify_and_save(account, again)

        threading.Thread(target=work, daemon=True).start()

    def _save_account(self, account: Account, credential: str, *, verified: bool) -> None:
        try:
            service = build_account_service(
                self.ctx.db, self.ctx.paths.data_dir, oauth_clients=self._oauth
            )
            service.add_account(account, credential)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            wx.MessageBox(
                getattr(exc, "user_message", str(exc)), "Could not add account", wx.ICON_ERROR
            )
            return
        self.reload_tree()
        self._restart_sync_timer()  # a first account may enable auto-sync
        if verified:
            wx.MessageBox(
                f"Account {account.email} was added and its sign-in verified.",
                "Account added", wx.OK | wx.ICON_INFORMATION,
            )
        self.SetStatusText(f"Added account {account.email}")

    def on_remove_account(self, _event: wx.CommandEvent) -> None:
        account = self._current_account()
        if account is None or account.id is None:
            wx.MessageBox(
                "Select an account (or one of its folders) in the folder list first.",
                "Remove Account", wx.OK | wx.ICON_INFORMATION,
            )
            return
        if wx.MessageBox(
            f"Remove the account {account.email}?\n\n"
            "This deletes its locally stored mail, folders, and settings. "
            "Mail on the server is not affected.",
            "Remove Account", wx.YES_NO | wx.ICON_WARNING,
        ) != wx.YES:
            return
        try:
            service = build_account_service(
                self.ctx.db, self.ctx.paths.data_dir, oauth_clients=self._oauth
            )
            service.remove_account(account)
        except Exception as exc:  # noqa: BLE001 - surface removal failures
            wx.MessageBox(
                getattr(exc, "user_message", str(exc)),
                "Could not remove account", wx.ICON_ERROR,
            )
            return
        self._preview.clear()
        self._list.DeleteAllItems()
        self.reload_tree()
        self._restart_sync_timer()
        self.SetStatusText(f"Removed account {account.email}")

    def on_rules(self, _event: wx.CommandEvent) -> None:
        dialog = RulesDialog(self, RuleRepository(self.ctx.db))
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()

    # -- compose ------------------------------------------------------------
    def _current_account(self) -> Account | None:
        accounts_repo = AccountRepository(self.ctx.db)
        item = self._tree.GetSelection()
        if item.IsOk():
            data = self._tree.GetItemData(item)
            if data and data[0] == "account":
                return accounts_repo.get(int(data[1]))
            if data and data[0] == "folder":
                folder = FolderRepository(self.ctx.db).get(int(data[1]))
                if folder is not None:
                    return accounts_repo.get(folder.account_id)
        accounts = accounts_repo.list()
        return accounts[0] if accounts else None

    def _draft_for(self, account: Account) -> DraftMessage:
        identity = IdentityRepository(self.ctx.db).default_for_account(account.id)  # type: ignore[arg-type]
        from_addr = identity.email if identity else account.email
        from_name = identity.display_name if identity else account.display_name
        return DraftMessage(
            from_addr=from_addr,
            from_name=from_name,
            account_id=account.id,
            identity_id=identity.id if identity else None,
        )

    def _sent_folder_name(self, account: Account) -> str | None:
        for folder in FolderRepository(self.ctx.db).list_for_account(account.id):  # type: ignore[arg-type]
            if folder.type is FolderType.SENT:
                return folder.remote_name
        return None

    def _open_composer(self, account: Account, draft: DraftMessage) -> None:
        def on_send(filled: DraftMessage) -> None:
            service = build_account_service(
                self.ctx.db, self.ctx.paths.data_dir, oauth_clients=self._oauth
            )
            sender = service.open_sender(account)
            sent_folder = self._sent_folder_name(account)
            recorder = (
                MailboxSentRecorder(lambda: service.open_store(account), sent_folder)
                if sent_folder
                else None
            )
            SendService(sender, recorder).send(filled)
            if filled.id is not None:
                DraftRepository(self.ctx.db).delete(filled.id)
            wx.CallAfter(self.SetStatusText, f"Message sent to {', '.join(filled.to)}")

        def on_save_draft(filled: DraftMessage) -> None:
            DraftRepository(self.ctx.db).save(filled)
            wx.CallAfter(self.SetStatusText, "Draft saved")

        frame = ComposeFrame(
            self,
            draft,
            on_send=on_send,
            on_save_draft=on_save_draft,
            completer_lookup=self._autocomplete_lookup,
            pick_contacts=self._pick_contacts,
        )
        frame.Show()

    def _autocomplete_lookup(self, prefix: str) -> list[str]:
        # wx runs the text completer on a worker thread, so this can't touch the
        # UI thread's SQLite connection — open a short-lived one on this thread.
        conn = connect(self.ctx.paths.database_file)
        try:
            return ContactService(ContactRepository(conn)).autocomplete(prefix)
        finally:
            conn.close()

    def _contact_service(self) -> ContactService:
        return ContactService(ContactRepository(self.ctx.db))

    def _pick_contacts(self) -> list[str]:
        dialog = ContactsDialog(self, self._contact_service(), pick=True)
        try:
            return dialog.picked if dialog.ShowModal() == wx.ID_OK else []
        finally:
            dialog.Destroy()

    def on_contacts(self, _event: wx.CommandEvent) -> None:
        dialog = ContactsDialog(self, self._contact_service())
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()

    def on_settings(self, _event: wx.CommandEvent) -> None:
        dialog = SettingsDialog(self, self.ctx.config, self.ctx.paths, self.ctx.db)
        try:
            changed = dialog.ShowModal() == wx.ID_OK
        finally:
            dialog.Destroy()
        if changed:  # re-apply tray + auto-sync to the new preferences immediately
            self._apply_tray_setting()
            self._restart_sync_timer()
            self._preview.set_block_remote(self.ctx.config.security.block_remote_content)

    def on_new_message(self, _event: wx.CommandEvent) -> None:
        account = self._current_account()
        if account is None:
            self.SetStatusText("Add an account before composing.")
            return
        if account.kind is AccountKind.NEWS:
            self._compose_post(account)
            return
        self._open_composer(account, self._draft_for(account))

    def on_reply(self, _event: wx.CommandEvent) -> None:
        account = self._current_account()
        if account is None:
            return
        item = self._list.GetFirstSelected()
        if item == -1:
            self.SetStatusText("Select a message to reply to.")
            return
        message = MessageRepository(self.ctx.db).get(int(self._list.GetItemData(item)))
        if message is None:
            return
        if account.kind is AccountKind.NEWS:
            self._compose_post(account, reply_to=message)
            return
        draft = self._draft_for(account)
        draft.to = [message.from_addr] if message.from_addr else []
        subject = message.subject or ""
        draft.subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        draft.in_reply_to = message.message_id
        self._open_composer(account, draft)

    # -- newsgroup posting --------------------------------------------------
    def _compose_post(self, account: Account, *, reply_to: Message | None = None) -> None:
        folder = None
        folder_id = self._selected_folder_id()
        if folder_id is not None:
            folder = FolderRepository(self.ctx.db).get(folder_id)
        group = folder.remote_name if folder and folder.type is FolderType.NEWSGROUP else ""
        subject, references = "", ""
        if reply_to is not None:
            subject = reply_to.subject or ""
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            references = reply_to.message_id
        dialog = PostDialog(self, newsgroups=group, subject=subject)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            newsgroups, subj, body = dialog.newsgroups, dialog.subject, dialog.body
        finally:
            dialog.Destroy()
        if not newsgroups or not subj:
            self.SetStatusText("A newsgroup and subject are required to post.")
            return
        assert account.id is not None
        self.SetStatusText(f"Posting to {newsgroups}...")
        handle = self.ctx.jobs.submit(
            f"post:{account.id}",
            self._make_post_job(account.id, newsgroups, subj, body, references),
        )
        handle.future.add_done_callback(
            lambda fut, ng=newsgroups: wx.CallAfter(self._after_post, ng, fut)
        )

    def _make_post_job(
        self, account_id: int, newsgroups: str, subject: str, body: str, references: str
    ):
        data_dir = self.ctx.paths.data_dir
        db_path = self.ctx.paths.database_file

        def job(_job_ctx: JobContext) -> None:
            conn = connect(db_path)
            try:
                accounts = build_account_service(conn, data_dir, oauth_clients=self._oauth)
                news = build_news_service(conn)
                account = AccountRepository(conn).get(account_id)
                assert account is not None
                with accounts.open_news_store(account, []) as store:
                    news.post(
                        account, store, newsgroups=newsgroups, subject=subject,
                        body=body, references=references,
                    )
            finally:
                conn.close()

        return job

    def _after_post(self, newsgroups: str, future) -> None:
        try:
            future.result()
            self.SetStatusText(f"Article posted to {newsgroups}.")
        except Exception as exc:  # noqa: BLE001 - surface posting failures
            self.SetStatusText(f"Posting failed: {exc}")

    def on_import(self, _event: wx.CommandEvent) -> None:
        accounts = AccountRepository(self.ctx.db).list()
        if not accounts:
            self.SetStatusText("Add an account before importing messages.")
            return
        dialog = ImportDialog(self, accounts)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            source = dialog.source_path
            account_id = dialog.account_id
        finally:
            dialog.Destroy()
        if source is None or account_id is None:
            return
        self.SetStatusText(f"Importing from {source.name}...")
        handle = self.ctx.jobs.submit(
            f"import:{source.name}",
            self._make_import_job(account_id, source),
            on_progress=lambda _f, m: wx.CallAfter(self.SetStatusText, f"Importing {m}..."),
        )
        handle.future.add_done_callback(
            lambda fut: wx.CallAfter(self._on_import_done, fut)
        )

    def _make_import_job(self, account_id: int, source):
        from ..infra.importers import build_importer
        from ..service.factory import build_import_service

        db_path = self.ctx.paths.database_file
        messages_dir = self.ctx.paths.messages_dir

        def job(job_ctx: JobContext):
            conn = connect(db_path)  # worker-thread-owned connection
            try:
                service = build_import_service(conn, messages_dir)
                return service.import_into(
                    account_id, build_importer(source), ctx=job_ctx
                )
            finally:
                conn.close()

        return job

    def _on_import_done(self, future) -> None:
        try:
            summary = future.result()
            message = (
                f"Imported {summary.imported} message(s) into "
                f"{summary.folders} folder(s)"
                + (f", {summary.skipped} already present" if summary.skipped else "")
            )
        except Exception as exc:  # noqa: BLE001 - surface import failures to the user
            message = f"Import failed: {exc}"
            log.warning("import failed: %s", exc)
        self.reload_tree()
        folder_id = self._selected_folder_id()
        if folder_id is not None:
            self.load_messages(folder_id)
        self.SetStatusText(message)

    # -- newsgroups ---------------------------------------------------------
    def _first_news_account(self) -> Account | None:
        current = self._current_account()
        if current is not None and current.kind is AccountKind.NEWS:
            return current
        for account in AccountRepository(self.ctx.db).list():
            if account.kind is AccountKind.NEWS:
                return account
        return None

    def on_newsgroups(self, _event: wx.CommandEvent) -> None:
        account = self._first_news_account()
        if account is None or account.id is None:
            self.SetStatusText("Add a news (NNTP) account first (File → Add Account).")
            return
        self.SetStatusText("Fetching newsgroup list...")
        handle = self.ctx.jobs.submit(
            f"groups:{account.id}", self._make_list_groups_job(account.id)
        )
        handle.future.add_done_callback(
            lambda fut, acc=account: wx.CallAfter(self._show_newsgroups, acc, fut)
        )

    def _make_list_groups_job(self, account_id: int):
        data_dir = self.ctx.paths.data_dir
        db_path = self.ctx.paths.database_file

        def job(_job_ctx: JobContext):
            conn = connect(db_path)
            try:
                accounts = build_account_service(conn, data_dir, oauth_clients=self._oauth)
                news = build_news_service(conn)
                account = AccountRepository(conn).get(account_id)
                assert account is not None
                subscribed = set(news.subscribed_groups(account_id))
                with accounts.open_news_store(account, []) as store:
                    available = news.available_groups(store)
                return available, subscribed
            finally:
                conn.close()

        return job

    def _show_newsgroups(self, account: Account, future) -> None:
        try:
            available, subscribed = future.result()
        except Exception as exc:  # noqa: BLE001 - surface fetch failures
            self.SetStatusText(f"Could not fetch newsgroups: {exc}")
            return
        dialog = NewsgroupsDialog(self, available, subscribed)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                self.SetStatusText("")
                return
            desired = dialog.subscribed
        finally:
            dialog.Destroy()
        to_add, to_remove = desired - subscribed, subscribed - desired
        if not to_add and not to_remove:
            self.SetStatusText("")
            return
        assert account.id is not None
        self.SetStatusText("Updating subscriptions...")
        handle = self.ctx.jobs.submit(
            f"subs:{account.id}", self._make_apply_subs_job(account.id, to_add, to_remove)
        )
        handle.future.add_done_callback(
            lambda fut: wx.CallAfter(self._after_subscriptions, fut)
        )

    def _make_apply_subs_job(self, account_id: int, to_add: set[str], to_remove: set[str]):
        db_path = self.ctx.paths.database_file

        def job(_job_ctx: JobContext) -> tuple[int, int]:
            conn = connect(db_path)
            try:
                news = build_news_service(conn)
                folders = FolderRepository(conn)
                for group in to_add:
                    news.subscribe(account_id, group)
                for group in to_remove:
                    existing = folders.get_by_remote(account_id, group)
                    if existing is not None:
                        news.unsubscribe(existing)
                return len(to_add), len(to_remove)
            finally:
                conn.close()

        return job

    def _after_subscriptions(self, future) -> None:
        try:
            added, removed = future.result()
            self.SetStatusText(
                f"Subscriptions updated (+{added}, -{removed}). "
                "Use Send / Receive (F9) to download articles."
            )
        except Exception as exc:  # noqa: BLE001
            self.SetStatusText(f"Subscription update failed: {exc}")
        self.reload_tree()

    def on_sync(self, _event: wx.CommandEvent) -> None:
        self._start_sync(notify=False)

    def _start_sync(self, *, notify: bool) -> None:
        accounts = AccountRepository(self.ctx.db).list()
        if not accounts:
            if not notify:
                self.SetStatusText("No accounts to sync. Add one first.")
            return
        if self._pending_syncs > 0:
            return  # a sync round is already in flight
        self._notify_new = notify
        self._round_new = 0
        self._pending_syncs += len(accounts)
        if not notify:
            self.SetStatusText("Synchronizing...")
        for account in accounts:
            assert account.id is not None
            handle = self.ctx.jobs.submit(
                f"sync:{account.email}",
                self._make_sync_job(account.id),
                on_progress=lambda f, m: wx.CallAfter(
                    self.SetStatusText, f"Syncing {m}... {int(f * 100)}%"
                ),
            )
            handle.future.add_done_callback(
                lambda fut, email=account.email: wx.CallAfter(self._on_sync_done, email, fut)
            )

    def _make_sync_job(self, account_id: int):
        data_dir = self.ctx.paths.data_dir
        db_path = self.ctx.paths.database_file
        messages_dir = self.ctx.paths.messages_dir

        def job(job_ctx: JobContext) -> SyncSummary:
            conn = connect(db_path)  # worker-thread-owned connection
            try:
                accounts = build_account_service(conn, data_dir, oauth_clients=self._oauth)
                account = AccountRepository(conn).get(account_id)
                if account is None:
                    return SyncSummary()
                if account.kind is AccountKind.NEWS:
                    news = build_news_service(conn)
                    groups = news.subscribed_groups(account_id)
                    with accounts.open_news_store(account, groups) as store:
                        return news.sync(account, store, ctx=job_ctx)
                if account.receive_protocol is ReceiveProtocol.POP3:
                    pop3 = build_pop3_service(conn, messages_dir)
                    with accounts.open_pop3_receiver(account) as receiver:
                        return pop3.sync(account, receiver, ctx=job_ctx)
                sync = build_sync_service(conn)
                with accounts.open_store(account) as store:
                    return sync.sync_account(account, store, ctx=job_ctx)
            finally:
                conn.close()

        return job

    def _on_sync_done(self, email: str, future) -> None:
        self._pending_syncs = max(0, self._pending_syncs - 1)
        try:
            summary: SyncSummary = future.result()
            self._round_new += summary.new_messages
            message = f"{email}: {summary.new_messages} new"
        except Exception as exc:  # noqa: BLE001 - report per-account failures
            message = f"{email}: failed ({exc})"
            log.warning("sync failed for %s: %s", email, exc)
        self.reload_tree()
        folder_id = self._selected_folder_id()
        if folder_id is not None:
            self.load_messages(folder_id)
        if self._pending_syncs == 0:
            # A background round stays quiet in the status bar; it speaks via toast.
            if not self._notify_new:
                self.SetStatusText(f"Sync complete - {message}")
            if self._notify_new and self._round_new > 0:
                self._notify(
                    "New mail",
                    f"{self._round_new} new message"
                    + ("s" if self._round_new != 1 else ""),
                )
        elif not self._notify_new:
            self.SetStatusText(message)

    # -- view switching (Mail / Calendar) -----------------------------------
    def _show_view(self, index: int) -> None:
        self._book.SetSelection(index)
        if index == 1:
            self._calendar.refresh()

    def on_toggle_view(self, _event: wx.CommandEvent) -> None:
        self._show_view(1 - self._book.GetSelection())

    # -- background operation: tray, auto-sync, notifications ---------------
    def _apply_tray_setting(self) -> None:
        """Create or remove the tray icon to match the current setting."""
        want = self.ctx.config.ui.minimize_to_tray
        if want and self._tray is None and app_icon() is not None:
            self._tray = _CorvidTrayIcon(self)
        elif not want and self._tray is not None:
            self._tray.RemoveIcon()
            self._tray.Destroy()
            self._tray = None

    def _restart_sync_timer(self) -> None:
        self._sync_timer.Stop()
        sync = self.ctx.config.sync
        if sync.auto_sync and sync.interval_seconds > 0:
            self._sync_timer.Start(sync.interval_seconds * 1000)

    def on_auto_sync(self, _event: wx.TimerEvent) -> None:
        # The first sync of a session backfills the whole mailbox, so don't toast
        # "16000 new messages" — only notify on later syncs (genuine new mail).
        notify = self._synced_once
        self._synced_once = True
        self._start_sync(notify=notify)

    def _notify(self, title: str, message: str) -> None:
        if not self.ctx.config.ui.show_notifications:
            return
        note = wx.adv.NotificationMessage(title, message, parent=self)
        icon = app_icon()
        if icon is not None:
            note.SetIcon(icon)
        note.Show()

    def restore_from_tray(self) -> None:
        self.Show()
        self.Iconize(False)
        self.Raise()

    def quit_app(self) -> None:
        """Really exit (from File → Exit or the tray menu), bypassing close-to-tray."""
        self._quitting = True
        self.Close()

    def on_close(self, event: wx.CloseEvent) -> None:
        if (
            self.ctx.config.ui.minimize_to_tray
            and self._tray is not None
            and not self._quitting
            and event.CanVeto()
        ):
            event.Veto()
            self.Hide()
            self.SetStatusText("")
            return
        self._sync_timer.Stop()
        if self._tray is not None:
            self._tray.RemoveIcon()
            self._tray.Destroy()
            self._tray = None
        event.Skip()  # allow the frame to be destroyed -> app exits
