"""Calendar use-cases: event CRUD and local-day/-month queries.

Events are stored in UTC; the UI works in local time. This service converts a
local calendar day (or month) into the UTC interval to query, and reports which
day numbers in a month have events so the picker can highlight them.
"""

from __future__ import annotations

import builtins
import calendar as _calmod
from datetime import UTC, date, datetime, timedelta

from ..domain.entities import Event
from ..infra.repositories import EventRepository


def _local_midnight_utc(day: date) -> datetime:
    """The UTC instant of local midnight starting ``day``."""
    naive = datetime(day.year, day.month, day.day)  # naive == local wall time
    return naive.astimezone(UTC)


class CalendarService:
    def __init__(self, events: EventRepository) -> None:
        self._events = events

    # -- CRUD ---------------------------------------------------------------
    def add(self, event: Event) -> Event:
        return self._events.add(event)

    def update(self, event: Event) -> None:
        self._events.update(event)

    def delete(self, event_id: int) -> None:
        self._events.delete(event_id)

    def get(self, event_id: int) -> Event | None:
        return self._events.get(event_id)

    # -- queries ------------------------------------------------------------
    def events_on(self, day: date) -> builtins.list[Event]:
        start = _local_midnight_utc(day)
        end = _local_midnight_utc(day + timedelta(days=1))
        return self._events.list_between(start, end)

    def event_counts(self, year: int, month: int) -> dict[int, int]:
        """Map each day-of-month in ``year``/``month`` to how many events cover it."""
        first = date(year, month, 1)
        last_day = _calmod.monthrange(year, month)[1]
        month_end = date(year, month, last_day) + timedelta(days=1)
        start = _local_midnight_utc(first)
        end = _local_midnight_utc(month_end)
        counts: dict[int, int] = {}
        for event in self._events.list_between(start, end):
            # Count the event on each local day it covers within this month.
            cursor = event.start_utc.astimezone().date()
            stop = event.end_utc.astimezone().date()
            while cursor <= stop:
                if cursor.year == year and cursor.month == month:
                    counts[cursor.day] = counts.get(cursor.day, 0) + 1
                cursor += timedelta(days=1)
        return counts

    def days_with_events(self, year: int, month: int) -> set[int]:
        """Day-of-month numbers in ``year``/``month`` that have any event."""
        return set(self.event_counts(year, month))
