from __future__ import annotations

from typing import Any

def summarize_calendar_result(payload: dict[str, Any]) -> str:
    action = str(payload.get("action", ""))
    if payload.get("ok") is not True:
        return f"日程操作失败：{payload.get('error') or '未知错误'}"

    if action == "list_events":
        events = payload.get("events") or []
        if not events:
            return "你目前没有未来日程。"
        return "未来日程：\n" + "\n".join(_event_line(event) for event in events)

    if action == "events_on_day":
        events = payload.get("events") or []
        if not events:
            return f"{payload.get('date')} 没有日程。"
        return f"{payload.get('date')} 的日程：\n" + "\n".join(_event_line(event) for event in events)

    if action == "free_time":
        blocks = payload.get("blocks") or []
        if not blocks:
            return f"{payload.get('date')} 没有符合条件的空闲时间。"
        return f"{payload.get('date')} 可用时间：\n" + "\n".join(_block_line(block) for block in blocks)

    if action == "add_event":
        if payload.get("added"):
            return "已添加日程：" + _event_line(payload.get("event") or {})
        conflicts = payload.get("conflicts") or []
        return "日程冲突，暂未添加：\n" + "\n".join(_event_line(event) for event in conflicts)

    if action == "schedule_event":
        if payload.get("scheduled"):
            return "已安排日程：" + _event_line(payload.get("event") or {})
        return f"{payload.get('date')} 没找到合适空档。"

    if action == "delete_event":
        return f"已删除事件 {payload.get('event_id')}。" if payload.get("deleted") else f"没有找到事件 {payload.get('event_id')}。"

    if action == "set_preference":
        return "已保存你的日程偏好。"

    if action == "get_preference":
        return f"你的日程偏好：{payload.get('preference') or '暂无'}"

    if action in {"move_event", "reschedule_event"}:
        if payload.get("updated"):
            return "已更新日程：" + _event_line(payload.get("event") or {})
        conflicts = payload.get("conflicts") or []
        if conflicts:
            return "更新后会冲突，暂未修改：\n" + "\n".join(_event_line(event) for event in conflicts)
        return "未能更新日程。"

    return f"日程操作完成：{action}"


def calendar_context_from_result(
    user_text: str,
    actions: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for result in results:
        event = result.get("event")
        if isinstance(event, dict):
            events.append(event)
        for item in result.get("events") or []:
            if isinstance(item, dict):
                events.append(item)
    return {
        "user_text": user_text,
        "actions": actions,
        "results": results,
        "events": events[-8:],
    }


def summarize_weather_results(
    results: list[dict[str, Any]],
    *,
    goal: str = "forecast",
    rain_threshold: int = 30,
) -> str:
    if not results:
        return "天气查询没有返回结果。"

    lines: list[str] = []
    for result in results:
        if result.get("ok") is not True:
            lines.append(f"天气查询失败：{result.get('error') or '未知错误'}")
            continue
        location = result.get("location") or {}
        location_name = location.get("name") if isinstance(location, dict) else ""
        title = f"{location_name or result.get('location_query') or '该地区'} {result.get('date')} 天气"
        periods = result.get("periods") or []
        if goal == "avoid_rain":
            good_periods = [
                period for period in periods
                if _period_rain_probability(period) is not None
                and _period_rain_probability(period) <= rain_threshold
            ]
            if good_periods:
                lines.append(
                    title
                    + f"\n降水概率不高于 {rain_threshold}% 的时段：\n"
                    + "\n".join(_weather_period_line(period) for period in good_periods)
                )
            else:
                lines.append(
                    title
                    + f"\n没有找到降水概率不高于 {rain_threshold}% 的时段。"
                )
        else:
            lines.append(
                title + "：\n" + "\n".join(_weather_period_line(period) for period in periods)
            )
    return "\n\n".join(lines)

def _event_line(event: dict[str, Any]) -> str:
    event_id = event.get("id", "?")
    title = event.get("title", "未命名")
    starts_at = _compact_datetime(str(event.get("starts_at", "")))
    ends_at = _compact_time(str(event.get("ends_at", "")))
    return f"{event_id}. {starts_at}-{ends_at} {title}"


def _block_line(block: dict[str, Any]) -> str:
    return f"{_compact_datetime(str(block.get('starts_at', '')))}-{_compact_time(str(block.get('ends_at', '')))}"


def _compact_datetime(value: str) -> str:
    if "T" not in value:
        return value
    day, time_part = value.split("T", 1)
    return f"{day} {time_part[:5]}"


def _compact_time(value: str) -> str:
    if "T" in value:
        return value.split("T", 1)[1][:5]
    return value[:5]


def _weekend_dates(today: date, *, weeks_ahead: int) -> list[date]:
    days_until_saturday = (5 - today.weekday()) % 7
    saturday = today + timedelta(days=days_until_saturday + weeks_ahead * 7)
    return [saturday, saturday + timedelta(days=1)]


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _period_rain_probability(period: dict[str, Any]) -> int | None:
    value = period.get("max_precipitation_probability")
    if value is None:
        return None
    return int(value)


def _weather_period_line(period: dict[str, Any]) -> str:
    probability = period.get("max_precipitation_probability")
    probability_text = "未知" if probability is None else f"{probability}%"
    return (
        f"{_compact_datetime(str(period.get('starts_at', '')))}-"
        f"{_compact_time(str(period.get('ends_at', '')))} "
        f"{period.get('weather') or '未知'}，降水概率最高 {probability_text}"
    )


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
