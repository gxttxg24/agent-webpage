
from __future__ import annotations

import logging
import sys

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    PicklePersistence,
    PersistenceInput,
    filters,
)

from .b2b.protocol import normalize_username
from .calendar.store import ScheduleStore
from .config import load_settings
from .llm import build_llm_clients
from .memory import MemoryStore
from .telegram.commands import b2b_calendar, b2b_debug, b2b_ping, b2b_status, b2b_weather
from .telegram.handlers import error_handler, handle_private_text, reset, start


logger = logging.getLogger(__name__)

def build_application(profile: str | None = None) -> Application:
    settings = load_settings(profile)
    persistence = PicklePersistence(
        filepath=settings.telegram_persistence_file,
        store_data=PersistenceInput(bot_data=False),
    )
    memory = MemoryStore(settings.memory_db)
    schedule = ScheduleStore(settings.schedule_db)
    llm, extract_llm = build_llm_clients(settings)

    application = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        .persistence(persistence)
        .concurrent_updates(False)
        .build()
    )

    application.bot_data["memory"] = memory
    application.bot_data["schedule"] = schedule
    application.bot_data["llm"] = llm
    application.bot_data["extract_llm"] = extract_llm
    application.bot_data["history_turns"] = settings.history_turns
    application.bot_data["b2b_seen_ids"] = set()
    application.bot_data["b2b_events"] = []
    application.bot_data["bot_profile"] = settings.bot_profile
    application.bot_data["orchestrator_profile"] = settings.orchestrator_profile
    application.bot_data["calendar_bot_profile"] = settings.calendar_bot_profile
    application.bot_data["weather_bot_profile"] = settings.weather_bot_profile
    application.bot_data["slot_matcher_bot_profile"] = settings.slot_matcher_bot_profile
    application.bot_data["orchestrator_pending"] = {}
    application.bot_data["orchestrator_pending_slots"] = {}
    application.bot_data["orchestrator_context_by_chat"] = {}
    application.bot_data["configured_bot_username"] = normalize_username(settings.telegram_username)
    application.bot_data["bot_peers"] = {
        profile: normalize_username(username)
        for profile, username in settings.bot_peers.items()
    }
    application.bot_data["settings_summary"] = {
        "persistence": str(settings.telegram_persistence_file),
        "memory_db": str(settings.memory_db),
        "schedule_db": str(settings.schedule_db),
    }

    private_chat = filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("start", start, filters=private_chat))
    application.add_handler(CommandHandler("reset", reset, filters=private_chat))
    application.add_handler(CommandHandler("b2b_ping", b2b_ping))
    application.add_handler(CommandHandler("b2b_status", b2b_status))
    application.add_handler(CommandHandler("b2b_calendar", b2b_calendar))
    application.add_handler(CommandHandler("b2b_weather", b2b_weather))
    application.add_handler(CommandHandler("b2b_debug", b2b_debug))
    application.add_handler(
        MessageHandler(
            private_chat & filters.TEXT & ~filters.COMMAND,
            handle_private_text,
        )
    )
    application.add_error_handler(error_handler)
    return application


def main(profile: str | None = None) -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    application = build_application(profile or _profile_from_argv(sys.argv[1:]))
    profile_name = application.bot_data.get("bot_profile", "")
    settings_summary = application.bot_data.get("settings_summary", {})
    logger.info(
        "Telegram agent bot%s is starting with long polling.",
        f" profile {profile_name}" if profile_name else "",
    )
    logger.info(
        "Bot storage: persistence=%s memory=%s schedule=%s",
        settings_summary.get("persistence", ""),
        settings_summary.get("memory_db", ""),
        settings_summary.get("schedule_db", ""),
    )
    application.run_polling(allowed_updates=Update.ALL_TYPES)


def _profile_from_argv(argv: list[str]) -> str | None:
    if not argv:
        return None
    if argv[0] in {"--profile", "-p"} and len(argv) >= 2:
        return argv[1]
    if argv[0].startswith("-"):
        return None
    return argv[0]

