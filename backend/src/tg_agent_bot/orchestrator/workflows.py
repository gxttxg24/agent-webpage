
from __future__ import annotations

import logging
import re

from telegram.constants import ChatAction
from telegram.ext import ContextTypes
from telegram import Update

from ..b2b.protocol import make_payload_request
from ..llm import LLMClient
from ..telegram.utils import own_username, remember_b2b_event, resolve_b2b_target
from .followup import append_pending_followup, make_pending_slot
from .planner import (
    calendar_context_from_result,
    parse_calendar_plan,
    parse_weather_plan,
    summarize_calendar_result,
    summarize_weather_results,
)


logger = logging.getLogger(__name__)

async def handle_orchestrator_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_text: str,
) -> bool:
    if update.effective_chat is None or update.effective_message is None:
        return False

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    extract_llm: LLMClient = context.application.bot_data["extract_llm"]
    context_by_chat: dict[int, list[dict]] = context.application.bot_data.setdefault(
        "orchestrator_context_by_chat",
        {},
    )
    chat_id = update.effective_chat.id
    recent_context = context_by_chat.setdefault(chat_id, [])
    pending_slots: dict[int, dict] = context.application.bot_data.setdefault(
        "orchestrator_pending_slots",
        {},
    )
    pending = pending_slots.get(chat_id)

    if pending and pending.get("service") == "weather":
        combined_text = append_pending_followup(pending, user_text)
        try:
            plan = await parse_weather_plan(extract_llm, combined_text)
        except Exception:
            logger.exception("Orchestrator pending weather planning failed")
            await update.effective_message.reply_text(
                "我还是没能补全这次天气查询。请直接说完整一点，比如：上海这周末找不下雨的时间。"
            )
            return True

        if plan.get("ok") is True:
            pending_slots.pop(chat_id, None)
            await start_orchestrator_weather_workflow(
                update,
                context,
                user_text=str(pending.get("original_text", user_text)),
                plan=plan,
            )
            return True

        ask_user = str(plan.get("ask_user") or plan.get("error") or "还缺少地点或日期。")
        pending["ask_user"] = ask_user
        await update.effective_message.reply_text(ask_user)
        return True

    if pending and pending.get("service") == "calendar":
        combined_text = append_pending_followup(pending, user_text)
        try:
            plan = await parse_calendar_plan(
                extract_llm,
                combined_text,
                context=recent_context,
            )
        except Exception:
            logger.exception("Orchestrator pending calendar planning failed")
            await update.effective_message.reply_text(
                "我还是没能补全这次日程请求。请直接说完整一点，比如：明天两点到三点组会。"
            )
            return True

        if plan.get("ok") is True:
            pending_slots.pop(chat_id, None)
            await start_orchestrator_calendar_workflow(
                update,
                context,
                user_text=str(pending.get("original_text", user_text)),
                plan=plan,
            )
            return True

        ask_user = str(plan.get("ask_user") or plan.get("error") or "请补充一下日程信息。")
        pending["ask_user"] = ask_user
        await update.effective_message.reply_text(ask_user)
        return True

    if looks_like_weather_request(user_text):
        try:
            plan = await parse_weather_plan(extract_llm, user_text)
        except Exception:
            logger.exception("Orchestrator weather planning failed")
            await update.effective_message.reply_text(
                "我还没能把这句话稳定解析成天气查询。请说明地点和日期，比如：上海这周末会不会下雨。"
            )
            return True

        if plan.get("ok") is not True:
            ask_user = str(plan.get("ask_user") or plan.get("error") or "请告诉我地点和日期。")
            pending_slots[chat_id] = make_pending_slot("weather", user_text, ask_user)
            await update.effective_message.reply_text(ask_user)
            return True

        await start_orchestrator_weather_workflow(
            update,
            context,
            user_text=user_text,
            plan=plan,
        )
        return True

    try:
        plan = await parse_calendar_plan(
            extract_llm,
            user_text,
            context=recent_context,
        )
    except Exception as exc:
        logger.exception("Orchestrator calendar planning failed")
        await update.effective_message.reply_text(
            "我还没能把这句话稳定解析成日程操作。请换一种更明确的说法，比如：明天两点到三点组会。"
        )
        return True

    if plan.get("ok") is not True:
        ask_user = str(plan.get("ask_user") or plan.get("error") or "请补充一下日程信息。")
        pending_slots[chat_id] = make_pending_slot("calendar", user_text, ask_user)
        await update.effective_message.reply_text(ask_user)
        return True

    await start_orchestrator_calendar_workflow(
        update,
        context,
        user_text=user_text,
        plan=plan,
    )
    return True


async def start_orchestrator_calendar_workflow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_text: str,
    plan: dict,
) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    chat_id = update.effective_chat.id
    actions = plan["actions"]
    workflow = {
        "user_chat_id": chat_id,
        "user_text": user_text,
        "actions": actions,
        "index": 0,
        "results": [],
    }

    try:
        await send_orchestrator_calendar_action(context, workflow)
    except Exception as exc:
        logger.exception("Failed to send orchestrator calendar action")
        await update.effective_message.reply_text(f"我解析到了日程操作，但发送给 CalendarBot 失败：{exc}")
        return

    await update.effective_message.reply_text(str(plan.get("summary") or "收到，我正在处理日程。"))


async def start_orchestrator_weather_workflow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_text: str,
    plan: dict,
) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    workflow = {
        "service": "weather_schedule" if plan.get("schedule_requested") else "weather",
        "stage": "weather",
        "user_chat_id": update.effective_chat.id,
        "user_text": user_text,
        "goal": str(plan.get("goal", "forecast")),
        "activity_title": str(plan.get("activity_title") or "天气相关安排"),
        "duration_minutes": int(plan.get("duration_minutes") or 60),
        "rain_threshold": 30,
        "actions": plan["actions"],
        "index": 0,
        "results": [],
        "weather_results": [],
        "calendar_results": [],
    }
    try:
        await send_orchestrator_weather_action(context, workflow)
    except Exception as exc:
        logger.exception("Failed to send orchestrator weather action")
        await update.effective_message.reply_text(f"我解析到了天气查询，但发送给 WeatherBot 失败：{exc}")
        return

    await update.effective_message.reply_text(str(plan.get("summary") or "我先查询天气。"))


async def send_orchestrator_calendar_action(
    context: ContextTypes.DEFAULT_TYPE,
    workflow: dict,
) -> None:
    actions = workflow["actions"]
    index = int(workflow["index"])
    action_payload = dict(actions[index])
    action_payload["service"] = "calendar"
    action_payload["owner_chat_id"] = int(workflow["user_chat_id"])

    calendar_profile = str(context.application.bot_data.get("calendar_bot_profile") or "A")
    target_username = resolve_b2b_target(context, calendar_profile)
    if target_username is None:
        raise RuntimeError(f"CalendarBot profile {calendar_profile} is not configured.")

    source = await own_username(context)
    message = make_payload_request(
        source=source,
        target=target_username,
        payload=action_payload,
    )
    sent = await context.bot.send_message(chat_id=target_username, text=message.to_text())
    pending: dict[str, dict] = context.application.bot_data.setdefault(
        "orchestrator_pending",
        {},
    )
    pending[message.id] = workflow
    remember_b2b_event(
        context,
        f"orchestrator sent calendar {action_payload.get('action')} request {message.id} to {target_username} telegram_message_id={sent.message_id}",
    )


async def send_orchestrator_weather_action(
    context: ContextTypes.DEFAULT_TYPE,
    workflow: dict,
) -> None:
    actions = workflow["actions"]
    index = int(workflow["index"])
    action_payload = dict(actions[index])
    action_payload["service"] = "weather"

    weather_profile = str(context.application.bot_data.get("weather_bot_profile") or "B")
    target_username = resolve_b2b_target(context, weather_profile)
    if target_username is None:
        raise RuntimeError(f"WeatherBot profile {weather_profile} is not configured.")

    source = await own_username(context)
    message = make_payload_request(
        source=source,
        target=target_username,
        payload=action_payload,
    )
    sent = await context.bot.send_message(chat_id=target_username, text=message.to_text())
    pending: dict[str, dict] = context.application.bot_data.setdefault(
        "orchestrator_pending",
        {},
    )
    pending[message.id] = workflow
    remember_b2b_event(
        context,
        f"orchestrator sent weather {action_payload.get('date')} request {message.id} to {target_username} telegram_message_id={sent.message_id}",
    )


async def send_orchestrator_slot_matcher_action(
    context: ContextTypes.DEFAULT_TYPE,
    workflow: dict,
) -> None:
    actions = workflow["actions"]
    index = int(workflow["index"])
    action_payload = dict(actions[index])
    action_payload["service"] = "slot_matcher"

    matcher_profile = str(context.application.bot_data.get("slot_matcher_bot_profile") or "D")
    target_username = resolve_b2b_target(context, matcher_profile)
    if target_username is None:
        raise RuntimeError(f"SlotMatcherBot profile {matcher_profile} is not configured.")

    source = await own_username(context)
    message = make_payload_request(
        source=source,
        target=target_username,
        payload=action_payload,
    )
    sent = await context.bot.send_message(chat_id=target_username, text=message.to_text())
    pending: dict[str, dict] = context.application.bot_data.setdefault(
        "orchestrator_pending",
        {},
    )
    pending[message.id] = workflow
    remember_b2b_event(
        context,
        f"orchestrator sent slot_matcher request {message.id} to {target_username} telegram_message_id={sent.message_id}",
    )


async def handle_orchestrator_b2b_result(
    context: ContextTypes.DEFAULT_TYPE,
    envelope,
) -> bool:
    if not is_orchestrator_bot(context):
        return False
    payload_kind = str(envelope.payload.get("kind", "")).strip().lower()
    if payload_kind not in {"calendar.result", "weather.result", "slot_matcher.result"}:
        return False
    if not envelope.correlation_id:
        return False

    pending: dict[str, dict] = context.application.bot_data.setdefault(
        "orchestrator_pending",
        {},
    )
    workflow = pending.pop(envelope.correlation_id, None)
    if workflow is None:
        return False

    if workflow.get("service") == "weather_schedule":
        await handle_weather_schedule_result(context, workflow, envelope.payload)
        return True

    workflow["results"].append(envelope.payload)
    actions = workflow["actions"]
    index = int(workflow["index"])
    done = envelope.payload.get("ok") is not True or index >= len(actions) - 1
    if not done:
        workflow["index"] = index + 1
        try:
            if workflow.get("service") == "weather":
                await send_orchestrator_weather_action(context, workflow)
            else:
                await send_orchestrator_calendar_action(context, workflow)
        except Exception as exc:
            logger.exception("Failed to continue orchestrator workflow")
            await context.bot.send_message(
                chat_id=int(workflow["user_chat_id"]),
                text=f"前一步操作完成了，但继续下一步失败：{exc}",
            )
        return True

    await finish_orchestrator_workflow(context, workflow)
    return True


async def handle_weather_schedule_result(
    context: ContextTypes.DEFAULT_TYPE,
    workflow: dict,
    payload: dict,
) -> None:
    user_chat_id = int(workflow["user_chat_id"])
    stage = str(workflow.get("stage", "weather"))

    if payload.get("ok") is not True:
        await context.bot.send_message(
            chat_id=user_chat_id,
            text=f"工作流在 {stage} 阶段失败：{payload.get('error') or '未知错误'}",
        )
        return

    if stage == "weather":
        workflow["weather_results"].append(payload)
        if int(workflow["index"]) < len(workflow["actions"]) - 1:
            workflow["index"] = int(workflow["index"]) + 1
            await send_orchestrator_weather_action(context, workflow)
            return

        calendar_actions = [
            {
                "action": "free_time",
                "date": result.get("date"),
                "min_duration_minutes": int(workflow.get("duration_minutes") or 60),
            }
            for result in workflow["weather_results"]
            if result.get("date")
        ]
        if not calendar_actions:
            await context.bot.send_message(chat_id=user_chat_id, text="天气查询完成，但没有拿到可用日期。")
            return
        workflow["stage"] = "calendar"
        workflow["actions"] = calendar_actions
        workflow["index"] = 0
        await send_orchestrator_calendar_action(context, workflow)
        return

    if stage == "calendar":
        workflow["calendar_results"].append(payload)
        if int(workflow["index"]) < len(workflow["actions"]) - 1:
            workflow["index"] = int(workflow["index"]) + 1
            await send_orchestrator_calendar_action(context, workflow)
            return

        matcher_payload = build_slot_matcher_payload(workflow)
        if matcher_payload is None:
            await context.bot.send_message(chat_id=user_chat_id, text="没有拿到可匹配的天气时段或空闲时间。")
            return
        workflow["stage"] = "slot_matcher"
        workflow["actions"] = [matcher_payload]
        workflow["index"] = 0
        await send_orchestrator_slot_matcher_action(context, workflow)
        return

    if stage == "slot_matcher":
        matches = payload.get("matches") or []
        if not matches:
            await context.bot.send_message(
                chat_id=user_chat_id,
                text="我综合天气和你的空闲时间后，没有找到合适的共同时间段。",
            )
            return
        match = matches[0]
        workflow["selected_match"] = match
        workflow["stage"] = "add_event"
        workflow["actions"] = [
            {
                "action": "add_event",
                "title": str(workflow.get("activity_title") or "天气相关安排"),
                "starts_at": match["starts_at"],
                "ends_at": match["ends_at"],
                "on_conflict": "reject",
            }
        ]
        workflow["index"] = 0
        await send_orchestrator_calendar_action(context, workflow)
        return

    if stage == "add_event":
        await finish_weather_schedule_workflow(context, workflow, payload)
        return

    await context.bot.send_message(chat_id=user_chat_id, text=f"未知工作流阶段：{stage}")


def build_slot_matcher_payload(workflow: dict) -> dict | None:
    weather_periods: list[dict] = []
    for result in workflow.get("weather_results", []):
        for period in result.get("periods") or []:
            if isinstance(period, dict):
                weather_periods.append(period)

    calendar_blocks: list[dict] = []
    for result in workflow.get("calendar_results", []):
        for block in result.get("blocks") or []:
            if isinstance(block, dict):
                calendar_blocks.append(block)

    if not weather_periods or not calendar_blocks:
        return None

    return {
        "action": "match_slots",
        "goal": str(workflow.get("goal", "avoid_rain")),
        "duration_minutes": int(workflow.get("duration_minutes") or 60),
        "rain_threshold": int(workflow.get("rain_threshold") or 30),
        "weather_periods": weather_periods,
        "calendar_blocks": calendar_blocks,
    }


async def finish_weather_schedule_workflow(
    context: ContextTypes.DEFAULT_TYPE,
    workflow: dict,
    add_event_payload: dict,
) -> None:
    user_chat_id = int(workflow["user_chat_id"])
    match = workflow.get("selected_match") or {}
    title = str(workflow.get("activity_title") or "天气相关安排")
    if add_event_payload.get("ok") is True and add_event_payload.get("added"):
        event = add_event_payload.get("event") or {}
        probability = match.get("max_precipitation_probability")
        probability_text = "未知" if probability is None else f"{probability}%"
        await context.bot.send_message(
            chat_id=user_chat_id,
            text=(
                f"已为你安排{title}：\n"
                f"{summarize_calendar_result(add_event_payload)}\n"
                f"匹配依据：{match.get('weather') or '天气未知'}，降水概率最高 {probability_text}。"
            ),
        )

        context_by_chat: dict[int, list[dict]] = context.application.bot_data.setdefault(
            "orchestrator_context_by_chat",
            {},
        )
        recent_context = context_by_chat.setdefault(user_chat_id, [])
        recent_context.append(
            calendar_context_from_result(
                str(workflow.get("user_text", "")),
                workflow.get("actions", []),
                [add_event_payload],
            )
        )
        del recent_context[:-8]
        return

    await context.bot.send_message(
        chat_id=user_chat_id,
        text=summarize_calendar_result(add_event_payload),
    )


async def finish_orchestrator_workflow(
    context: ContextTypes.DEFAULT_TYPE,
    workflow: dict,
) -> None:
    user_chat_id = int(workflow["user_chat_id"])
    results = workflow["results"]
    actions = workflow["actions"]
    if workflow.get("service") == "weather":
        text = summarize_weather_results(
            results,
            goal=str(workflow.get("goal", "forecast")),
        )
        await context.bot.send_message(chat_id=user_chat_id, text=text)
        return

    lines = [summarize_calendar_result(result) for result in results]
    await context.bot.send_message(chat_id=user_chat_id, text="\n\n".join(lines))

    context_by_chat: dict[int, list[dict]] = context.application.bot_data.setdefault(
        "orchestrator_context_by_chat",
        {},
    )
    recent_context = context_by_chat.setdefault(user_chat_id, [])
    recent_context.append(
        calendar_context_from_result(
            str(workflow.get("user_text", "")),
            actions,
            results,
        )
    )
    del recent_context[:-8]


def is_orchestrator_bot(context: ContextTypes.DEFAULT_TYPE) -> bool:
    profile = str(context.application.bot_data.get("bot_profile") or "").upper()
    orchestrator_profile = str(
        context.application.bot_data.get("orchestrator_profile") or "C"
    ).upper()
    return bool(profile) and profile == orchestrator_profile


def looks_like_weather_request(user_text: str) -> bool:
    return bool(re.search(r"(天气|下雨|降水|雨|不下雨|晴|阴天|多云)", user_text))
