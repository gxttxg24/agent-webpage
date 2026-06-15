from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_profile: str
    telegram_token: str
    telegram_username: str
    bot_peers: dict[str, str]
    telegram_persistence_file: Path
    codex_base_url: str
    codex_api_key: str
    codex_model: str
    codex_extract_model: str
    history_turns: int
    memory_db: Path
    schedule_db: Path
    orchestrator_profile: str
    calendar_bot_profile: str
    weather_bot_profile: str
    slot_matcher_bot_profile: str


def load_settings(profile: str | None = None) -> Settings:
    load_dotenv()

    bot_profile = _normalize_profile(profile or os.getenv("BOT_PROFILE", ""))
    token = (
        _profile_env(bot_profile, "TOKEN")
        or os.getenv("TG_BOT_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )
    if not token:
        profile_hint = f"BOT_{bot_profile}_TOKEN" if bot_profile else "TG_BOT_TOKEN or TELEGRAM_BOT_TOKEN"
        raise RuntimeError(
            f"Telegram bot token is missing. Add {profile_hint} to .env."
        )

    history_turns = int(os.getenv("BOT_HISTORY_TURNS", "8"))
    profile_suffix = f"_{bot_profile.lower()}" if bot_profile else ""
    telegram_persistence_file = Path(
        _profile_env(bot_profile, "PERSISTENCE_FILE")
        or os.getenv(
            "TELEGRAM_PERSISTENCE_FILE",
            f"data/telegram_persistence{profile_suffix}.pickle",
        )
    )
    memory_db = Path(
        _profile_env(bot_profile, "MEMORY_DB")
        or os.getenv("BOT_MEMORY_DB", f"data/bot_memory{profile_suffix}.sqlite3")
    )
    schedule_db = Path(
        _profile_env(bot_profile, "SCHEDULE_DB")
        or os.getenv("BOT_SCHEDULE_DB", f"data/bot_schedule{profile_suffix}.sqlite3")
    )
    codex_model = (
        os.getenv("CODEX_MODEL", "").strip()
        or "gpt-5.2"
    )

    return Settings(
        bot_profile=bot_profile,
        telegram_token=token,
        telegram_username=_profile_env(bot_profile, "USERNAME"),
        bot_peers=_discover_bot_usernames(),
        telegram_persistence_file=telegram_persistence_file,
        codex_base_url=os.getenv("CODEX_BASE_URL", "").strip().rstrip("/"),
        codex_api_key=os.getenv("CODEX_API_KEY", "").strip(),
        codex_model=codex_model,
        codex_extract_model=(
            os.getenv("CODEX_EXTRACT_MODEL", "").strip()
            or codex_model
        ),
        history_turns=max(1, history_turns),
        memory_db=memory_db,
        schedule_db=schedule_db,
        orchestrator_profile=_normalize_profile(os.getenv("ORCHESTRATOR_PROFILE", "C")),
        calendar_bot_profile=_normalize_profile(os.getenv("CALENDAR_BOT_PROFILE", "A")),
        weather_bot_profile=_normalize_profile(os.getenv("WEATHER_BOT_PROFILE", "B")),
        slot_matcher_bot_profile=_normalize_profile(os.getenv("SLOT_MATCHER_BOT_PROFILE", "D")),
    )


def _normalize_profile(profile: str) -> str:
    value = profile.strip().upper()
    if not value:
        return ""
    if not value.replace("_", "").isalnum():
        raise RuntimeError("Bot profile must contain only letters, numbers, or underscores.")
    if value.startswith("BOT_"):
        value = value[4:]
    return value


def _profile_env(profile: str, key: str) -> str:
    if not profile:
        return ""
    return os.getenv(f"BOT_{profile}_{key}", "").strip()


def _discover_bot_usernames() -> dict[str, str]:
    peers: dict[str, str] = {}
    for key, value in os.environ.items():
        if not key.startswith("BOT_") or not key.endswith("_USERNAME"):
            continue
        profile = key.removeprefix("BOT_").removesuffix("_USERNAME")
        normalized_profile = _normalize_profile(profile)
        username = value.strip()
        if normalized_profile and username:
            peers[normalized_profile] = username
    return dict(sorted(peers.items()))
