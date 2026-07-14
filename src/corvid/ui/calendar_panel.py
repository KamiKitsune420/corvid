"""The calendar view.

Primary UI is a WebView hosting an accessible ARIA month grid (see
``calendar_html``) — it gives a visual calendar of dates *and* strong screen-
reader support (NVDA reads ARIA grids well). The day's events and the event
editor are ordinary, announced wx controls beneath it. If a WebView can't be
created, it falls back to a read-only, arrow-driven date field that reads the
date in words.
"""

from __future__ import annotations

import calendar as _calmod
import json
from collections.abc import Callable
from datetime import date, timedelta

import wx

from ..domain.entities import Event
from ..service.calendar import CalendarService
from .accessibility import accessible_name
from .calendar_html import CALENDAR_HTML
from .event_dialog import EventDialog

try:
    import wx.html2 as _html2
except ImportError:  # pragma: no cover - html2 always ships with wxPython
    _html2 = None  # type: ignore[assignment]


def _add_months(d: date, n: int) -> date:
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, _calmod.monthrange(year, month)[1])
    return date(year, month, day)


class _DateField(wx.TextCtrl):
    """Fallback date field spoken in words; arrows change day (L/R) and month (U/D)."""

    def __init__(self, parent: wx.Window, on_change: Callable[[date], None]) -> None:
        super().__init__(parent, style=wx.TE_READONLY | wx.TE_CENTER)
        self._date = date.today()
        self._on_change = on_change
        accessible_name(self, "Date")
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self._refresh()

    def set_date(self, value: date) -> None:
        self._date = value
        self._refresh()
        self._on_change(value)

    def _refresh(self) -> None:
        self.SetValue(self._date.strftime("%A, %B %d, %Y"))
        try:
            wx.Accessible.NotifyEvent(0x800E, self, wx.OBJID_CLIENT, 0)  # value change
        except Exception:  # noqa: BLE001
            pass

    def _on_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_LEFT:
            self.set_date(self._date - timedelta(days=1))
        elif key == wx.WXK_RIGHT:
            self.set_date(self._date + timedelta(days=1))
        elif key == wx.WXK_UP:
            self.set_date(_add_months(self._date, 1))
        elif key == wx.WXK_DOWN:
            self.set_date(_add_months(self._date, -1))
        else:
            event.Skip()


class CalendarPanel(wx.Panel):
    def __init__(self, parent: wx.Window, service: CalendarService) -> None:
        super().__init__(parent)
        self._service = service
        self._selected = date.today()
        self._day_events: list[Event] = []
        self._web = None
        self._web_ready = False
        self._field: _DateField | None = None

        today_btn = wx.Button(self, label="&Today")
        today_btn.Bind(wx.EVT_BUTTON, lambda _e: self._go_today())

        self._heading = wx.StaticText(self, label="")
        self._heading.SetFont(self._heading.GetFont().Bold())

        self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        accessible_name(self._list, "Events")
        self._list.InsertColumn(0, "Time", width=150)
        self._list.InsertColumn(1, "Event", width=320)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_edit)

        new_btn = wx.Button(self, label="New &Event")
        edit_btn = wx.Button(self, label="&Edit")
        del_btn = wx.Button(self, label="De&lete")
        new_btn.Bind(wx.EVT_BUTTON, self.on_new)
        edit_btn.Bind(wx.EVT_BUTTON, self.on_edit)
        del_btn.Bind(wx.EVT_BUTTON, self.on_delete)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for b in (new_btn, edit_btn, del_btn):
            actions.Add(b, 0, wx.RIGHT, 6)

        selector = self._build_web() or self._build_field()

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(today_btn, 0, wx.ALL, 8)
        outer.Add(selector, 3 if self._web is not None else 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        outer.Add(self._heading, 0, wx.ALL, 8)
        outer.Add(self._list, 2, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        outer.Add(actions, 0, wx.ALL, 8)
        self.SetSizer(outer)

        if self._web is None:
            self._reload_events()  # field mode renders immediately; web waits for "ready"

    # -- selector construction ---------------------------------------------
    def _build_web(self) -> wx.Window | None:
        if _html2 is None or not _html2.WebView.IsBackendAvailable(
            _html2.WebViewBackendEdge
        ):
            return None
        try:
            web = _html2.WebView.New(self, backend=_html2.WebViewBackendEdge)
            web.AddScriptMessageHandler("corvid")
        except Exception:  # noqa: BLE001 - fall back to the field on any WebView failure
            return None
        web.EnableContextMenu(False)
        web.Bind(_html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED, self._on_web_message)
        web.SetPage(CALENDAR_HTML, "")
        web.SetMinSize((320, 300))
        self._web = web
        return web

    def _build_field(self) -> wx.Window:
        self._field = _DateField(self, self._on_field_changed)
        return self._field

    # -- date selection & rendering ----------------------------------------
    def _go_today(self) -> None:
        today = date.today()
        if self._field is not None:
            self._field.set_date(today)
        else:
            self._render_month(today.year, today.month, today)

    def _on_field_changed(self, value: date) -> None:
        self._selected = value
        self._reload_events()

    def _render_month(self, year: int, month: int, selected: date) -> None:
        self._selected = selected
        if self._web is not None and self._web_ready:
            counts = self._service.event_counts(year, month)
            data = {
                "year": year,
                "month": month,
                "today": date.today().isoformat(),
                "selected": selected.isoformat(),
                "counts": {str(k): v for k, v in counts.items()},
            }
            self._web.RunScript(f"setMonth({json.dumps(data)});")
        self._reload_events()

    def refresh(self) -> None:
        if self._web is not None:
            self._render_month(self._selected.year, self._selected.month, self._selected)
        else:
            self._reload_events()

    def _on_web_message(self, event: wx.Event) -> None:
        try:
            msg = json.loads(event.GetString())  # type: ignore[attr-defined]
        except (ValueError, TypeError):
            return
        kind = msg.get("type")
        if kind == "ready":
            self._web_ready = True
            self._render_month(self._selected.year, self._selected.month, self._selected)
        elif kind == "select":
            self._selected = date.fromisoformat(msg["date"])
            self._reload_events()
        elif kind == "month":
            self._render_month(
                int(msg["year"]), int(msg["month"]), date.fromisoformat(msg["selected"])
            )
        elif kind == "activate":
            self._new_event(date.fromisoformat(msg["date"]))

    def _reload_events(self) -> None:
        day = self._selected
        self._day_events = self._service.events_on(day)
        count = len(self._day_events)
        plural = "s" if count != 1 else ""
        self._heading.SetLabel(
            f"{day.strftime('%A, %B %d, %Y')} — {count} event{plural}"
        )
        self._list.DeleteAllItems()
        for i, ev in enumerate(self._day_events):
            if ev.all_day:
                when = "All day"
            else:
                when = ev.start_utc.astimezone().strftime("%I:%M %p").lstrip("0")
            self._list.InsertItem(i, when)
            self._list.SetItem(i, 1, ev.title)

    def _redraw(self) -> None:
        """Refresh both the month dots and the day's events after an edit."""
        self._render_month(self._selected.year, self._selected.month, self._selected)

    def _selected_event(self) -> Event | None:
        row = self._list.GetFirstSelected()
        return self._day_events[row] if 0 <= row < len(self._day_events) else None

    # -- actions ------------------------------------------------------------
    def _new_event(self, day: date) -> None:
        dialog = EventDialog(self, None, default_date=day)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self._service.add(dialog.get_event())
                self._redraw()
        finally:
            dialog.Destroy()

    def on_new(self, _event: wx.Event) -> None:
        self._new_event(self._selected)

    def on_edit(self, _event: wx.Event) -> None:
        event = self._selected_event()
        if event is None:
            return
        dialog = EventDialog(self, event)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self._service.update(dialog.get_event())
                self._redraw()
        finally:
            dialog.Destroy()

    def on_delete(self, _event: wx.CommandEvent) -> None:
        event = self._selected_event()
        if event is None or event.id is None:
            return
        if wx.MessageBox(
            f"Delete '{event.title}'?", "Confirm", wx.YES_NO | wx.ICON_QUESTION
        ) == wx.YES:
            self._service.delete(event.id)
            self._redraw()
