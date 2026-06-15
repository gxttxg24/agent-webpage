from __future__ import annotations

import asyncio
from datetime import date

import pytest

import tg_agent_bot.weather.service as weather


class FakeResponse:
    def __init__(self, payload: dict, status_error: Exception | None = None) -> None:
        self._payload = payload
        self._status_error = status_error

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error


class FakeAsyncClient:
    def __init__(self, responses: list[FakeResponse], timeout: float | None = None) -> None:
        self.responses = responses
        self.timeout = timeout
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, params: dict) -> FakeResponse:
        self.calls.append((url, params))
        if not self.responses:
            raise AssertionError("No fake response left.")
        return self.responses.pop(0)


def hourly_forecast_payload() -> dict:
    return {
        "hourly": {
            "time": [
                "2099-06-10T00:00",
                "2099-06-10T01:00",
                "2099-06-10T02:00",
                "2099-06-10T03:00",
            ],
            "precipitation_probability": [10, 30, 80, None],
            "precipitation": [0.0, 0.2, 1.5, None],
            "weather_code": [0, 3, 61, None],
            "temperature_2m": [22.0, 23.0, 24.0, None],
        }
    }


def test_hourly_entries_filters_target_day_and_labels_weather() -> None:
    forecast = {
        "hourly": {
            "time": ["2099-06-09T23:00", "2099-06-10T00:00"],
            "precipitation_probability": [90, 10],
            "precipitation": [2.0, 0.0],
            "weather_code": [61, 0],
            "temperature_2m": [20.0, 22.0],
        }
    }

    entries = weather._hourly_entries(forecast, date(2099, 6, 10))

    assert entries == [
        {
            "time": "2099-06-10T00:00",
            "precipitation_probability": 10,
            "precipitation_mm": 0.0,
            "weather_code": 0,
            "weather": weather.weather_code_label(0),
            "temperature_2m_c": 22.0,
        }
    ]


def test_period_entries_aggregates_hourly_data() -> None:
    hourly = weather._hourly_entries(hourly_forecast_payload(), date(2099, 6, 10))

    periods = weather._period_entries(hourly, interval_hours=3)

    assert periods[0] == {
        "starts_at": "2099-06-10T00:00",
        "ends_at": "2099-06-10T03:00",
        "max_precipitation_probability": 80,
        "precipitation_mm_sum": 1.7,
        "weather_code": 61,
        "weather": weather.weather_code_label(61),
        "temperature_2m_c_avg": 23.0,
    }
    assert periods[1]["starts_at"] == "2099-06-10T03:00"
    assert periods[1]["max_precipitation_probability"] is None


def test_geocode_prefers_requested_country_code() -> None:
    client = FakeAsyncClient(
        [
            FakeResponse(
                {
                    "results": [
                        {
                            "name": "Paris",
                            "country_code": "US",
                            "latitude": 33.66,
                            "longitude": -95.55,
                        },
                        {
                            "name": "Paris",
                            "country_code": "FR",
                            "latitude": 48.85,
                            "longitude": 2.35,
                            "admin1": "Ile-de-France",
                            "country": "France",
                        },
                    ]
                }
            )
        ]
    )

    location = asyncio.run(weather._geocode(client, "Paris", "FR"))

    assert location["country_code"] == "FR"
    assert location["latitude"] == 48.85
    assert location["longitude"] == 2.35


def test_geocode_raises_when_location_missing() -> None:
    client = FakeAsyncClient([FakeResponse({"results": []})])

    with pytest.raises(weather.WeatherServiceError, match="Location not found"):
        asyncio.run(weather._geocode(client, "Atlantis", "CN"))


def test_forecast_requires_hourly_data() -> None:
    client = FakeAsyncClient([FakeResponse({"daily": {}})])

    with pytest.raises(weather.WeatherServiceError, match="hourly data"):
        asyncio.run(
            weather._forecast(
                client,
                {"latitude": 31.2, "longitude": 121.5},
                date(2099, 6, 10),
                "Asia/Shanghai",
            )
        )


def test_handle_weather_request_uses_fake_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeAsyncClient(
        [
            FakeResponse(
                {
                    "results": [
                        {
                            "name": "上海",
                            "admin1": "上海市",
                            "country": "中国",
                            "country_code": "CN",
                            "latitude": 31.23,
                            "longitude": 121.47,
                        }
                    ]
                }
            ),
            FakeResponse(hourly_forecast_payload()),
        ]
    )
    monkeypatch.setattr(weather.httpx, "AsyncClient", lambda timeout: fake_client)

    result = asyncio.run(
        weather.handle_weather_request(
            {
                "service": "weather",
                "action": "hourly_forecast",
                "location": "上海",
                "date": "2099-06-10",
                "interval_hours": 3,
                "include_hours": True,
            }
        )
    )

    assert result["ok"] is True
    assert result["location"]["name"] == "上海"
    assert result["periods"][0]["max_precipitation_probability"] == 80
    assert len(result["hours"]) == 4
    assert [call[0] for call in fake_client.calls] == [
        weather.GEOCODING_URL,
        weather.FORECAST_URL,
    ]


def test_handle_weather_request_validates_payload_before_network() -> None:
    with pytest.raises(weather.WeatherServiceError, match="location is required"):
        asyncio.run(
            weather.handle_weather_request(
                {"action": "hourly_forecast", "date": "2099-06-10"}
            )
        )
