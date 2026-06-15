from __future__ import annotations

from datetime import date
from typing import Any

def _validate_plan(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("ok") is not True:
        return {
            "ok": False,
            "error": str(data.get("error") or "我还不能确定你的日程意图。"),
            "ask_user": str(data.get("ask_user") or ""),
        }
    actions = data.get("actions")
    if not isinstance(actions, list) or not actions:
        return {"ok": False, "error": "没有解析出可执行的日程动作。", "ask_user": ""}
    normalized_actions = []
    for item in actions[:3]:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).strip().lower()
        if action not in _allowed_actions():
            continue
        normalized = dict(item)
        normalized["action"] = action
        normalized_actions.append(normalized)
    if not normalized_actions:
        return {"ok": False, "error": "没有解析出受支持的日程动作。", "ask_user": ""}
    return {
        "ok": True,
        "intent": "calendar",
        "summary": str(data.get("summary", "正在处理日程。")),
        "actions": normalized_actions,
    }


def _validate_weather_plan(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("ok") is not True:
        return {
            "ok": False,
            "error": str(data.get("error") or "我还不能确定天气查询信息。"),
            "ask_user": str(data.get("ask_user") or ""),
        }
    actions = data.get("actions")
    if not isinstance(actions, list) or not actions:
        return {"ok": False, "error": "没有解析出可执行的天气查询。", "ask_user": ""}
    normalized_actions = []
    for item in actions[:4]:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "hourly_forecast")).strip().lower()
        if action not in {"hourly_forecast", "forecast"}:
            continue
        location = str(item.get("location") or data.get("location") or "").strip()
        date_value = str(item.get("date") or "").strip()
        if not location or not _is_iso_date(date_value):
            continue
        normalized = dict(item)
        normalized["action"] = action
        normalized["location"] = location
        normalized.setdefault("country_code", "CN")
        normalized.setdefault("timezone", "Asia/Shanghai")
        normalized.setdefault("interval_hours", 3)
        normalized_actions.append(normalized)
    if not normalized_actions:
        return {"ok": False, "error": "天气查询缺少地点或日期。", "ask_user": "请告诉我地点和日期，比如：上海这周末。"}
    return {
        "ok": True,
        "intent": "weather",
        "summary": str(data.get("summary", "我先查询天气。")),
        "goal": str(data.get("goal", "forecast")),
        "schedule_requested": bool(data.get("schedule_requested", False)),
        "activity_title": str(data.get("activity_title") or "天气相关安排"),
        "duration_minutes": _positive_int(data.get("duration_minutes"), default=60),
        "location": str(data.get("location") or normalized_actions[0]["location"]),
        "actions": normalized_actions,
    }


def _allowed_actions() -> set[str]:
    return {
        "list_events",
        "events_on_day",
        "free_time",
        "add_event",
        "schedule_event",
        "delete_event",
        "set_preference",
        "get_preference",
        "move_event",
        "reschedule_event",
    }
