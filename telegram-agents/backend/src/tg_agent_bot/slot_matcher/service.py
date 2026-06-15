from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..calendar.store import LOCAL_TZ
from ..common.parsing import parse_iso_datetime


class SlotMatcherServiceError(ValueError):
    pass


def is_slot_matcher_request(payload: dict[str, Any]) -> bool:
    return str(payload.get("service", "")).strip().lower() == "slot_matcher"


def handle_slot_matcher_request(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "match_slots")).strip().lower()
    if action != "match_slots":
        raise SlotMatcherServiceError(f"Unsupported slot matcher action: {action}.")

    duration_minutes = int(payload.get("duration_minutes") or 0)
    if duration_minutes <= 0:
        raise SlotMatcherServiceError("duration_minutes must be positive.")

    goal = str(payload.get("goal", "avoid_rain")).strip().lower()
    rain_threshold = int(payload.get("rain_threshold", 30))
    calendar_blocks = _list_of_dicts(payload.get("calendar_blocks"), "calendar_blocks")
    weather_periods = _list_of_dicts(payload.get("weather_periods"), "weather_periods")

    matches: list[dict[str, Any]] = []
    duration = timedelta(minutes=duration_minutes)
    for block in calendar_blocks:
        block_start = _parse_datetime(block.get("starts_at"))
        block_end = _parse_datetime(block.get("ends_at"))
        for period in weather_periods:
            probability = _rain_probability(period)
            if probability is None:
                continue
            if goal == "prefer_rain":
                weather_ok = probability >= rain_threshold
            elif goal == "forecast":
                weather_ok = True
            else:
                weather_ok = probability <= rain_threshold
            if not weather_ok:
                continue

            period_start = _parse_datetime(period.get("starts_at"))
            period_end = _parse_datetime(period.get("ends_at"))
            start = max(block_start, period_start)
            end = min(block_end, period_end)
            if end - start < duration:
                continue
            candidate_end = start + duration
            matches.append(
                {
                    "starts_at": start.isoformat(),
                    "ends_at": candidate_end.isoformat(),
                    "available_until": end.isoformat(),
                    "duration_minutes": duration_minutes,
                    "weather": period.get("weather") or "未知",
                    "max_precipitation_probability": probability,
                }
            )

    matches.sort(key=lambda item: _sort_key(item, goal))
    return {
        "kind": "slot_matcher.result",
        "service": "slot_matcher",
        "action": action,
        "ok": True,
        "goal": goal,
        "duration_minutes": duration_minutes,
        "rain_threshold": rain_threshold,
        "matches": matches[:10],
    }


def _sort_key(item: dict[str, Any], goal: str) -> tuple[int, str]:
    probability = int(item.get("max_precipitation_probability") or 0)
    if goal == "prefer_rain":
        return (-probability, str(item.get("starts_at", "")))
    return (probability, str(item.get("starts_at", "")))


def _rain_probability(period: dict[str, Any]) -> int | None:
    value = period.get("max_precipitation_probability")
    if value is None:
        return None
    return int(value)


def _list_of_dicts(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SlotMatcherServiceError(f"{field} must be a list.")
    items = [item for item in value if isinstance(item, dict)]
    if not items:
        raise SlotMatcherServiceError(f"{field} must contain at least one object.")
    return items


def _parse_datetime(value: Any) -> datetime:
    return parse_iso_datetime(
        value,
        SlotMatcherServiceError,
        default_tz=LOCAL_TZ,
        allow_minute_precision=True,
    )
