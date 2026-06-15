from __future__ import annotations

from datetime import date, datetime

from tg_agent_bot.calendar.store import (
    LOCAL_TZ,
    ParsedEvent,
    ScheduleRequest,
    ScheduleStore,
    free_time_blocks,
    pick_schedule_slot,
)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=LOCAL_TZ)


def test_store_add_list_query_conflict_delete_and_preferences(tmp_path) -> None:
    store = ScheduleStore(tmp_path / "schedule.sqlite3")
    chat_id = 123
    event = ParsedEvent("standup", dt("2099-06-10T10:00:00"), dt("2099-06-10T11:00:00"))

    created = store.add_event(chat_id, event)

    assert created.id > 0
    assert store.list_events(chat_id, now=dt("2099-06-10T00:00:00")) == [created]
    assert store.events_on_day(chat_id, date(2099, 6, 10)) == [created]
    assert store.conflicting_events(
        chat_id,
        ParsedEvent("overlap", dt("2099-06-10T10:30:00"), dt("2099-06-10T11:30:00")),
    ) == [created]

    store.set_preference(chat_id, "avoid mornings")
    assert store.get_preference(chat_id) == "avoid mornings"
    assert store.delete_event(chat_id, created.id)
    assert store.events_on_day(chat_id, date(2099, 6, 10)) == []


def test_free_time_blocks_respects_busy_events_and_preferences() -> None:
    target_day = date(2099, 6, 10)
    busy = [
        ParsedEvent("morning", dt("2099-06-10T10:00:00"), dt("2099-06-10T11:00:00")),
        ParsedEvent("afternoon", dt("2099-06-10T14:00:00"), dt("2099-06-10T15:30:00")),
    ]
    events = [
        type("Event", (), {"starts_at": item.starts_at, "ends_at": item.ends_at})()
        for item in busy
    ]

    blocks = free_time_blocks(events, target_day)

    assert blocks == [
        (dt("2099-06-10T09:00:00"), dt("2099-06-10T10:00:00")),
        (dt("2099-06-10T11:00:00"), dt("2099-06-10T14:00:00")),
        (dt("2099-06-10T15:30:00"), dt("2099-06-10T18:00:00")),
    ]

    afternoon_only = free_time_blocks(events, target_day, "不想上午开会")
    assert afternoon_only[0][0] == dt("2099-06-10T12:00:00")


def test_pick_schedule_slot_uses_first_available_window() -> None:
    target_day = date(2099, 6, 10)
    events = [
        type(
            "Event",
            (),
            {
                "starts_at": dt("2099-06-10T09:00:00"),
                "ends_at": dt("2099-06-10T10:00:00"),
            },
        )()
    ]
    request = ScheduleRequest(
        title="focus",
        target_day=target_day,
        duration_minutes=60,
    )

    assert pick_schedule_slot(events, request) == (
        dt("2099-06-10T10:00:00"),
        dt("2099-06-10T11:00:00"),
    )


def test_pick_schedule_slot_returns_none_when_duration_does_not_fit() -> None:
    target_day = date(2099, 6, 10)
    request = ScheduleRequest(
        title="workshop",
        target_day=target_day,
        duration_minutes=10 * 60,
    )

    assert pick_schedule_slot([], request) is None
