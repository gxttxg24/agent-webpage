from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tg_agent_bot.telegram.utils import (
    command_payload,
    format_b2b_peers,
    own_username,
    remember_b2b_event,
    resolve_b2b_target,
)


class FakeBot:
    def __init__(self, username: str = "CurrentBot") -> None:
        self.calls = 0
        self.username = username

    async def get_me(self):
        self.calls += 1
        return SimpleNamespace(id=12345, username=self.username)


def fake_context(bot_data: dict | None = None, bot: FakeBot | None = None):
    return SimpleNamespace(
        application=SimpleNamespace(bot_data=bot_data if bot_data is not None else {}),
        bot=bot or FakeBot(),
    )


def fake_update(text: str | None):
    message = None if text is None else SimpleNamespace(text=text)
    return SimpleNamespace(effective_message=message)


def test_command_payload_returns_text_after_command() -> None:
    assert command_payload(fake_update("/b2b_ping C hello world")) == "C hello world"
    assert command_payload(fake_update("/start")) == ""
    assert command_payload(fake_update(None)) == ""


def test_remember_b2b_event_keeps_last_twenty_items() -> None:
    context = fake_context()

    for index in range(25):
        remember_b2b_event(context, f"event-{index}")

    assert context.application.bot_data["b2b_events"] == [
        f"event-{index}" for index in range(5, 25)
    ]


def test_resolve_b2b_target_accepts_username_or_profile() -> None:
    context = fake_context({"bot_peers": {"A": "@CalendarBot", "C": "OrchestratorBot"}})

    assert resolve_b2b_target(context, "@DirectBot") == "@DirectBot"
    assert resolve_b2b_target(context, "a") == "@CalendarBot"
    assert resolve_b2b_target(context, "C") == "@OrchestratorBot"
    assert resolve_b2b_target(context, "missing") is None
    assert resolve_b2b_target(context, "") is None


def test_format_b2b_peers_lists_configured_profiles() -> None:
    context = fake_context({"bot_peers": {"A": "@CalendarBot", "B": "@WeatherBot"}})

    text = format_b2b_peers(context)

    assert "A=@CalendarBot" in text
    assert "B=@WeatherBot" in text


def test_format_b2b_peers_handles_empty_config() -> None:
    assert isinstance(format_b2b_peers(fake_context()), str)


def test_own_username_uses_cached_value_before_get_me() -> None:
    bot = FakeBot()
    context = fake_context({"bot_username": "CachedBot"}, bot)

    assert asyncio.run(own_username(context)) == "@CachedBot"
    assert bot.calls == 0


def test_own_username_fetches_and_caches_get_me_username() -> None:
    bot = FakeBot(username="FetchedBot")
    context = fake_context({}, bot)

    assert asyncio.run(own_username(context)) == "@FetchedBot"
    assert context.application.bot_data["bot_username"] == "@FetchedBot"
    assert asyncio.run(own_username(context)) == "@FetchedBot"
    assert bot.calls == 1
