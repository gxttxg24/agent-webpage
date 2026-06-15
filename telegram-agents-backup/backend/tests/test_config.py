from __future__ import annotations

import os
from pathlib import Path

import pytest

import tg_agent_bot.config as config


ENV_KEYS = {
    "BOT_PROFILE",
    "TG_BOT_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_PERSISTENCE_FILE",
    "BOT_MEMORY_DB",
    "BOT_SCHEDULE_DB",
    "BOT_HISTORY_TURNS",
    "CODEX_BASE_URL",
    "CODEX_API_KEY",
    "CODEX_MODEL",
    "CODEX_EXTRACT_MODEL",
    "ORCHESTRATOR_PROFILE",
    "CALENDAR_BOT_PROFILE",
    "WEATHER_BOT_PROFILE",
    "SLOT_MATCHER_BOT_PROFILE",
}


def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "load_dotenv", lambda: False)
    for key in list(os.environ):
        if key in ENV_KEYS or key.startswith("BOT_"):
            monkeypatch.delenv(key, raising=False)


def test_load_settings_reads_profile_specific_bot_config(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_environment(monkeypatch)
    monkeypatch.setenv("BOT_A_TOKEN", "token-a")
    monkeypatch.setenv("BOT_A_USERNAME", "@CalendarBot")
    monkeypatch.setenv("BOT_B_USERNAME", "@WeatherBot")
    monkeypatch.setenv("BOT_C_USERNAME", "@OrchestratorBot")
    monkeypatch.setenv("BOT_D_USERNAME", "@SlotMatcherBot")
    monkeypatch.setenv("CODEX_BASE_URL", "https://example.test/")
    monkeypatch.setenv("CODEX_API_KEY", "test-key")
    monkeypatch.setenv("CODEX_MODEL", "model-main")
    monkeypatch.setenv("CODEX_EXTRACT_MODEL", "model-extract")

    settings = config.load_settings("A")

    assert settings.bot_profile == "A"
    assert settings.telegram_token == "token-a"
    assert settings.telegram_username == "@CalendarBot"
    assert settings.bot_peers == {
        "A": "@CalendarBot",
        "B": "@WeatherBot",
        "C": "@OrchestratorBot",
        "D": "@SlotMatcherBot",
    }
    assert settings.codex_base_url == "https://example.test"
    assert settings.codex_model == "model-main"
    assert settings.codex_extract_model == "model-extract"
    assert settings.memory_db == Path("data/bot_memory_a.sqlite3")
    assert settings.schedule_db == Path("data/bot_schedule_a.sqlite3")


def test_load_settings_uses_fallback_token_and_default_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_environment(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fallback-token")
    monkeypatch.setenv("CODEX_BASE_URL", "https://example.test")
    monkeypatch.setenv("CODEX_API_KEY", "test-key")

    settings = config.load_settings()

    assert settings.bot_profile == ""
    assert settings.telegram_token == "fallback-token"
    assert settings.orchestrator_profile == "C"
    assert settings.calendar_bot_profile == "A"
    assert settings.weather_bot_profile == "B"
    assert settings.slot_matcher_bot_profile == "D"
    assert settings.codex_model == "gpt-5.2"
    assert settings.codex_extract_model == "gpt-5.2"
    assert settings.history_turns == 8


def test_profile_specific_storage_paths_override_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_environment(monkeypatch)
    monkeypatch.setenv("BOT_C_TOKEN", "token-c")
    monkeypatch.setenv("BOT_C_PERSISTENCE_FILE", "tmp/c.pickle")
    monkeypatch.setenv("BOT_C_MEMORY_DB", "tmp/c-memory.sqlite3")
    monkeypatch.setenv("BOT_C_SCHEDULE_DB", "tmp/c-schedule.sqlite3")
    monkeypatch.setenv("CODEX_BASE_URL", "https://example.test")
    monkeypatch.setenv("CODEX_API_KEY", "test-key")

    settings = config.load_settings("C")

    assert settings.telegram_persistence_file == Path("tmp/c.pickle")
    assert settings.memory_db == Path("tmp/c-memory.sqlite3")
    assert settings.schedule_db == Path("tmp/c-schedule.sqlite3")


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_environment(monkeypatch)

    with pytest.raises(RuntimeError, match="Telegram bot token is missing"):
        config.load_settings("C")


def test_invalid_profile_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_environment(monkeypatch)
    monkeypatch.setenv("BOT_BAD_TOKEN", "token")

    with pytest.raises(RuntimeError, match="Bot profile must contain only"):
        config.load_settings("bad-profile")
