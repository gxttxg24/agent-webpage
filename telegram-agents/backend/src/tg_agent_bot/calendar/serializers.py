from __future__ import annotations

from datetime import datetime
from typing import Any

from .store import CalendarEvent


def event_to_dict(
    event: CalendarEvent,
    *,
    include_chat_id: bool = True,
    include_time_labels: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": event.id,
        "title": event.title,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat(),
        "duration_minutes": int((event.ends_at - event.starts_at).total_seconds() // 60),
    }
    if include_chat_id:
        data["chat_id"] = event.chat_id
    if include_time_labels:
        data["start_time"] = event.starts_at.strftime("%H:%M")
        data["end_time"] = event.ends_at.strftime("%H:%M")
    return data


def block_to_dict(starts_at: datetime, ends_at: datetime) -> dict[str, Any]:
    return {
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "duration_minutes": int((ends_at - starts_at).total_seconds() // 60),
    }
