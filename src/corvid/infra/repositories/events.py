"""Calendar event repository. Times are stored as ISO-8601 UTC text."""

from __future__ import annotations

import builtins
from datetime import datetime

from ...domain.entities import Event
from ._rows import dt_to_text, from_bool, last_id, text_to_dt, to_bool
from .base import Repository


def _event_from_row(row: object) -> Event:
    r = row  # sqlite3.Row supports mapping access
    start = text_to_dt(r["start_utc"])  # type: ignore[index]
    end = text_to_dt(r["end_utc"])  # type: ignore[index]
    assert start is not None and end is not None
    return Event(
        id=r["id"],  # type: ignore[index]
        title=r["title"],  # type: ignore[index]
        start_utc=start,
        end_utc=end,
        all_day=to_bool(r["all_day"]),  # type: ignore[index]
        location=r["location"],  # type: ignore[index]
        notes=r["notes"],  # type: ignore[index]
    )


class EventRepository(Repository):
    def add(self, event: Event) -> Event:
        cur = self.conn.execute(
            """
            INSERT INTO events (title, location, notes, start_utc, end_utc, all_day)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.title,
                event.location,
                event.notes,
                dt_to_text(event.start_utc),
                dt_to_text(event.end_utc),
                from_bool(event.all_day),
            ),
        )
        event.id = last_id(cur)
        return event

    def update(self, event: Event) -> None:
        if event.id is None:
            raise ValueError("Cannot update an event without an id.")
        self.conn.execute(
            """
            UPDATE events SET title = ?, location = ?, notes = ?,
                start_utc = ?, end_utc = ?, all_day = ?
            WHERE id = ?
            """,
            (
                event.title,
                event.location,
                event.notes,
                dt_to_text(event.start_utc),
                dt_to_text(event.end_utc),
                from_bool(event.all_day),
                event.id,
            ),
        )

    def delete(self, event_id: int) -> None:
        self.conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def get(self, event_id: int) -> Event | None:
        row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return _event_from_row(row) if row else None

    def list_between(
        self, start_utc: datetime, end_utc: datetime
    ) -> builtins.list[Event]:
        """Events overlapping the half-open interval ``[start_utc, end_utc)``."""
        rows = self.conn.execute(
            """
            SELECT * FROM events
            WHERE start_utc < ? AND end_utc > ?
            ORDER BY start_utc, id
            """,
            (dt_to_text(end_utc), dt_to_text(start_utc)),
        ).fetchall()
        return [_event_from_row(r) for r in rows]
