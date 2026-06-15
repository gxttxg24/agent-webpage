
from __future__ import annotations

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..b2b.protocol import make_payload_request, make_request
from .utils import (
    command_payload,
    format_b2b_peers,
    own_username,
    remember_b2b_event,
    resolve_b2b_target,
)


logger = logging.getLogger(__name__)

async def b2b_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return

    payload = command_payload(update)
    target_arg, _, text = payload.partition(" ")
    target_username = resolve_b2b_target(context, target_arg)
    if target_username is None:
        await update.effective_message.reply_text(
            "用法：/b2b_ping @OtherBot 可选消息，或 /b2b_ping C 可选消息\n"
            + format_b2b_peers(context)
        )
        return

    source = await own_username(context)
    logger.info("Bot-to-bot ping requested from %s to %s", source, target_username)
    message = make_request(
        source=source,
        target=target_username,
        text=text.strip() or "hello from tg_agent_bot",
    )
    try:
        sent = await context.bot.send_message(
            chat_id=target_username,
            text=message.to_text(),
        )
    except Exception as exc:
        remember_b2b_event(
            context,
            f"send failed request {message.id} to {target_username}: {type(exc).__name__}: {exc}",
        )
        logger.exception("Bot-to-bot REQUEST send failed")
        await update.effective_message.reply_text(
            f"发送失败：{type(exc).__name__}: {exc}\n"
            "请确认两个 bot 都在 BotFather 开启了 Bot-to-Bot Communication Mode。"
        )
        return

    remember_b2b_event(
        context,
        f"sent request {message.id} to {target_username} telegram_message_id={sent.message_id}",
    )
    await update.effective_message.reply_text(
        f"已向 {target_username} 发送 bot-to-bot REQUEST：{message.id}"
    )


async def b2b_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return

    source = await own_username(context)
    configured = context.application.bot_data.get("configured_bot_username") or "(not set)"
    seen_ids: set[str] = context.application.bot_data.setdefault("b2b_seen_ids", set())
    profile = context.application.bot_data.get("bot_profile") or "(default)"
    events = context.application.bot_data.setdefault("b2b_events", [])
    event_text = "\n".join(f"- {event}" for event in events[-8:]) or "- 暂无"
    await update.effective_message.reply_text(
        f"bot-to-bot 已启用。Profile：{profile}\n"
        f"本 bot：{source}\n"
        f".env username：{configured}\n"
        f"已见过结构化消息：{len(seen_ids)} 条\n"
        f"{format_b2b_peers(context)}\n"
        "最近事件：\n"
        f"{event_text}\n"
        "发送测试：/b2b_ping C hello 或 /b2b_ping @OtherBot hello"
    )


async def b2b_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    payload = command_payload(update)
    target_arg, _, json_text = payload.partition(" ")
    target_username = resolve_b2b_target(context, target_arg)
    if target_username is None or not json_text.strip():
        await update.effective_message.reply_text(
            "用法：/b2b_calendar A {\"action\":\"free_time\",\"date\":\"2026-06-05\",\"min_duration_minutes\":120}\n"
            + format_b2b_peers(context)
        )
        return

    try:
        calendar_payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        await update.effective_message.reply_text(f"JSON 无效：{exc}")
        return

    if not isinstance(calendar_payload, dict):
        await update.effective_message.reply_text("calendar payload 必须是 JSON object。")
        return

    calendar_payload.setdefault("service", "calendar")
    calendar_payload.setdefault("owner_chat_id", update.effective_chat.id)

    source = await own_username(context)
    message = make_payload_request(
        source=source,
        target=target_username,
        payload=calendar_payload,
    )
    try:
        sent = await context.bot.send_message(chat_id=target_username, text=message.to_text())
    except Exception as exc:
        remember_b2b_event(
            context,
            f"calendar send failed {message.id} to {target_username}: {type(exc).__name__}: {exc}",
        )
        logger.exception("Bot-to-bot calendar request send failed")
        await update.effective_message.reply_text(f"发送失败：{type(exc).__name__}: {exc}")
        return

    remember_b2b_event(
        context,
        f"sent calendar {calendar_payload.get('action')} request {message.id} to {target_username} telegram_message_id={sent.message_id}",
    )
    await update.effective_message.reply_text(
        f"已向 {target_username} 发送 calendar.{calendar_payload.get('action')} 请求：{message.id}"
    )


async def b2b_weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return

    payload = command_payload(update)
    target_arg, _, json_text = payload.partition(" ")
    target_username = resolve_b2b_target(context, target_arg)
    if target_username is None or not json_text.strip():
        await update.effective_message.reply_text(
            "用法：/b2b_weather B {\"location\":\"北京\",\"date\":\"2026-06-05\"}\n"
            + format_b2b_peers(context)
        )
        return

    try:
        weather_payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        await update.effective_message.reply_text(f"JSON 无效：{exc}")
        return

    if not isinstance(weather_payload, dict):
        await update.effective_message.reply_text("weather payload 必须是 JSON object。")
        return

    weather_payload.setdefault("service", "weather")
    weather_payload.setdefault("action", "hourly_forecast")

    source = await own_username(context)
    message = make_payload_request(
        source=source,
        target=target_username,
        payload=weather_payload,
    )
    try:
        sent = await context.bot.send_message(chat_id=target_username, text=message.to_text())
    except Exception as exc:
        remember_b2b_event(
            context,
            f"weather send failed {message.id} to {target_username}: {type(exc).__name__}: {exc}",
        )
        logger.exception("Bot-to-bot weather request send failed")
        await update.effective_message.reply_text(f"发送失败：{type(exc).__name__}: {exc}")
        return

    remember_b2b_event(
        context,
        f"sent weather {weather_payload.get('action')} request {message.id} to {target_username} telegram_message_id={sent.message_id}",
    )
    await update.effective_message.reply_text(
        f"已向 {target_username} 发送 weather.{weather_payload.get('action')} 请求：{message.id}"
    )


async def b2b_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return

    me = await context.bot.get_me()
    source = await own_username(context)
    configured = context.application.bot_data.get("configured_bot_username") or "(not set)"
    profile = context.application.bot_data.get("bot_profile") or "(default)"
    settings_summary = context.application.bot_data.get("settings_summary", {})
    peers = format_b2b_peers(context)
    chat = update.effective_chat
    chat_label = f"{chat.type}:{chat.id}" if chat is not None else "(unknown)"
    await update.effective_message.reply_text(
        "b2b debug\n"
        f"profile: {profile}\n"
        f"getMe: id={me.id}, username=@{me.username}\n"
        f"protocol source: {source}\n"
        f".env username: {configured}\n"
        f"{peers}\n"
        f"chat: {chat_label}\n"
        f"persistence: {settings_summary.get('persistence', '')}\n"
        f"memory_db: {settings_summary.get('memory_db', '')}\n"
        f"schedule_db: {settings_summary.get('schedule_db', '')}"
    )
