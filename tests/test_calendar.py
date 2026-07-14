from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

from corvid.domain.entities import Event
from corvid.infra.repositories import EventRepository
from corvid.service.calendar import CalendarService


def _local_to_utc(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi).astimezone(UTC)


def _event(title: str, start: datetime, end: datetime, *, all_day: bool = False) -> Event:
    return Event(id=None, title=title, start_utc=start, end_utc=end, all_day=all_day)


def test_event_crud(db: sqlite3.Connection) -> None:
    repo = EventRepository(db)
    ev = repo.add(
        _event("Dentist", _local_to_utc(2026, 7, 14, 9), _local_to_utc(2026, 7, 14, 10))
    )
    assert ev.id is not None
    got = repo.get(ev.id)
    assert got is not None and got.title == "Dentist"
    assert got.start_utc == _local_to_utc(2026, 7, 14, 9)

    got.title = "Dentist (moved)"
    repo.update(got)
    assert repo.get(ev.id).title == "Dentist (moved)"  # type: ignore[union-attr]

    repo.delete(ev.id)
    assert repo.get(ev.id) is None


def test_events_on_day(db: sqlite3.Connection) -> None:
    svc = CalendarService(EventRepository(db))
    svc.add(_event("Morning", _local_to_utc(2026, 7, 14, 9), _local_to_utc(2026, 7, 14, 10)))
    svc.add(_event("Evening", _local_to_utc(2026, 7, 14, 20), _local_to_utc(2026, 7, 14, 21)))
    svc.add(_event("Next day", _local_to_utc(2026, 7, 15, 9), _local_to_utc(2026, 7, 15, 10)))

    on_14 = svc.events_on(date(2026, 7, 14))
    assert [e.title for e in on_14] == ["Morning", "Evening"]  # ordered by start, same day
    assert [e.title for e in svc.events_on(date(2026, 7, 15))] == ["Next day"]
    assert svc.events_on(date(2026, 7, 16)) == []


def test_days_with_events_marks_multiday(db: sqlite3.Connection) -> None:
    svc = CalendarService(EventRepository(db))
    svc.add(_event("One-off", _local_to_utc(2026, 7, 3, 12), _local_to_utc(2026, 7, 3, 13)))
    # A trip spanning the 10th–12th (local days).
    svc.add(
        _event("Trip", _local_to_utc(2026, 7, 10, 8), _local_to_utc(2026, 7, 12, 18))
    )
    days = svc.days_with_events(2026, 7)
    assert days == {3, 10, 11, 12}
    # A different month has none of these.
    assert svc.days_with_events(2026, 8) == set()


def test_event_counts(db: sqlite3.Connection) -> None:
    svc = CalendarService(EventRepository(db))
    svc.add(_event("A", _local_to_utc(2026, 7, 14, 9), _local_to_utc(2026, 7, 14, 10)))
    svc.add(_event("B", _local_to_utc(2026, 7, 14, 11), _local_to_utc(2026, 7, 14, 12)))
    svc.add(_event("C", _local_to_utc(2026, 7, 20, 9), _local_to_utc(2026, 7, 20, 10)))
    counts = svc.event_counts(2026, 7)
    assert counts == {14: 2, 20: 1}


def test_all_day_event_shows_on_its_day(db: sqlite3.Connection) -> None:
    svc = CalendarService(EventRepository(db))
    start = _local_to_utc(2026, 7, 14, 0, 0)
    end = _local_to_utc(2026, 7, 15, 0, 0)
    svc.add(_event("Holiday", start, end, all_day=True))
    assert [e.title for e in svc.events_on(date(2026, 7, 14))] == ["Holiday"]
    assert svc.get(1).all_day is True  # type: ignore[union-attr]
