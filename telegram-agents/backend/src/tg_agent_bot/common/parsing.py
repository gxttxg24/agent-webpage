from __future__ import annotations

from datetime import date, datetime, tzinfo
from typing import Any


def required_text(payload: dict[str, Any], key: str, error_type: type[Exception]) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise error_type(f"{key} is required.")
    return value


def parse_iso_date(value: Any, error_type: type[Exception]) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise error_type("date must use YYYY-MM-DD.") from exc


def parse_iso_datetime(
    value: Any,
    error_type: type[Exception],
    *,
    default_tz: tzinfo,
    example: str = "2026-06-05T14:00:00+08:00",
    allow_minute_precision: bool = False,
) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise error_type("datetime value is required.")
    if allow_minute_precision and len(raw) == 16:
        raw = raw + ":00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise error_type(f"datetime must be ISO 8601, for example {example}.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed
