from __future__ import annotations

import pytest

from tg_agent_bot.slot_matcher.service import (
    SlotMatcherServiceError,
    handle_slot_matcher_request,
    is_slot_matcher_request,
)


def base_payload(**values) -> dict:
    return {
        "service": "slot_matcher",
        "action": "match_slots",
        "duration_minutes": 60,
        "rain_threshold": 30,
        "calendar_blocks": [
            {
                "starts_at": "2099-06-10T09:00:00+08:00",
                "ends_at": "2099-06-10T12:00:00+08:00",
            }
        ],
        "weather_periods": [
            {
                "starts_at": "2099-06-10T09:00",
                "ends_at": "2099-06-10T10:00",
                "weather": "clear",
                "max_precipitation_probability": 10,
            },
            {
                "starts_at": "2099-06-10T10:00",
                "ends_at": "2099-06-10T12:00",
                "weather": "rain",
                "max_precipitation_probability": 80,
            },
        ],
        **values,
    }


def test_is_slot_matcher_request() -> None:
    assert is_slot_matcher_request({"service": "slot_matcher"})
    assert not is_slot_matcher_request({"service": "calendar"})


def test_avoid_rain_returns_low_probability_overlap() -> None:
    result = handle_slot_matcher_request(base_payload(goal="avoid_rain"))

    assert result["ok"] is True
    assert result["matches"] == [
        {
            "starts_at": "2099-06-10T09:00:00+08:00",
            "ends_at": "2099-06-10T10:00:00+08:00",
            "available_until": "2099-06-10T10:00:00+08:00",
            "duration_minutes": 60,
            "weather": "clear",
            "max_precipitation_probability": 10,
        }
    ]


def test_prefer_rain_returns_high_probability_overlap() -> None:
    result = handle_slot_matcher_request(base_payload(goal="prefer_rain"))

    assert result["matches"][0]["starts_at"] == "2099-06-10T10:00:00+08:00"
    assert result["matches"][0]["max_precipitation_probability"] == 80


def test_forecast_accepts_any_weather_and_sorts_by_probability() -> None:
    result = handle_slot_matcher_request(base_payload(goal="forecast"))

    assert [match["max_precipitation_probability"] for match in result["matches"]] == [10, 80]


def test_duration_must_fit_intersection() -> None:
    result = handle_slot_matcher_request(base_payload(duration_minutes=180, goal="prefer_rain"))

    assert result["matches"] == []


@pytest.mark.parametrize(
    "patch,error",
    [
        ({"duration_minutes": 0}, "duration_minutes must be positive"),
        ({"action": "unknown"}, "Unsupported slot matcher action"),
        ({"calendar_blocks": []}, "calendar_blocks must contain"),
        ({"weather_periods": "bad"}, "weather_periods must be a list"),
    ],
)
def test_invalid_slot_matcher_payload_raises(patch: dict, error: str) -> None:
    with pytest.raises(SlotMatcherServiceError, match=error):
        handle_slot_matcher_request(base_payload(**patch))
