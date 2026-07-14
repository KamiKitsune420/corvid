"""Create or edit a single calendar event (works in local time)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import wx
import wx.adv

from ..domain.entities import Event
from .accessibility import accessible_name, labeled_row


def _to_wx_date(d: date) -> wx.DateTime:
    return wx.DateTime.FromDMY(d.day, d.month - 1, d.year)  # wx months are 0-based


def _from_wx_date(value: wx.DateTime) -> date:
    return date(value.GetYear(), value.GetMonth() + 1, value.GetDay())


class EventDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window | None,
        event: Event | None = None,
        *,
        default_date: date | None = None,
    ) -> None:
        editing = event is not None and event.id is not None
        super().__init__(parent, title="Edit Event" if editing else "New Event", size=(430, 430))
        self._event = event

        if event is not None:
            start_local = event.start_utc.astimezone()
            end_local = event.end_utc.astimezone()
        else:
            now = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            if default_date is not None:
                now = now.replace(
                    year=default_date.year, month=default_date.month, day=default_date.day
                )
            start_local = now
            end_local = start_local + timedelta(hours=1)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        self._title = wx.TextCtrl(self)
        labeled_row(self, grid, "&Title:", self._title)

        self._date = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN)
        self._date.SetValue(_to_wx_date(start_local.date()))
        labeled_row(self, grid, "&Date:", self._date)

        self._start = wx.adv.TimePickerCtrl(self)
        self._start.SetTime(start_local.hour, start_local.minute, 0)
        labeled_row(self, grid, "&Start:", self._start)

        self._end = wx.adv.TimePickerCtrl(self)
        self._end.SetTime(end_local.hour, end_local.minute, 0)
        labeled_row(self, grid, "&End:", self._end)

        self._all_day = wx.CheckBox(self, label="&All day")
        self._all_day.Bind(wx.EVT_CHECKBOX, lambda _e: self._sync_all_day())
        grid.Add(wx.StaticText(self, label=""), 0)
        grid.Add(self._all_day, 0)

        self._location = wx.TextCtrl(self)
        labeled_row(self, grid, "&Location:", self._location)

        self._notes = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        accessible_name(self._notes, "Notes")

        if event is not None:
            self._title.SetValue(event.title)
            self._location.SetValue(event.location)
            self._notes.SetValue(event.notes)
            self._all_day.SetValue(event.all_day)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)
        outer.Add(wx.StaticText(self, label="&Notes:"), 0, wx.LEFT, 12)
        outer.Add(self._notes, 1, wx.EXPAND | wx.ALL, 12)
        outer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)
        self._sync_all_day()
        self._title.SetFocus()

    def _sync_all_day(self) -> None:
        enabled = not self._all_day.GetValue()
        self._start.Enable(enabled)
        self._end.Enable(enabled)

    def get_event(self) -> Event:
        day = _from_wx_date(self._date.GetValue())
        if self._all_day.GetValue():
            start_local = datetime(day.year, day.month, day.day)
            end_local = start_local + timedelta(days=1)
        else:
            sh, sm, _ = self._start.GetTime()
            eh, em, _ = self._end.GetTime()
            start_local = datetime(day.year, day.month, day.day, sh, sm)
            end_local = datetime(day.year, day.month, day.day, eh, em)
            if end_local <= start_local:  # guard against an end before start
                end_local = start_local + timedelta(hours=1)

        event = self._event or Event(id=None, title="", start_utc=start_local, end_utc=end_local)
        event.title = self._title.GetValue().strip() or "(untitled)"
        event.location = self._location.GetValue().strip()
        event.notes = self._notes.GetValue()
        event.all_day = self._all_day.GetValue()
        event.start_utc = start_local.astimezone(UTC)  # naive local -> UTC
        event.end_utc = end_local.astimezone(UTC)
        return event
