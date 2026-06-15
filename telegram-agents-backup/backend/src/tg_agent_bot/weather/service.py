from __future__ import annotations

"""WeatherBot backend service."""

from collections import Counter
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any
from urllib.parse import urlencode

import httpx

from ..common.parsing import parse_iso_date, required_text


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TIMEZONE = "Asia/Shanghai"


class WeatherServiceError(ValueError):
    pass


async def handle_weather_request(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "hourly_forecast")).strip().lower()
    if action not in {"hourly_forecast", "forecast"}:
        raise WeatherServiceError(f"Unsupported weather action: {action}.")

    location_query = _required_text(payload, "location")
    target_day = _parse_date(payload.get("date"))
    interval_hours = int(payload.get("interval_hours", 3) or 3)
    if interval_hours <= 0 or interval_hours > 24:
        raise WeatherServiceError("interval_hours must be between 1 and 24.")

    country_code = str(payload.get("country_code", "CN")).strip().upper() or "CN"
    timezone = str(payload.get("timezone", DEFAULT_TIMEZONE)).strip() or DEFAULT_TIMEZONE
    include_hours = bool(payload.get("include_hours", False))

    async with httpx.AsyncClient(timeout=15.0) as client:
        location = await _geocode(client, location_query, country_code)
        forecast_url, forecast = await _forecast(client, location, target_day, timezone)

    hourly = _hourly_entries(forecast, target_day)
    periods = _period_entries(hourly, interval_hours)
    result = {
        "kind": "weather.result",
        "service": "weather",
        "action": action,
        "ok": True,
        "location_query": location_query,
        "location": location,
        "date": target_day.isoformat(),
        "timezone": timezone,
        "interval_hours": interval_hours,
        "periods": periods,
        "source": {
            "provider": "Open-Meteo",
            "geocoding_url": GEOCODING_URL,
            "forecast_url": forecast_url,
        },
    }
    if include_hours:
        result["hours"] = hourly
    return result


def is_weather_request(payload: dict[str, Any]) -> bool:
    return str(payload.get("service", "")).strip().lower() == "weather"


async def _geocode(
    client: httpx.AsyncClient,
    location_query: str,
    country_code: str,
) -> dict[str, Any]:
    params = {
        "name": location_query,
        "count": 10,
        "language": "zh",
        "format": "json",
    }
    response = await client.get(GEOCODING_URL, params=params)
    response.raise_for_status()
    data = response.json()
    results = data.get("results") or []
    if not isinstance(results, list) or not results:
        raise WeatherServiceError(f"Location not found: {location_query}.")

    selected = None
    for item in results:
        if str(item.get("country_code", "")).upper() == country_code:
            selected = item
            break
    if selected is None:
        selected = results[0]

    try:
        latitude = float(selected["latitude"])
        longitude = float(selected["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherServiceError(f"Invalid geocoding result for {location_query}.") from exc

    return {
        "name": str(selected.get("name", location_query)),
        "admin1": str(selected.get("admin1", "")),
        "admin2": str(selected.get("admin2", "")),
        "country": str(selected.get("country", "")),
        "country_code": str(selected.get("country_code", "")),
        "latitude": latitude,
        "longitude": longitude,
    }


async def _forecast(
    client: httpx.AsyncClient,
    location: dict[str, Any],
    target_day: date,
    timezone: str,
) -> tuple[str, dict[str, Any]]:
    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "hourly": "precipitation_probability,precipitation,weather_code,temperature_2m",
        "start_date": target_day.isoformat(),
        "end_date": target_day.isoformat(),
        "timezone": timezone,
    }
    url = f"{FORECAST_URL}?{urlencode(params)}"
    response = await client.get(FORECAST_URL, params=params)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data.get("hourly"), dict):
        raise WeatherServiceError("Forecast response does not contain hourly data.")
    return url, data


def _hourly_entries(forecast: dict[str, Any], target_day: date) -> list[dict[str, Any]]:
    hourly = forecast["hourly"]
    times = hourly.get("time") or []
    probabilities = hourly.get("precipitation_probability") or []
    precipitation = hourly.get("precipitation") or []
    weather_codes = hourly.get("weather_code") or []
    temperatures = hourly.get("temperature_2m") or []

    entries: list[dict[str, Any]] = []
    for index, time_text in enumerate(times):
        parsed_time = datetime.fromisoformat(str(time_text))
        if parsed_time.date() != target_day:
            continue
        code = _list_value(weather_codes, index)
        entries.append(
            {
                "time": str(time_text),
                "precipitation_probability": _optional_int(_list_value(probabilities, index)),
                "precipitation_mm": _optional_float(_list_value(precipitation, index)),
                "weather_code": _optional_int(code),
                "weather": weather_code_label(_optional_int(code)),
                "temperature_2m_c": _optional_float(_list_value(temperatures, index)),
            }
        )
    if not entries:
        raise WeatherServiceError("No hourly forecast entries were returned for the requested date.")
    return entries


def _period_entries(hourly: list[dict[str, Any]], interval_hours: int) -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = []
    for offset in range(0, len(hourly), interval_hours):
        chunk = hourly[offset : offset + interval_hours]
        if not chunk:
            continue
        precipitation_probabilities = [
            item["precipitation_probability"]
            for item in chunk
            if item["precipitation_probability"] is not None
        ]
        precipitation_values = [
            item["precipitation_mm"]
            for item in chunk
            if item["precipitation_mm"] is not None
        ]
        temperatures = [
            item["temperature_2m_c"]
            for item in chunk
            if item["temperature_2m_c"] is not None
        ]
        weather_codes = [
            item["weather_code"]
            for item in chunk
            if item["weather_code"] is not None
        ]
        representative_code = _representative_weather_code(weather_codes)
        periods.append(
            {
                "starts_at": chunk[0]["time"],
                "ends_at": _period_end(chunk[-1]["time"]),
                "max_precipitation_probability": max(precipitation_probabilities)
                if precipitation_probabilities
                else None,
                "precipitation_mm_sum": round(sum(precipitation_values), 2)
                if precipitation_values
                else None,
                "weather_code": representative_code,
                "weather": weather_code_label(representative_code),
                "temperature_2m_c_avg": round(mean(temperatures), 1) if temperatures else None,
            }
        )
    return periods


def weather_code_label(code: int | None) -> str:
    labels = {
        0: "晴",
        1: "基本晴朗",
        2: "局部多云",
        3: "阴",
        45: "雾",
        48: "霜雾",
        51: "小毛毛雨",
        53: "中等毛毛雨",
        55: "大毛毛雨",
        56: "冻毛毛雨",
        57: "强冻毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        66: "冻雨",
        67: "强冻雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        77: "雪粒",
        80: "小阵雨",
        81: "中等阵雨",
        82: "强阵雨",
        85: "小阵雪",
        86: "强阵雪",
        95: "雷暴",
        96: "雷暴伴小冰雹",
        99: "雷暴伴大冰雹",
    }
    if code is None:
        return "未知"
    return labels.get(code, f"未知天气({code})")


def _representative_weather_code(codes: list[int]) -> int | None:
    if not codes:
        return None
    rainy_codes = [code for code in codes if code >= 51]
    if rainy_codes:
        return Counter(rainy_codes).most_common(1)[0][0]
    return Counter(codes).most_common(1)[0][0]


def _period_end(time_text: str) -> str:
    return (datetime.fromisoformat(time_text) + timedelta(hours=1)).isoformat(timespec="minutes")


def _list_value(values: list[Any], index: int) -> Any:
    if index >= len(values):
        return None
    return values[index]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _required_text(payload: dict[str, Any], key: str) -> str:
    return required_text(payload, key, WeatherServiceError)


def _parse_date(value: Any) -> date:
    return parse_iso_date(value, WeatherServiceError)
