from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from ..calendar.store import LOCAL_TZ
from ..llm import LLMClient
from .prompts import ORCHESTRATOR_SYSTEM_PROMPT, WEATHER_SYSTEM_PROMPT
from .summaries import calendar_context_from_result, summarize_calendar_result, summarize_weather_results
from .validation import _validate_plan, _validate_weather_plan

async def parse_calendar_plan(
    llm: LLMClient,
    user_text: str,
    *,
    context: list[dict[str, Any]],
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    now = datetime.now(LOCAL_TZ)
    user_prompt = {
        "json_request": "Return a JSON object only.",
        "now": now.isoformat(),
        "today": now.date().isoformat(),
        "tomorrow": (now.date() + timedelta(days=1)).isoformat(),
        "after_tomorrow": (now.date() + timedelta(days=2)).isoformat(),
        "three_days_later": (now.date() + timedelta(days=3)).isoformat(),
        "timezone": "Asia/Shanghai UTC+08:00",
        "recent_calendar_context": context[-6:],
        "user_text": user_text,
    }
    data = await llm.json_reply(
        ORCHESTRATOR_SYSTEM_PROMPT,
        json.dumps(user_prompt, ensure_ascii=False),
        timeout_seconds=timeout_seconds,
    )
    return _validate_plan(data)


async def parse_weather_plan(
    llm: LLMClient,
    user_text: str,
    *,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    now = datetime.now(LOCAL_TZ)
    user_prompt = {
        "json_request": "Return a JSON object only.",
        "now": now.isoformat(),
        "today": now.date().isoformat(),
        "tomorrow": (now.date() + timedelta(days=1)).isoformat(),
        "after_tomorrow": (now.date() + timedelta(days=2)).isoformat(),
        "three_days_later": (now.date() + timedelta(days=3)).isoformat(),
        "this_weekend_dates": [item.isoformat() for item in _weekend_dates(now.date(), weeks_ahead=0)],
        "next_weekend_dates": [item.isoformat() for item in _weekend_dates(now.date(), weeks_ahead=1)],
        "timezone": "Asia/Shanghai UTC+08:00",
        "user_text": user_text,
    }
    data = await llm.json_reply(
        WEATHER_SYSTEM_PROMPT,
        json.dumps(user_prompt, ensure_ascii=False),
        timeout_seconds=timeout_seconds,
    )
    return _validate_weather_plan(data)
