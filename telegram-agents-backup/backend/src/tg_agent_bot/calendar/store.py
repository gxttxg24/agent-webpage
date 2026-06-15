from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


try:
    LOCAL_TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


@dataclass(frozen=True)
class CalendarEvent:
    id: int
    chat_id: int
    title: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class ParsedEvent:
    title: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class ScheduleRequest:
    title: str
    target_day: date
    duration_minutes: int
    kind: str = "default"


class ScheduleParseError(ValueError):
    pass


class ScheduleStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_chat_start ON events(chat_id, starts_at)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    chat_id INTEGER PRIMARY KEY,
                    text TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def add_event(self, chat_id: int, event: ParsedEvent) -> CalendarEvent:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events(chat_id, title, starts_at, ends_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    chat_id,
                    event.title,
                    event.starts_at.isoformat(),
                    event.ends_at.isoformat(),
                ),
            )
            event_id = int(cursor.lastrowid)
        return CalendarEvent(event_id, chat_id, event.title, event.starts_at, event.ends_at)

    def replace_events(
        self,
        chat_id: int,
        event_ids: list[int],
        event: ParsedEvent,
    ) -> CalendarEvent:
        with self._connect() as conn:
            if event_ids:
                placeholders = ",".join("?" for _ in event_ids)
                conn.execute(
                    f"DELETE FROM events WHERE chat_id = ? AND id IN ({placeholders})",
                    (chat_id, *event_ids),
                )
            cursor = conn.execute(
                """
                INSERT INTO events(chat_id, title, starts_at, ends_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    chat_id,
                    event.title,
                    event.starts_at.isoformat(),
                    event.ends_at.isoformat(),
                ),
            )
            event_id = int(cursor.lastrowid)
        return CalendarEvent(event_id, chat_id, event.title, event.starts_at, event.ends_at)

    def list_events(self, chat_id: int, *, now: datetime | None = None) -> list[CalendarEvent]:
        lower_bound = (now or datetime.now(LOCAL_TZ)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, chat_id, title, starts_at, ends_at
                FROM events
                WHERE chat_id = ? AND ends_at >= ?
                ORDER BY starts_at, id
                """,
                (chat_id, lower_bound),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def events_on_day(self, chat_id: int, target_day: date) -> list[CalendarEvent]:
        day_start = datetime.combine(target_day, time.min, tzinfo=LOCAL_TZ).isoformat()
        day_end = datetime.combine(target_day + timedelta(days=1), time.min, tzinfo=LOCAL_TZ).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, chat_id, title, starts_at, ends_at
                FROM events
                WHERE chat_id = ? AND starts_at < ? AND ends_at > ?
                ORDER BY starts_at, id
                """,
                (chat_id, day_end, day_start),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def conflicting_events(self, chat_id: int, event: ParsedEvent) -> list[CalendarEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, chat_id, title, starts_at, ends_at
                FROM events
                WHERE chat_id = ?
                  AND starts_at < ?
                  AND ends_at > ?
                ORDER BY starts_at, id
                """,
                (chat_id, event.ends_at.isoformat(), event.starts_at.isoformat()),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def delete_event(self, chat_id: int, event_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM events WHERE chat_id = ? AND id = ?",
                (chat_id, event_id),
            )
        return cursor.rowcount > 0

    def set_preference(self, chat_id: int, text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences(chat_id, text, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id) DO UPDATE SET
                    text = excluded.text,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (chat_id, text),
            )

    def get_preference(self, chat_id: int) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT text FROM preferences WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return "" if row is None else str(row[0])


def free_time_blocks(
    events: list[CalendarEvent],
    target_day: date,
    preference: str = "",
) -> list[tuple[datetime, datetime]]:
    work_start = time(9, 0)
    work_end = time(18, 0)
    if _dislikes_morning(preference):
        work_start = time(12, 0)
    if _dislikes_evening(preference):
        work_end = time(17, 0)

    cursor = datetime.combine(target_day, work_start, tzinfo=LOCAL_TZ)
    day_end = datetime.combine(target_day, work_end, tzinfo=LOCAL_TZ)
    blocks: list[tuple[datetime, datetime]] = []

    for event in sorted(events, key=lambda item: item.starts_at):
        start = max(event.starts_at, cursor)
        end = min(event.ends_at, day_end)
        if end <= cursor:
            continue
        if start > cursor:
            blocks.append((cursor, start))
        cursor = max(cursor, end)

    if cursor < day_end:
        blocks.append((cursor, day_end))
    return blocks


def pick_schedule_slot(
    events: list[CalendarEvent],
    request: ScheduleRequest,
    preference: str = "",
) -> tuple[datetime, datetime] | None:
    duration = timedelta(minutes=request.duration_minutes)
    windows = _candidate_windows(request.target_day, request.kind, preference)
    busy_events = sorted(events, key=lambda item: item.starts_at)

    for window_start, window_end in windows:
        cursor = window_start
        for event in busy_events:
            event_start = max(event.starts_at, window_start)
            event_end = min(event.ends_at, window_end)
            if event_end <= cursor:
                continue
            if event_start - cursor >= duration:
                return cursor, cursor + duration
            cursor = max(cursor, event_end)
        if window_end - cursor >= duration:
            return cursor, cursor + duration
    return None


def format_event(event: CalendarEvent) -> str:
    day = event.starts_at.strftime("%m-%d")
    start = event.starts_at.strftime("%H:%M")
    end = event.ends_at.strftime("%H:%M")
    return f"{event.id}. {day} {start}-{end} {event.title}"


def format_datetime_range(starts_at: datetime, ends_at: datetime) -> str:
    return f"{starts_at.strftime('%Y-%m-%d %H:%M')} - {ends_at.strftime('%H:%M')}"


def format_time_range(starts_at: datetime, ends_at: datetime) -> str:
    return f"{starts_at.strftime('%H:%M')}-{ends_at.strftime('%H:%M')}"


def _candidate_windows(
    target_day: date,
    kind: str,
    preference: str,
) -> list[tuple[datetime, datetime]]:
    if kind in {"meal", "lunch", "dinner"}:
        windows: list[tuple[time, time]] = []
        if kind in {"meal", "lunch"}:
            windows.append((time(11, 30), time(13, 30)))
        if kind in {"meal", "dinner"}:
            windows.append((time(17, 30), time(20, 30)))
        return [
            (
                datetime.combine(target_day, start, tzinfo=LOCAL_TZ),
                datetime.combine(target_day, end, tzinfo=LOCAL_TZ),
            )
            for start, end in windows
        ]

    start = time(9, 0)
    end = time(18, 0)
    if _dislikes_morning(preference):
        start = time(12, 0)
    if _dislikes_evening(preference):
        end = time(17, 0)
    return [
        (
            datetime.combine(target_day, start, tzinfo=LOCAL_TZ),
            datetime.combine(target_day, end, tzinfo=LOCAL_TZ),
        )
    ]


def _event_from_row(row: tuple[int, int, str, str, str]) -> CalendarEvent:
    event_id, chat_id, title, starts_at, ends_at = row
    return CalendarEvent(
        id=int(event_id),
        chat_id=int(chat_id),
        title=str(title),
        starts_at=datetime.fromisoformat(starts_at),
        ends_at=datetime.fromisoformat(ends_at),
    )


def _dislikes_morning(preference: str) -> bool:
    return bool(re.search(r"(\u4e0d\u60f3|\u4e0d\u559c\u6b22|\u907f\u514d|\u5c3d\u91cf\u4e0d).{0,6}(\u4e0a\u5348|\u65e9\u4e0a|\u65e9\u6668)", preference))


def _dislikes_evening(preference: str) -> bool:
    return bool(re.search(r"(\u4e0d\u60f3|\u4e0d\u559c\u6b22|\u907f\u514d|\u5c3d\u91cf\u4e0d).{0,6}(\u665a\u4e0a|\u4e0b\u73ed\u540e|\u665a\u95f4)", preference))
