from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

import tg_agent_bot.web.chat_service as chat_service
from tg_agent_bot.calendar.store import LOCAL_TZ, ParsedEvent, ScheduleStore
from tg_agent_bot.web.chat_service import WebChatService, _chat_id, _participant_chat_id


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=LOCAL_TZ)


def test_schedule_overview_returns_events_for_session(tmp_path) -> None:
    service = WebChatService.__new__(WebChatService)
    service.schedule = ScheduleStore(tmp_path / "schedule.sqlite3")

    session_id = "web-session"
    chat_id = _chat_id(session_id)
    service.schedule.add_event(
        chat_id,
        ParsedEvent(
            "demo",
            dt("2099-06-10T10:00:00"),
            dt("2099-06-10T11:30:00"),
        ),
    )

    overview = service._schedule_day(chat_id, dt("2099-06-10T00:00:00").date())

    assert overview["date"] == "2099-06-10"
    assert overview["events"][0]["title"] == "demo"
    assert overview["events"][0]["start_time"] == "10:00"
    assert overview["events"][0]["end_time"] == "11:30"
    assert overview["events"][0]["duration_minutes"] == 90


def test_schedule_overview_is_scoped_to_participant(tmp_path) -> None:
    service = WebChatService.__new__(WebChatService)
    service.schedule = ScheduleStore(tmp_path / "schedule.sqlite3")
    session_id = "web-session"
    today = datetime.now(LOCAL_TZ).date().isoformat()

    me_chat_id = _participant_chat_id(session_id, "ME")
    bot_chat_id = _participant_chat_id(session_id, "U1")
    service.schedule.add_event(
        me_chat_id,
        ParsedEvent("my event", dt(f"{today}T10:00:00"), dt(f"{today}T11:00:00")),
    )
    service.schedule.add_event(
        bot_chat_id,
        ParsedEvent("bot event", dt(f"{today}T12:00:00"), dt(f"{today}T13:00:00")),
    )

    me_overview = service.schedule_overview(session_id, days=1, owner_profile="ME")
    bot_overview = service.schedule_overview(session_id, days=1, owner_profile="U1")

    assert me_overview["owner_profile"] == "ME"
    assert bot_overview["owner_profile"] == "U1"
    assert me_overview["days"][0]["events"][0]["title"] == "my event"
    assert bot_overview["days"][0]["events"][0]["title"] == "bot event"


def test_bot_roster_marks_invited_bots_for_session() -> None:
    service = WebChatService.__new__(WebChatService)
    service.bot_catalog = [
        {
            "profile": "A",
            "username": "@CalendarBot",
            "display_name": "CalendarBot",
            "role": "calendar",
        }
    ]
    chat_id = _chat_id("web-session")
    service.invited_bots_by_chat = {chat_id: {"A"}}

    assert service.bot_roster("web-session") == {
        "type": "bot_roster",
        "bots": [
            {
                "profile": "A",
                "username": "@CalendarBot",
                "display_name": "CalendarBot",
                "role": "calendar",
                "invited": True,
            }
        ],
    }


def test_web_chat_invites_mentioned_bot_without_llm_turn() -> None:
    sent: list[dict] = []

    async def send(event: dict) -> None:
        sent.append(event)

    service = WebChatService.__new__(WebChatService)
    service.bot_catalog = [
        {
            "profile": "B",
            "username": "@WeatherBot",
            "display_name": "WeatherBot",
            "role": "weather",
        }
    ]
    service.invited_bots_by_chat = {}

    chat_id = _chat_id("web-session")
    reply = asyncio.run(service._reply(chat_id, "@WeatherBot", send))

    assert reply == ""
    assert service.invited_bots_by_chat[chat_id] == {"B"}
    assert sent[0]["type"] == "bot_invited"
    assert sent[0]["bot"]["username"] == "@WeatherBot"
    assert sent[1]["type"] == "bot_roster"
    assert sent[1]["bots"][0]["invited"] is True


def test_group_chat_ignores_messages_without_orchestrator_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []

    async def send(event: dict) -> None:
        sent.append(event)

    async def fail_parse_calendar_plan(extract_llm, user_text: str, *, context: list[dict]):
        raise AssertionError("planner should not be called")

    monkeypatch.setattr(chat_service, "parse_calendar_plan", fail_parse_calendar_plan)

    service = WebChatService.__new__(WebChatService)
    service.memory = SimpleNamespace(add=lambda *args: None)
    service.bot_catalog = []
    service.invited_bots_by_chat = {}

    asyncio.run(service.handle_text("web-session", "明天开会", send, conversation="group"))

    assert sent == []


def test_group_chat_accepts_orchestrator_role_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []
    calls: list[str] = []

    async def send(event: dict) -> None:
        sent.append(event)

    async def fake_parse_calendar_plan(extract_llm, user_text: str, *, context: list[dict]):
        calls.append(user_text)
        return {
            "ok": True,
            "actions": [{"action": "schedule_event", "title": "打球", "date": "2099-06-10", "duration_minutes": 60}],
        }

    monkeypatch.setattr(chat_service, "parse_calendar_plan", fake_parse_calendar_plan)
    monkeypatch.setattr(chat_service, "summarize_calendar_result", lambda result: "scheduled")

    service = WebChatService.__new__(WebChatService)
    service.extract_llm = object()
    service.memory = SimpleNamespace(add=lambda *args: None)
    service.context_by_chat = {}
    service.pending_slots = {}
    service.bot_catalog = [
        {
            "profile": "C",
            "username": "@MyRealOrchestratorNameBot",
            "display_name": "OrchestratorBot",
            "role": "orchestrator",
            "aliases": "myrealorchestratornamebot,orchestratorbot,orchestrator",
        }
    ]
    service.invited_bots_by_chat = {}
    service._calendar_result = lambda payload: {"kind": "calendar.result", "ok": True, "payload": payload}

    asyncio.run(
        service.handle_text(
            "web-session",
            "@OrchestratorBot 帮我明天找个时间打球",
            send,
            conversation="group",
        )
    )

    assert calls == ["帮我明天找个时间打球"]
    assert not any(event.get("type") == "bot_invite_failed" for event in sent)
    assert sent[-1] == {"type": "assistant_message", "text": "scheduled"}


def test_group_chat_pending_followup_does_not_require_orchestrator_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []
    calls: list[str] = []

    async def send(event: dict) -> None:
        sent.append(event)

    async def fake_parse_calendar_plan(extract_llm, user_text: str, *, context: list[dict]):
        calls.append(user_text)
        if "1小时" not in user_text:
            return {"ok": False, "ask_user": "请告诉我时长"}
        return {
            "ok": True,
            "actions": [{"action": "schedule_event", "title": "打球", "date": "2099-06-10", "duration_minutes": 60}],
        }

    monkeypatch.setattr(chat_service, "parse_calendar_plan", fake_parse_calendar_plan)
    monkeypatch.setattr(chat_service, "summarize_calendar_result", lambda result: "scheduled")

    service = WebChatService.__new__(WebChatService)
    service.extract_llm = object()
    service.memory = SimpleNamespace(add=lambda *args: None)
    service.context_by_chat = {}
    service.pending_slots = {}
    service.bot_catalog = [
        {
            "profile": "C",
            "username": "@RealC",
            "display_name": "OrchestratorBot",
            "role": "orchestrator",
            "aliases": "realc,orchestratorbot,orchestrator",
        }
    ]
    service.invited_bots_by_chat = {}
    service._calendar_result = lambda payload: {"kind": "calendar.result", "ok": True, "payload": payload}

    asyncio.run(service.handle_text("web-session", "@OrchestratorBot 帮我明天找个时间打球", send, conversation="group"))
    asyncio.run(service.handle_text("web-session", "1小时", send, conversation="group"))

    assert calls == [
        "帮我明天找个时间打球",
        "帮我明天找个时间打球\n用户补充信息：\n- 1小时",
    ]
    assert sent[-1] == {"type": "assistant_message", "text": "scheduled"}
    assert service.pending_slots == {}


def test_private_bot_chat_forwards_text_to_group_without_llm() -> None:
    sent: list[dict] = []

    async def send(event: dict) -> None:
        sent.append(event)

    service = WebChatService.__new__(WebChatService)
    service.bot_catalog = [
        {
            "profile": "U1",
            "username": "@AliceBot",
            "display_name": "Bot U1",
            "role": "bot",
        }
    ]
    service.invited_bots_by_chat = {}

    asyncio.run(
        service.handle_text(
            "web-session",
            "我周五下午有空",
            send,
            conversation="private",
            target_profile="U1",
        )
    )

    chat_id = _chat_id("web-session")
    assert service.invited_bots_by_chat[chat_id] == {"U1"}
    assert [event["type"] for event in sent] == [
        "bot_invited",
        "private_forwarded",
        "group_message",
    ]
    assert sent[2]["message"] == {
        "sender": "bot",
        "sender_profile": "U1",
        "sender_name": "Bot U1",
        "username": "@AliceBot",
        "text": "我周五下午有空",
    }


def test_private_bot_chat_can_trigger_orchestrator_from_forwarded_group_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []
    calls: list[str] = []

    async def send(event: dict) -> None:
        sent.append(event)

    async def fake_parse_calendar_plan(extract_llm, user_text: str, *, context: list[dict]):
        calls.append(user_text)
        return {
            "ok": True,
            "actions": [{"action": "events_on_day", "date": "2099-06-10"}],
        }

    monkeypatch.setattr(chat_service, "parse_calendar_plan", fake_parse_calendar_plan)
    monkeypatch.setattr(chat_service, "summarize_calendar_result", lambda result: "calendar summary")

    service = WebChatService.__new__(WebChatService)
    service.extract_llm = object()
    service.memory = SimpleNamespace(add=lambda *args: None)
    service.context_by_chat = {}
    service.pending_slots = {}
    service.bot_catalog = [
        {
            "profile": "C",
            "username": "@OrchestratorBot",
            "display_name": "OrchestratorBot",
            "role": "orchestrator",
        },
        {
            "profile": "U1",
            "username": "@AliceBot",
            "display_name": "Bot U1",
            "role": "bot",
        },
    ]
    service.invited_bots_by_chat = {}
    service._calendar_result = lambda payload: {"kind": "calendar.result", "ok": True, "payload": payload}

    asyncio.run(
        service.handle_text(
            "web-session",
            "@OrchestratorBot 明天开会",
            send,
            conversation="private",
            target_profile="U1",
        )
    )

    assert calls == ["明天开会"]
    assert any(event["type"] == "group_message" for event in sent)
    assert sent[-1] == {"type": "assistant_message", "text": "calendar summary"}


def test_private_bot_pending_followup_does_not_require_orchestrator_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []
    calls: list[str] = []

    async def send(event: dict) -> None:
        sent.append(event)

    async def fake_parse_calendar_plan(extract_llm, user_text: str, *, context: list[dict]):
        calls.append(user_text)
        if "1小时" not in user_text:
            return {"ok": False, "ask_user": "请告诉我时长"}
        return {
            "ok": True,
            "actions": [{"action": "schedule_event", "title": "打球", "date": "2099-06-10", "duration_minutes": 60}],
        }

    monkeypatch.setattr(chat_service, "parse_calendar_plan", fake_parse_calendar_plan)
    monkeypatch.setattr(chat_service, "summarize_calendar_result", lambda result: "scheduled")

    service = WebChatService.__new__(WebChatService)
    service.extract_llm = object()
    service.memory = SimpleNamespace(add=lambda *args: None)
    service.context_by_chat = {}
    service.pending_slots = {}
    service.bot_catalog = [
        {
            "profile": "C",
            "username": "@RealC",
            "display_name": "OrchestratorBot",
            "role": "orchestrator",
            "aliases": "realc,orchestratorbot,orchestrator",
        },
        {
            "profile": "U1",
            "username": "@AliceBot",
            "display_name": "Bot U1",
            "role": "bot",
        },
    ]
    service.invited_bots_by_chat = {}
    service._calendar_result = lambda payload: {"kind": "calendar.result", "ok": True, "payload": payload}

    asyncio.run(
        service.handle_text(
            "web-session",
            "@OrchestratorBot 帮我明天找个时间打球",
            send,
            conversation="private",
            target_profile="U1",
        )
    )
    asyncio.run(
        service.handle_text(
            "web-session",
            "1小时",
            send,
            conversation="private",
            target_profile="U1",
        )
    )

    assert calls == [
        "帮我明天找个时间打球",
        "帮我明天找个时间打球\n用户补充信息：\n- 1小时",
    ]
    assert sent[-1] == {"type": "assistant_message", "text": "scheduled"}
    assert service.pending_slots == {}


def test_group_context_lets_another_participant_copy_previous_event_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []
    calls: list[dict] = []

    async def send(event: dict) -> None:
        sent.append(event)

    async def fake_parse_calendar_plan(extract_llm, user_text: str, *, context: list[dict]):
        calls.append({"user_text": user_text, "context": context})
        if "我也" in user_text:
            group_events = [
                event
                for item in context
                if item.get("scope") == "group" and item.get("actor_profile") == "ME"
                for event in item.get("events", [])
            ]
            assert group_events[0]["starts_at"] == "2099-06-10T15:00:00+08:00"
            assert group_events[0]["ends_at"] == "2099-06-10T16:00:00+08:00"
            return {
                "ok": True,
                "actions": [
                    {
                        "action": "add_event",
                        "title": "打球",
                        "starts_at": group_events[0]["starts_at"],
                        "ends_at": group_events[0]["ends_at"],
                        "on_conflict": "reject",
                    }
                ],
            }
        return {
            "ok": True,
            "actions": [
                {
                    "action": "add_event",
                    "title": "打球",
                    "starts_at": "2099-06-10T15:00:00+08:00",
                    "ends_at": "2099-06-10T16:00:00+08:00",
                    "on_conflict": "reject",
                }
            ],
        }

    def fake_calendar_result(payload: dict) -> dict:
        return {
            "kind": "calendar.result",
            "action": payload["action"],
            "ok": True,
            "added": True,
            "event": {
                "id": 1,
                "title": payload["title"],
                "starts_at": payload["starts_at"],
                "ends_at": payload["ends_at"],
            },
        }

    monkeypatch.setattr(chat_service, "parse_calendar_plan", fake_parse_calendar_plan)
    monkeypatch.setattr(chat_service, "summarize_calendar_result", lambda result: "scheduled")

    service = WebChatService.__new__(WebChatService)
    service.extract_llm = object()
    service.memory = SimpleNamespace(add=lambda *args: None)
    service.context_by_chat = {}
    service.group_context_by_chat = {}
    service.pending_slots = {}
    service.bot_catalog = [
        {
            "profile": "C",
            "username": "@RealC",
            "display_name": "OrchestratorBot",
            "role": "orchestrator",
            "aliases": "realc,orchestratorbot,orchestrator",
        },
        {
            "profile": "U1",
            "username": "@AliceBot",
            "display_name": "Bot U1",
            "role": "bot",
        },
    ]
    service.invited_bots_by_chat = {}
    service._calendar_result = fake_calendar_result

    asyncio.run(
        service.handle_text(
            "web-session",
            "@OrchestratorBot 明天下午三点到四点打球",
            send,
            conversation="group",
        )
    )
    asyncio.run(
        service.handle_text(
            "web-session",
            "@OrchestratorBot 我也加同样时间的打球",
            send,
            conversation="private",
            target_profile="U1",
        )
    )

    assert len(calls) == 2
    assert calls[1]["user_text"] == "我也加同样时间的打球"
    group_context = service.group_context_by_chat[_chat_id("web-session")]
    assert group_context[0]["actor_profile"] == "ME"
    assert group_context[1]["actor_profile"] == "U1"


def test_web_chat_strips_invited_bot_mentions_before_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    sent: list[dict] = []

    async def send(event: dict) -> None:
        sent.append(event)

    async def fake_parse_calendar_plan(extract_llm, user_text: str, *, context: list[dict]):
        calls.append(user_text)
        return {
            "ok": True,
            "actions": [{"action": "events_on_day", "date": "2099-06-10"}],
        }

    monkeypatch.setattr(chat_service, "parse_calendar_plan", fake_parse_calendar_plan)
    monkeypatch.setattr(chat_service, "summarize_calendar_result", lambda result: "calendar summary")

    service = WebChatService.__new__(WebChatService)
    service.extract_llm = object()
    service.context_by_chat = {}
    service.pending_slots = {}
    service.bot_catalog = [
        {
            "profile": "A",
            "username": "@CalendarBot",
            "display_name": "CalendarBot",
            "role": "calendar",
        }
    ]
    service.invited_bots_by_chat = {}
    service._calendar_result = lambda payload: {"kind": "calendar.result", "ok": True, "payload": payload}

    chat_id = _chat_id("web-session")
    reply = asyncio.run(service._reply(chat_id, "@CalendarBot 明天有什么安排", send))

    assert reply == "calendar summary"
    assert calls == ["明天有什么安排"]
    assert service.invited_bots_by_chat[chat_id] == {"A"}


def test_web_chat_reuses_pending_calendar_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sent: list[dict] = []

    async def send(event: dict) -> None:
        sent.append(event)

    async def fake_parse_calendar_plan(extract_llm, user_text: str, *, context: list[dict]):
        calls.append(user_text)
        if "用户补充信息" not in user_text:
            return {"ok": False, "ask_user": "How long should it be?"}
        return {
            "ok": True,
            "actions": [
                {
                    "action": "schedule_event",
                    "title": "team meeting",
                    "date": "2099-06-10",
                    "duration_minutes": 60,
                }
            ],
        }

    monkeypatch.setattr(chat_service, "parse_calendar_plan", fake_parse_calendar_plan)
    monkeypatch.setattr(chat_service, "summarize_calendar_result", lambda result: "scheduled summary")

    service = WebChatService.__new__(WebChatService)
    service.extract_llm = object()
    service.llm = object()
    service.history_turns = 3
    service.context_by_chat = {}
    service.pending_slots = {}
    service._calendar_result = lambda payload: {"kind": "calendar.result", "ok": True, "payload": payload}

    chat_id = _chat_id("web-session")
    first = asyncio.run(service._reply(chat_id, "Find time for a team meeting tomorrow", send))
    second = asyncio.run(service._reply(chat_id, "one hour", send))

    assert first == "How long should it be?"
    assert second == "scheduled summary"
    assert calls == [
        "Find time for a team meeting tomorrow",
        "Find time for a team meeting tomorrow\n用户补充信息：\n- one hour",
    ]
    assert service.pending_slots == {}
    assert service.context_by_chat[chat_id][0]["actions"][0]["title"] == "team meeting"


def test_web_chat_accumulates_multiple_calendar_followups(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sent: list[dict] = []

    async def send(event: dict) -> None:
        sent.append(event)

    async def fake_parse_calendar_plan(extract_llm, user_text: str, *, context: list[dict]):
        calls.append(user_text)
        if "tomorrow" not in user_text:
            return {"ok": False, "ask_user": "Which day?"}
        if "45 minutes" not in user_text:
            return {"ok": False, "ask_user": "How long?"}
        return {
            "ok": True,
            "actions": [
                {
                    "action": "schedule_event",
                    "title": "review",
                    "date": "2099-06-10",
                    "duration_minutes": 45,
                }
            ],
        }

    monkeypatch.setattr(chat_service, "parse_calendar_plan", fake_parse_calendar_plan)
    monkeypatch.setattr(chat_service, "summarize_calendar_result", lambda result: "scheduled summary")

    service = WebChatService.__new__(WebChatService)
    service.extract_llm = object()
    service.llm = object()
    service.history_turns = 3
    service.context_by_chat = {}
    service.pending_slots = {}
    service._calendar_result = lambda payload: {"kind": "calendar.result", "ok": True, "payload": payload}

    chat_id = _chat_id("web-session")
    first = asyncio.run(service._reply(chat_id, "Schedule a review", send))
    second = asyncio.run(service._reply(chat_id, "tomorrow", send))
    third = asyncio.run(service._reply(chat_id, "45 minutes", send))

    assert first == "Which day?"
    assert second == "How long?"
    assert third == "scheduled summary"
    assert calls == [
        "Schedule a review",
        "Schedule a review\n用户补充信息：\n- tomorrow",
        "Schedule a review\n用户补充信息：\n- tomorrow\n- 45 minutes",
    ]
    assert service.pending_slots == {}
    assert service.context_by_chat[chat_id][0]["actions"][0]["duration_minutes"] == 45


def test_web_chat_accumulates_multiple_weather_followups(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sent: list[dict] = []

    async def send(event: dict) -> None:
        sent.append(event)

    async def fake_parse_weather_plan(extract_llm, user_text: str):
        calls.append(user_text)
        if "上海" not in user_text:
            return {"ok": False, "ask_user": "请告诉我城市"}
        if "后天" not in user_text:
            return {"ok": False, "ask_user": "请告诉我日期"}
        return {
            "ok": True,
            "goal": "avoid_rain",
            "schedule_requested": False,
            "actions": [
                {
                    "action": "hourly_forecast",
                    "location": "上海",
                    "date": "2099-06-10",
                }
            ],
        }

    monkeypatch.setattr(chat_service, "parse_weather_plan", fake_parse_weather_plan)
    monkeypatch.setattr(chat_service, "summarize_weather_results", lambda results, goal: "weather summary")

    async def fake_weather_result(payload: dict) -> dict:
        return {"kind": "weather.result", "ok": True, "date": payload["date"]}

    service = WebChatService.__new__(WebChatService)
    service.extract_llm = object()
    service.pending_slots = {}
    service._weather_result = fake_weather_result

    chat_id = _chat_id("web-session")
    first = asyncio.run(service._reply(chat_id, "找个不下雨的时间打球", send))
    second = asyncio.run(service._reply(chat_id, "上海", send))
    third = asyncio.run(service._reply(chat_id, "后天", send))

    assert first == "请告诉我城市"
    assert second == "请告诉我日期"
    assert third == "weather summary"
    assert calls == [
        "找个不下雨的时间打球",
        "找个不下雨的时间打球\n用户补充信息：\n- 上海",
        "找个不下雨的时间打球\n用户补充信息：\n- 上海\n- 后天",
    ]
    assert service.pending_slots == {}
