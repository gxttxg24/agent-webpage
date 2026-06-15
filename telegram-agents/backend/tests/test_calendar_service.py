from __future__ import annotations

import pytest

from tg_agent_bot.calendar.service import CalendarServiceError, handle_calendar_request
from tg_agent_bot.calendar.store import ScheduleStore


CHAT_ID = 456


def payload(action: str, **values) -> dict:
    return {"service": "calendar", "action": action, "owner_chat_id": CHAT_ID, **values}


def test_add_event_rejects_conflict_by_default(tmp_path) -> None:
    store = ScheduleStore(tmp_path / "schedule.sqlite3")
    first = handle_calendar_request(
        store,
        payload(
            "add_event",
            title="meeting",
            starts_at="2099-06-10T10:00:00+08:00",
            ends_at="2099-06-10T11:00:00+08:00",
        ),
    )

    second = handle_calendar_request(
        store,
        payload(
            "add_event",
            title="overlap",
            starts_at="2099-06-10T10:30:00+08:00",
            ends_at="2099-06-10T11:30:00+08:00",
        ),
    )

    assert first["added"] is True
    assert second["added"] is False
    assert second["conflict"] is True
    assert second["conflicts"][0]["title"] == "meeting"


def test_add_event_can_replace_conflict(tmp_path) -> None:
    store = ScheduleStore(tmp_path / "schedule.sqlite3")
    handle_calendar_request(
        store,
        payload(
            "add_event",
            title="old",
            starts_at="2099-06-10T10:00:00+08:00",
            ends_at="2099-06-10T11:00:00+08:00",
        ),
    )

    result = handle_calendar_request(
        store,
        payload(
            "add_event",
            title="new",
            starts_at="2099-06-10T10:30:00+08:00",
            ends_at="2099-06-10T11:30:00+08:00",
            on_conflict="replace",
        ),
    )

    events = handle_calendar_request(store, payload("events_on_day", date="2099-06-10"))
    assert result["added"] is True
    assert result["conflict"] is True
    assert [event["title"] for event in events["events"]] == ["new"]


def test_free_time_filters_by_min_duration(tmp_path) -> None:
    store = ScheduleStore(tmp_path / "schedule.sqlite3")
    handle_calendar_request(
        store,
        payload(
            "add_event",
            title="busy",
            starts_at="2099-06-10T10:00:00+08:00",
            ends_at="2099-06-10T17:30:00+08:00",
        ),
    )

    result = handle_calendar_request(
        store,
        payload("free_time", date="2099-06-10", min_duration_minutes=90),
    )

    assert result["blocks"] == []


def test_schedule_event_picks_available_slot(tmp_path) -> None:
    store = ScheduleStore(tmp_path / "schedule.sqlite3")
    result = handle_calendar_request(
        store,
        payload(
            "schedule_event",
            title="focus",
            date="2099-06-10",
            duration_minutes=45,
        ),
    )

    assert result["scheduled"] is True
    assert result["event"]["starts_at"] == "2099-06-10T09:00:00+08:00"
    assert result["event"]["ends_at"] == "2099-06-10T09:45:00+08:00"


def test_move_reschedule_delete_and_preferences(tmp_path) -> None:
    store = ScheduleStore(tmp_path / "schedule.sqlite3")
    created = handle_calendar_request(
        store,
        payload(
            "add_event",
            title="call",
            starts_at="2099-06-10T10:00:00+08:00",
            ends_at="2099-06-10T11:00:00+08:00",
        ),
    )
    event_id = created["event"]["id"]

    moved = handle_calendar_request(
        store,
        payload("move_event", event_id=event_id, shift_minutes=60),
    )
    assert moved["updated"] is True
    assert moved["event"]["starts_at"] == "2099-06-10T11:00:00+08:00"

    rescheduled = handle_calendar_request(
        store,
        payload("reschedule_event", event_id=moved["event"]["id"], to_date="2099-06-11"),
    )
    assert rescheduled["updated"] is True
    assert rescheduled["event"]["starts_at"] == "2099-06-11T11:00:00+08:00"

    preference = handle_calendar_request(store, payload("set_preference", preference="avoid mornings"))
    assert preference["saved"] is True
    assert handle_calendar_request(store, payload("get_preference"))["preference"] == "avoid mornings"

    deleted = handle_calendar_request(
        store,
        payload("delete_event", event_id=rescheduled["event"]["id"]),
    )
    assert deleted["deleted"] is True


def test_invalid_calendar_payload_raises(tmp_path) -> None:
    store = ScheduleStore(tmp_path / "schedule.sqlite3")

    with pytest.raises(CalendarServiceError, match="title is required"):
        handle_calendar_request(store, {"action": "add_event", "owner_chat_id": CHAT_ID})
