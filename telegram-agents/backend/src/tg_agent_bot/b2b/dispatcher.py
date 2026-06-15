
from __future__ import annotations

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..calendar.service import CalendarServiceError, handle_calendar_request, is_calendar_request
from ..calendar.store import ScheduleStore
from ..orchestrator.workflows import handle_orchestrator_b2b_result
from ..slot_matcher.service import (
    SlotMatcherServiceError,
    handle_slot_matcher_request,
    is_slot_matcher_request,
)
from ..telegram.formatting import telegram_safe_envelope_text
from ..telegram.utils import own_username, remember_b2b_event
from ..weather.service import WeatherServiceError, handle_weather_request, is_weather_request
from .protocol import (
    ACK,
    B2BEnvelope,
    B2BProtocolError,
    make_ack,
    make_response,
    normalize_username,
    parse_envelope,
    should_ack,
    username_matches,
)


logger = logging.getLogger(__name__)

async def handle_b2b_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_text: str,
) -> bool:
    if update.effective_message is None:
        return False

    try:
        envelope = parse_envelope(user_text)
    except B2BProtocolError as exc:
        await update.effective_message.reply_text(f"收到 bot-to-bot 消息，但协议校验失败：{exc}")
        return True

    if envelope is None:
        return False

    my_username = await own_username(context)
    seen_ids: set[str] = context.application.bot_data.setdefault("b2b_seen_ids", set())
    already_seen = envelope.id in seen_ids
    seen_ids.add(envelope.id)

    if already_seen:
        remember_b2b_event(context, f"ignored duplicate {envelope.message_type} {envelope.id}")
        logger.info("Duplicate bot-to-bot message ignored: %s", envelope.id)
        return True

    if not envelope.target or not normalize_username(envelope.target):
        remember_b2b_event(context, f"ignored message {envelope.id}: empty target")
        logger.info("Bot-to-bot message without target ignored: %s", envelope.id)
        return True

    if not username_matches(envelope.target, my_username):
        remember_b2b_event(
            context,
            f"ignored {envelope.message_type} {envelope.id}: target {envelope.target}, this bot {my_username}",
        )
        logger.info(
            "Bot-to-bot message %s ignored because target is %s, this bot is %s",
            envelope.id,
            envelope.target,
            my_username,
        )
        return True

    sender = update.effective_user
    if sender is not None and sender.username:
        sender_username = normalize_username(sender.username)
        if not username_matches(sender_username, envelope.source):
            remember_b2b_event(
                context,
                f"ignored {envelope.message_type} {envelope.id}: sender {sender_username}, source {envelope.source}",
            )
            logger.info(
                "Bot-to-bot message %s ignored because sender %s does not match source %s",
                envelope.id,
                sender_username,
                envelope.source,
            )
            return True

    if envelope.message_type == ACK:
        payload_kind = str(envelope.payload.get("kind", "")).strip().lower()
        if await handle_orchestrator_b2b_result(context, envelope):
            return True
        if payload_kind == "calendar.result":
            remember_b2b_event(
                context,
                f"received calendar.result {envelope.payload.get('action')} ok={envelope.payload.get('ok')} from {envelope.source}",
            )
        elif payload_kind == "weather.result":
            remember_b2b_event(
                context,
                f"received weather.result {envelope.payload.get('action')} ok={envelope.payload.get('ok')} from {envelope.source}",
            )
        elif payload_kind == "slot_matcher.result":
            remember_b2b_event(
                context,
                f"received slot_matcher.result ok={envelope.payload.get('ok')} from {envelope.source}",
            )
        else:
            remember_b2b_event(
                context,
                f"received ack {envelope.id} from {envelope.source} for {envelope.correlation_id}",
            )
        remember_b2b_event(
            context,
            f"payload={json.dumps(envelope.payload, ensure_ascii=False)[:800]}",
        )
        logger.info(
            "Bot-to-bot ACK received from %s for %s",
            envelope.source,
            envelope.correlation_id,
        )
        return True

    if is_calendar_request(envelope.payload):
        await handle_calendar_b2b_request(context, envelope, my_username)
        return True

    if is_weather_request(envelope.payload):
        await handle_weather_b2b_request(context, envelope, my_username)
        return True

    if is_slot_matcher_request(envelope.payload):
        await handle_slot_matcher_b2b_request(context, envelope, my_username)
        return True

    if should_ack(envelope, seen_ids - {envelope.id}, my_username):
        ack = make_ack(source=my_username, request=envelope)
        seen_ids.add(ack.id)
        await context.bot.send_message(chat_id=envelope.source, text=ack.to_text())
        remember_b2b_event(
            context,
            f"received request {envelope.id} from {envelope.source}; sent ack {ack.id}",
        )
        logger.info("Bot-to-bot ACK sent to %s for %s", envelope.source, envelope.id)
        return True

    remember_b2b_event(
        context,
        f"consumed request {envelope.id} from {envelope.source} without ack depth={envelope.depth}/{envelope.max_depth}",
    )
    logger.info(
        "Bot-to-bot REQUEST %s consumed without ACK at depth %s/%s",
        envelope.id,
        envelope.depth,
        envelope.max_depth,
    )
    return True


async def handle_calendar_b2b_request(
    context: ContextTypes.DEFAULT_TYPE,
    envelope,
    my_username: str,
) -> None:
    schedule: ScheduleStore = context.application.bot_data["schedule"]
    seen_ids: set[str] = context.application.bot_data.setdefault("b2b_seen_ids", set())

    try:
        result_payload = handle_calendar_request(schedule, envelope.payload)
    except CalendarServiceError as exc:
        result_payload = {
            "kind": "calendar.result",
            "service": "calendar",
            "action": str(envelope.payload.get("action", "")),
            "ok": False,
            "error": str(exc),
        }
    except Exception as exc:
        logger.exception("Calendar service request failed")
        result_payload = {
            "kind": "calendar.result",
            "service": "calendar",
            "action": str(envelope.payload.get("action", "")),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    response = make_response(source=my_username, request=envelope, payload=result_payload)
    seen_ids.add(response.id)
    await context.bot.send_message(chat_id=envelope.source, text=telegram_safe_envelope_text(response))
    status = "ok" if result_payload.get("ok") else "error"
    remember_b2b_event(
        context,
        f"calendar {result_payload.get('action') or '(missing)'} {status} for {envelope.source}; response {response.id}",
    )


async def handle_weather_b2b_request(
    context: ContextTypes.DEFAULT_TYPE,
    envelope,
    my_username: str,
) -> None:
    seen_ids: set[str] = context.application.bot_data.setdefault("b2b_seen_ids", set())

    try:
        result_payload = await handle_weather_request(envelope.payload)
    except WeatherServiceError as exc:
        result_payload = {
            "kind": "weather.result",
            "service": "weather",
            "action": str(envelope.payload.get("action", "")),
            "ok": False,
            "error": str(exc),
        }
    except Exception as exc:
        logger.exception("Weather service request failed")
        result_payload = {
            "kind": "weather.result",
            "service": "weather",
            "action": str(envelope.payload.get("action", "")),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    response = make_response(source=my_username, request=envelope, payload=result_payload)
    seen_ids.add(response.id)
    await context.bot.send_message(chat_id=envelope.source, text=telegram_safe_envelope_text(response))
    status = "ok" if result_payload.get("ok") else "error"
    remember_b2b_event(
        context,
        f"weather {result_payload.get('action') or '(missing)'} {status} for {envelope.source}; response {response.id}",
    )


async def handle_slot_matcher_b2b_request(
    context: ContextTypes.DEFAULT_TYPE,
    envelope,
    my_username: str,
) -> None:
    seen_ids: set[str] = context.application.bot_data.setdefault("b2b_seen_ids", set())

    try:
        result_payload = handle_slot_matcher_request(envelope.payload)
    except SlotMatcherServiceError as exc:
        result_payload = {
            "kind": "slot_matcher.result",
            "service": "slot_matcher",
            "action": str(envelope.payload.get("action", "")),
            "ok": False,
            "error": str(exc),
        }
    except Exception as exc:
        logger.exception("Slot matcher service request failed")
        result_payload = {
            "kind": "slot_matcher.result",
            "service": "slot_matcher",
            "action": str(envelope.payload.get("action", "")),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    response = make_response(source=my_username, request=envelope, payload=result_payload)
    seen_ids.add(response.id)
    await context.bot.send_message(chat_id=envelope.source, text=telegram_safe_envelope_text(response))
    status = "ok" if result_payload.get("ok") else "error"
    remember_b2b_event(
        context,
        f"slot_matcher {status} for {envelope.source}; response {response.id}",
    )
