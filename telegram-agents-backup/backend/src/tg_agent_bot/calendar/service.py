from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..common.parsing import parse_iso_date, parse_iso_datetime, required_text
from .serializers import block_to_dict, event_to_dict
from .store import (
    CalendarEvent,
    LOCAL_TZ,
    ParsedEvent,
    ScheduleRequest,
    ScheduleStore,
    free_time_blocks,
    pick_schedule_slot,
)


class CalendarServiceError(ValueError):
    pass


def handle_calendar_request(
    schedule: ScheduleStore,
    payload: dict[str, Any],
) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip().lower()
    owner_chat_id = _owner_chat_id(payload)

    if action == "list_events":
        events = schedule.list_events(owner_chat_id)
        return _ok(action, events=[event_to_dict(event) for event in events])

    if action == "events_on_day":
        target_day = _parse_date(payload.get("date"))
        events = schedule.events_on_day(owner_chat_id, target_day)
        return _ok(
            action,
            date=target_day.isoformat(),
            events=[event_to_dict(event) for event in events],
        )

    if action == "free_time":
        target_day = _parse_date(payload.get("date"))
        preference = str(payload.get("preference") or schedule.get_preference(owner_chat_id))
        blocks = free_time_blocks(schedule.events_on_day(owner_chat_id, target_day), target_day, preference)
        min_duration = int(payload.get("min_duration_minutes", 0) or 0)
        return _ok(
            action,
            date=target_day.isoformat(),
            min_duration_minutes=min_duration,
            blocks=[
                block_to_dict(start, end)
                for start, end in blocks
                if min_duration <= 0 or int((end - start).total_seconds() // 60) >= min_duration
            ],
        )

    if action == "add_event":
        event = _parsed_event(payload)
        conflicts = schedule.conflicting_events(owner_chat_id, event)
        on_conflict = str(payload.get("on_conflict", "reject")).strip().lower()
        if conflicts and on_conflict != "replace":
            return _ok(
                action,
                added=False,
                conflict=True,
                conflicts=[event_to_dict(item) for item in conflicts],
            )
        created = (
            schedule.replace_events(owner_chat_id, [item.id for item in conflicts], event)
            if conflicts
            else schedule.add_event(owner_chat_id, event)
        )
        return _ok(
            action,
            added=True,
            conflict=bool(conflicts),
            event=event_to_dict(created),
            replaced_event_ids=[item.id for item in conflicts],
        )

    if action == "schedule_event":
        target_day = _parse_date(payload.get("date") or payload.get("target_day"))
        request = ScheduleRequest(
            title=_required_text(payload, "title"),
            target_day=target_day,
            duration_minutes=int(payload.get("duration_minutes") or 0),
            kind=str(payload.get("kind", "default")).strip().lower() or "default",
        )
        if request.duration_minutes <= 0:
            raise CalendarServiceError("duration_minutes must be positive.")
        preference = str(payload.get("preference") or schedule.get_preference(owner_chat_id))
        slot = pick_schedule_slot(
            schedule.events_on_day(owner_chat_id, target_day),
            request,
            preference,
        )
        if slot is None:
            return _ok(
                action,
                scheduled=False,
                date=target_day.isoformat(),
                reason="no_available_slot",
            )
        starts_at, ends_at = slot
        event = schedule.add_event(owner_chat_id, ParsedEvent(request.title, starts_at, ends_at))
        return _ok(action, scheduled=True, event=event_to_dict(event))

    if action == "delete_event":
        event_id = int(payload.get("event_id") or 0)
        if event_id <= 0:
            raise CalendarServiceError("event_id must be positive.")
        return _ok(action, deleted=schedule.delete_event(owner_chat_id, event_id), event_id=event_id)

    if action == "move_event":
        event = _find_single_event(schedule, owner_chat_id, payload)
        shift_minutes = int(payload.get("shift_minutes") or 0)
        if shift_minutes == 0:
            raise CalendarServiceError("shift_minutes must not be zero.")
        shifted = ParsedEvent(
            title=event.title,
            starts_at=event.starts_at + timedelta(minutes=shift_minutes),
            ends_at=event.ends_at + timedelta(minutes=shift_minutes),
        )
        return _replace_single_event(schedule, owner_chat_id, event, shifted, payload, action)

    if action == "reschedule_event":
        event = _find_single_event(schedule, owner_chat_id, payload)
        target_day = _parse_date(payload.get("to_date") or payload.get("date"))
        moved = ParsedEvent(
            title=event.title,
            starts_at=datetime.combine(target_day, event.starts_at.timetz()),
            ends_at=datetime.combine(target_day, event.ends_at.timetz()),
        )
        return _replace_single_event(schedule, owner_chat_id, event, moved, payload, action)

    if action == "set_preference":
        preference = _required_text(payload, "preference")
        schedule.set_preference(owner_chat_id, preference)
        return _ok(action, saved=True, preference=preference)

    if action == "get_preference":
        return _ok(action, preference=schedule.get_preference(owner_chat_id))

    raise CalendarServiceError(f"Unsupported calendar action: {action or '(missing)'}.")


def is_calendar_request(payload: dict[str, Any]) -> bool:
    return str(payload.get("service", "")).strip().lower() == "calendar"


def _ok(action: str, **data: Any) -> dict[str, Any]:
    return {
        "kind": "calendar.result",
        "service": "calendar",
        "action": action,
        "ok": True,
        **data,
    }


def _owner_chat_id(payload: dict[str, Any]) -> int:
    value = payload.get("owner_chat_id") or payload.get("chat_id") or payload.get("user_id")
    try:
        owner_chat_id = int(value)
    except (TypeError, ValueError) as exc:
        raise CalendarServiceError("owner_chat_id must be an integer.") from exc
    if owner_chat_id == 0:
        raise CalendarServiceError("owner_chat_id must not be zero.")
    return owner_chat_id


def _parsed_event(payload: dict[str, Any]) -> ParsedEvent:
    title = _required_text(payload, "title")
    starts_at = _parse_datetime(payload.get("starts_at") or payload.get("start"))
    ends_at = _parse_datetime(payload.get("ends_at") or payload.get("end"))
    if ends_at <= starts_at:
        raise CalendarServiceError("ends_at must be after starts_at.")
    return ParsedEvent(title=title, starts_at=starts_at, ends_at=ends_at)


def _find_single_event(
    schedule: ScheduleStore,
    owner_chat_id: int,
    payload: dict[str, Any],
) -> CalendarEvent:
    event_id = int(payload.get("event_id") or 0)
    target_day_value = payload.get("from_date") or payload.get("date")
    title_contains = str(payload.get("title_contains") or payload.get("title") or "").strip()

    events = (
        schedule.events_on_day(owner_chat_id, _parse_date(target_day_value))
        if target_day_value
        else schedule.list_events(owner_chat_id)
    )
    if event_id > 0:
        events = [event for event in events if event.id == event_id]
    if title_contains:
        events = [event for event in events if title_contains in event.title]

    if not events:
        raise CalendarServiceError("No matching event found.")
    if len(events) > 1:
        raise CalendarServiceError(
            "Multiple matching events found: "
            + ", ".join(f"{event.id}:{event.title}" for event in events[:5])
        )
    return events[0]


def _replace_single_event(
    schedule: ScheduleStore,
    owner_chat_id: int,
    old_event: CalendarEvent,
    new_event: ParsedEvent,
    payload: dict[str, Any],
    action: str,
) -> dict[str, Any]:
    conflicts = [
        event
        for event in schedule.conflicting_events(owner_chat_id, new_event)
        if event.id != old_event.id
    ]
    on_conflict = str(payload.get("on_conflict", "reject")).strip().lower()
    if conflicts and on_conflict != "replace":
        return _ok(
            action,
            updated=False,
            conflict=True,
            original_event=event_to_dict(old_event),
            proposed_event={
                "title": new_event.title,
                "starts_at": new_event.starts_at.isoformat(),
                "ends_at": new_event.ends_at.isoformat(),
            },
            conflicts=[event_to_dict(item) for item in conflicts],
        )

    replaced_ids = [old_event.id, *[event.id for event in conflicts]]
    created = schedule.replace_events(owner_chat_id, replaced_ids, new_event)
    return _ok(
        action,
        updated=True,
        conflict=bool(conflicts),
        original_event=event_to_dict(old_event),
        event=event_to_dict(created),
        replaced_event_ids=replaced_ids,
    )


def _required_text(payload: dict[str, Any], key: str) -> str:
    return required_text(payload, key, CalendarServiceError)


def _parse_date(value: Any):
    return parse_iso_date(value, CalendarServiceError)


def _parse_datetime(value: Any) -> datetime:
    return parse_iso_datetime(value, CalendarServiceError, default_tz=LOCAL_TZ)
