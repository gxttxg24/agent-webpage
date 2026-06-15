from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any

from ..calendar.service import CalendarServiceError, handle_calendar_request
from ..calendar.serializers import event_to_dict
from ..calendar.store import LOCAL_TZ, ScheduleStore
from ..config import load_settings
from ..llm import LLMClient, build_llm_client
from ..memory import MemoryStore
from ..orchestrator.followup import append_pending_followup, make_pending_slot
from ..orchestrator.planner import (
    calendar_context_from_result,
    parse_calendar_plan,
    parse_weather_plan,
    summarize_calendar_result,
    summarize_weather_results,
)
from ..slot_matcher.service import SlotMatcherServiceError, handle_slot_matcher_request
from ..weather.service import WeatherServiceError, handle_weather_request
from .bot_roster import (
    build_bot_catalog,
    bot_mention_keys,
    find_bot_by_mention,
    find_bot_by_profile,
    mentions,
    mentions_orchestrator,
    roster_event,
    strip_matched_mentions,
)
from .session_state import (
    WebSessionState,
    chat_id as _chat_id,
    combined_context,
    participant_chat_id as _participant_chat_id,
)


EventSender = Callable[[dict[str, Any]], Awaitable[None]]


class WebChatService:
    def __init__(self, profile: str | None = None) -> None:
        settings = load_settings(profile)
        self.memory = MemoryStore(settings.memory_db)
        self.schedule = ScheduleStore(settings.schedule_db)
        self.llm = build_llm_client(settings.codex_base_url, settings.codex_api_key, settings.codex_model)
        self.extract_llm = build_llm_client(
            settings.codex_base_url,
            settings.codex_api_key,
            settings.codex_extract_model,
        )
        self.history_turns = settings.history_turns
        self.state = WebSessionState()
        self.context_by_chat = self.state.context_by_chat
        self.group_context_by_chat = self.state.group_context_by_chat
        self.pending_slots = self.state.pending_slots
        self.invited_bots_by_chat = self.state.invited_bots_by_chat
        self.bot_catalog = build_bot_catalog(settings)

    async def handle_text(
        self,
        session_id: str,
        text: str,
        send: EventSender,
        *,
        conversation: str = "group",
        target_profile: str | None = None,
    ) -> None:
        user_text = text.strip()
        if not user_text:
            return

        group_chat_id = _chat_id(session_id)
        if conversation == "private":
            await self._handle_private_bot_text(session_id, group_chat_id, target_profile, user_text, send)
            return

        await self._handle_group_text(session_id, group_chat_id, user_text, send)

    async def _handle_group_text(
        self,
        session_id: str,
        group_chat_id: int,
        user_text: str,
        send: EventSender,
    ) -> None:
        orchestrator_mentioned = mentions_orchestrator(_bot_catalog_for_service(self), user_text)
        owner_chat_id = _participant_chat_id(session_id, "ME")
        has_pending = owner_chat_id in _pending_slots_for_service(self)
        stripped_text = await self._handle_bot_mentions(group_chat_id, user_text, send)
        if not (orchestrator_mentioned or has_pending) or not stripped_text:
            return

        await send({"type": "typing", "active": True})
        try:
            reply = await self._reply(
                owner_chat_id,
                stripped_text,
                send,
                group_chat_id=group_chat_id,
                actor_profile="ME",
                actor_name="Me",
            )
        finally:
            await send({"type": "typing", "active": False})

        self.memory.add(group_chat_id, "user", user_text)
        if reply:
            self.memory.add(group_chat_id, "assistant", reply)
            await send({"type": "assistant_message", "text": reply})

    async def _handle_private_bot_text(
        self,
        session_id: str,
        group_chat_id: int,
        target_profile: str | None,
        user_text: str,
        send: EventSender,
    ) -> None:
        bot = find_bot_by_profile(_bot_catalog_for_service(self), target_profile or "")
        if bot is None:
            await send(
                {
                    "type": "private_message_failed",
                    "reason": "unknown_bot",
                    "target_profile": target_profile or "",
                }
            )
            return

        await self._invite_bot_to_group(group_chat_id, bot, send)
        await send(
            {
                "type": "private_forwarded",
                "bot": {**bot, "invited": True},
                "text": user_text,
            }
        )
        await send(
            {
                "type": "group_message",
                "message": {
                    "sender": "bot",
                    "sender_profile": bot["profile"],
                    "sender_name": bot["display_name"],
                    "username": bot["username"],
                    "text": user_text,
                },
            }
        )

        owner_chat_id = _participant_chat_id(session_id, bot["profile"])
        if mentions_orchestrator(_bot_catalog_for_service(self), user_text) or owner_chat_id in _pending_slots_for_service(self):
            stripped_text = await self._handle_bot_mentions(group_chat_id, user_text, send)
            if not stripped_text:
                return
            await send({"type": "typing", "active": True})
            try:
                reply = await self._reply(
                    owner_chat_id,
                    stripped_text,
                    send,
                    group_chat_id=group_chat_id,
                    actor_profile=bot["profile"],
                    actor_name=bot["display_name"],
                )
            finally:
                await send({"type": "typing", "active": False})
            if reply:
                self.memory.add(group_chat_id, "assistant", reply)
                await send({"type": "assistant_message", "text": reply})

    def reset(self, session_id: str) -> None:
        chat_id = _chat_id(session_id)
        self.memory.clear(chat_id)
        _state_for_service(self).clear_chat(chat_id)

    def bot_roster(self, session_id: str) -> dict[str, Any]:
        chat_id = _chat_id(session_id)
        return roster_event(_bot_catalog_for_service(self), _state_for_service(self).invited_profiles(chat_id))

    def schedule_overview(
        self,
        session_id: str,
        *,
        days: int = 7,
        owner_profile: str = "ME",
    ) -> dict[str, Any]:
        chat_id = _participant_chat_id(session_id, owner_profile)
        today = datetime.now(LOCAL_TZ).date()
        day_count = max(1, min(days, 14))
        return {
            "type": "schedule_overview",
            "owner_profile": owner_profile,
            "start_date": today.isoformat(),
            "days": [
                self._schedule_day(chat_id, today + timedelta(days=offset))
                for offset in range(day_count)
            ],
        }

    def _schedule_day(self, chat_id: int, target_day: date) -> dict[str, Any]:
        events = self.schedule.events_on_day(chat_id, target_day)
        return {
            "date": target_day.isoformat(),
            "weekday": target_day.strftime("%a"),
            "events": [
                event_to_dict(event, include_chat_id=False, include_time_labels=True)
                for event in events
            ],
        }

    async def _reply(
        self,
        chat_id: int,
        user_text: str,
        send: EventSender,
        *,
        group_chat_id: int | None = None,
        actor_profile: str | None = None,
        actor_name: str | None = None,
    ) -> str:
        user_text = await self._handle_bot_mentions(chat_id, user_text, send)
        if not user_text:
            return ""

        pending = _pending_slots_for_service(self).get(chat_id)
        if pending and pending.get("service") == "weather":
            combined_text = append_pending_followup(pending, user_text)
            return await self._handle_weather(
                chat_id,
                combined_text,
                send,
                original_text=str(pending["original_text"]),
                group_chat_id=group_chat_id,
                actor_profile=actor_profile,
                actor_name=actor_name,
            )

        if pending and pending.get("service") == "calendar":
            combined_text = append_pending_followup(pending, user_text)
            return await self._handle_calendar_or_chat(
                chat_id,
                combined_text,
                send,
                original_text=str(pending["original_text"]),
                group_chat_id=group_chat_id,
                actor_profile=actor_profile,
                actor_name=actor_name,
            )

        if _looks_like_weather(user_text):
            return await self._handle_weather(
                chat_id,
                user_text,
                send,
                group_chat_id=group_chat_id,
                actor_profile=actor_profile,
                actor_name=actor_name,
            )

        return await self._handle_calendar_or_chat(
            chat_id,
            user_text,
            send,
            group_chat_id=group_chat_id,
            actor_profile=actor_profile,
            actor_name=actor_name,
        )

    async def _handle_bot_mentions(
        self,
        chat_id: int,
        user_text: str,
        send: EventSender,
    ) -> str:
        mentioned = mentions(user_text)
        if not mentioned:
            return user_text

        matched_mentions: set[str] = set()
        for mention in mentioned:
            bot = find_bot_by_mention(_bot_catalog_for_service(self), mention)
            if bot is None:
                await send({"type": "bot_invite_failed", "username": mention, "reason": "unknown_bot"})
                continue
            matched_mentions.update(bot_mention_keys(bot))
            await self._invite_bot_to_group(chat_id, bot, send)

        if matched_mentions:
            await send(self._bot_roster_for_chat(chat_id))
            return strip_matched_mentions(user_text, matched_mentions)
        return user_text

    async def _invite_bot_to_group(
        self,
        chat_id: int,
        bot: dict[str, str],
        send: EventSender,
    ) -> None:
        invited = _state_for_service(self).invited_profiles(chat_id)
        already_invited = bot["profile"] in invited
        invited.add(bot["profile"])
        await send(
            {
                "type": "bot_invited",
                "bot": {**bot, "invited": True},
                "already_invited": already_invited,
            }
        )

    def _bot_roster_for_chat(self, chat_id: int) -> dict[str, Any]:
        return roster_event(_bot_catalog_for_service(self), _state_for_service(self).invited_profiles(chat_id))

    async def _handle_calendar_or_chat(
        self,
        chat_id: int,
        user_text: str,
        send: EventSender,
        *,
        original_text: str | None = None,
        group_chat_id: int | None = None,
        actor_profile: str | None = None,
        actor_name: str | None = None,
    ) -> str:
        state = _state_for_service(self)
        recent_context = state.personal_context(chat_id)
        group_context = (
            state.group_context_by_chat.get(group_chat_id, [])
            if group_chat_id is not None
            else []
        )
        try:
            await send({"type": "workflow_status", "label": "Parsing calendar request"})
            plan = await parse_calendar_plan(
                self.extract_llm,
                user_text,
                context=combined_context(recent_context, group_context),
            )
        except Exception:
            history = self.memory.recent(chat_id, limit=self.history_turns * 2)
            reply = await self.llm.reply(history=history, user_text=user_text)
            return reply

        if plan.get("ok") is not True:
            ask_user = str(plan.get("ask_user") or plan.get("error") or "Please add more calendar details.")
            if chat_id in state.pending_slots:
                state.pending_slots[chat_id]["ask_user"] = ask_user
            else:
                state.pending_slots[chat_id] = make_pending_slot(
                    "calendar",
                    original_text or user_text,
                    ask_user,
                )
            return ask_user

        state.pending_slots.pop(chat_id, None)

        results: list[dict[str, Any]] = []
        for action in plan["actions"]:
            payload = dict(action)
            payload["service"] = "calendar"
            payload["owner_chat_id"] = chat_id
            await send({"type": "workflow_status", "label": f"Running calendar action: {payload['action']}"})
            results.append(self._calendar_result(payload))

        context_entry = calendar_context_from_result(user_text, plan["actions"], results)
        recent_context.append(context_entry)
        del recent_context[:-8]
        if group_chat_id is not None:
            self._remember_group_calendar_context(
                group_chat_id,
                context_entry,
                actor_profile=actor_profile or "",
                actor_name=actor_name or "",
            )

        lines = [summarize_calendar_result(result) for result in results]
        return "\n\n".join(lines)

    async def _handle_weather(
        self,
        chat_id: int,
        user_text: str,
        send: EventSender,
        *,
        original_text: str | None = None,
        group_chat_id: int | None = None,
        actor_profile: str | None = None,
        actor_name: str | None = None,
    ) -> str:
        try:
            await send({"type": "workflow_status", "label": "Parsing weather request"})
            plan = await parse_weather_plan(self.extract_llm, user_text)
        except Exception as exc:
            return f"I could not parse this weather request: {type(exc).__name__}: {exc}"

        if plan.get("ok") is not True:
            ask_user = str(plan.get("ask_user") or plan.get("error") or "Please tell me the location and date.")
            state = _state_for_service(self)
            if chat_id in state.pending_slots:
                state.pending_slots[chat_id]["ask_user"] = ask_user
            else:
                state.pending_slots[chat_id] = make_pending_slot(
                    "weather",
                    original_text or user_text,
                    ask_user,
                )
            return ask_user

        state = _state_for_service(self)
        state.pending_slots.pop(chat_id, None)
        weather_results: list[dict[str, Any]] = []
        for action in plan["actions"]:
            payload = dict(action)
            payload["service"] = "weather"
            await send({"type": "workflow_status", "label": f"Fetching weather: {payload.get('date', '')}"})
            weather_results.append(await self._weather_result(payload))

        if not plan.get("schedule_requested"):
            return summarize_weather_results(weather_results, goal=str(plan.get("goal", "forecast")))

        await send({"type": "workflow_status", "label": "Checking free calendar time"})
        calendar_results = [
            self._calendar_result(
                {
                    "service": "calendar",
                    "action": "free_time",
                    "owner_chat_id": chat_id,
                    "date": result.get("date"),
                    "min_duration_minutes": int(plan.get("duration_minutes") or 60),
                }
            )
            for result in weather_results
            if result.get("ok") is True and result.get("date")
        ]

        matcher_payload = _slot_matcher_payload(plan, weather_results, calendar_results)
        if matcher_payload is None:
            return "Weather and calendar data were found, but there were no matching weather periods or free blocks."

        await send({"type": "workflow_status", "label": "Matching weather and free time"})
        matcher_result = self._slot_result(matcher_payload)
        matches = matcher_result.get("matches") or []
        if not matches:
            return "I could not find a suitable time after combining weather and your free blocks."

        match = matches[0]
        title = str(plan.get("activity_title") or "Weather-aware activity")
        await send({"type": "workflow_status", "label": "Writing calendar event"})
        add_action = {
            "action": "add_event",
            "title": title,
            "starts_at": match["starts_at"],
            "ends_at": match["ends_at"],
            "on_conflict": "reject",
        }
        add_result = self._calendar_result(
            {
                "service": "calendar",
                "owner_chat_id": chat_id,
                **add_action,
            }
        )
        recent_context = _state_for_service(self).personal_context(chat_id)
        context_entry = calendar_context_from_result(user_text, [add_action], [add_result])
        recent_context.append(context_entry)
        del recent_context[:-8]
        if group_chat_id is not None:
            self._remember_group_calendar_context(
                group_chat_id,
                context_entry,
                actor_profile=actor_profile or "",
                actor_name=actor_name or "",
            )

        probability = match.get("max_precipitation_probability")
        probability_text = "unknown" if probability is None else f"{probability}%"
        return (
            f"Scheduled {title}:\n"
            f"{summarize_calendar_result(add_result)}\n"
            f"Match basis: {match.get('weather') or 'unknown weather'}, max precipitation probability {probability_text}."
        )

    def _remember_group_calendar_context(
        self,
        group_chat_id: int,
        context_entry: dict[str, Any],
        *,
        actor_profile: str,
        actor_name: str,
    ) -> None:
        group_context = _state_for_service(self).group_context(group_chat_id)
        enriched = {
            **context_entry,
            "actor_profile": actor_profile or "UNKNOWN",
            "actor_name": actor_name or actor_profile or "Unknown",
        }
        group_context.append(enriched)
        del group_context[:-12]

    def _calendar_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return handle_calendar_request(self.schedule, payload)
        except CalendarServiceError as exc:
            return _error("calendar.result", payload, str(exc))
        except Exception as exc:
            return _error("calendar.result", payload, f"{type(exc).__name__}: {exc}")

    async def _weather_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await handle_weather_request(payload)
        except WeatherServiceError as exc:
            return _error("weather.result", payload, str(exc))
        except Exception as exc:
            return _error("weather.result", payload, f"{type(exc).__name__}: {exc}")

    def _slot_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return handle_slot_matcher_request(payload)
        except SlotMatcherServiceError as exc:
            return _error("slot_matcher.result", payload, str(exc))
        except Exception as exc:
            return _error("slot_matcher.result", payload, f"{type(exc).__name__}: {exc}")


def _bot_catalog_for_service(service: WebChatService) -> list[dict[str, str]]:
    return list(getattr(service, "bot_catalog", []))


def _state_for_service(service: WebChatService) -> WebSessionState:
    state = getattr(service, "state", None)
    if state is None:
        state = WebSessionState(
            context_by_chat=getattr(service, "context_by_chat", {}),
            group_context_by_chat=getattr(service, "group_context_by_chat", {}),
            pending_slots=getattr(service, "pending_slots", {}),
            invited_bots_by_chat=getattr(service, "invited_bots_by_chat", {}),
        )
        service.state = state

    service.context_by_chat = state.context_by_chat
    service.group_context_by_chat = state.group_context_by_chat
    service.pending_slots = state.pending_slots
    service.invited_bots_by_chat = state.invited_bots_by_chat
    return state


def _pending_slots_for_service(service: WebChatService) -> dict[int, dict[str, Any]]:
    return _state_for_service(service).pending_slots

def _looks_like_weather(text: str) -> bool:
    return bool(re.search(r"(天气|下雨|降水|雨|晴|阴天|多云|weather|rain)", text, re.IGNORECASE))


def _slot_matcher_payload(
    plan: dict[str, Any],
    weather_results: list[dict[str, Any]],
    calendar_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    weather_periods = [
        period
        for result in weather_results
        for period in (result.get("periods") or [])
        if isinstance(period, dict)
    ]
    calendar_blocks = [
        block
        for result in calendar_results
        for block in (result.get("blocks") or [])
        if isinstance(block, dict)
    ]
    if not weather_periods or not calendar_blocks:
        return None
    return {
        "service": "slot_matcher",
        "action": "match_slots",
        "goal": str(plan.get("goal", "avoid_rain")),
        "duration_minutes": int(plan.get("duration_minutes") or 60),
        "rain_threshold": 30,
        "weather_periods": weather_periods,
        "calendar_blocks": calendar_blocks,
    }


def _error(kind: str, payload: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "service": str(payload.get("service", "")),
        "action": str(payload.get("action", "")),
        "ok": False,
        "error": message,
    }
