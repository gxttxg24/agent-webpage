from __future__ import annotations

import re
from typing import Any


BotCatalog = list[dict[str, str]]


def build_bot_catalog(settings: Any) -> BotCatalog:
    roles = {
        settings.orchestrator_profile: ("OrchestratorBot", "orchestrator"),
        settings.calendar_bot_profile: ("CalendarBot", "calendar"),
        settings.weather_bot_profile: ("WeatherBot", "weather"),
        settings.slot_matcher_bot_profile: ("SlotMatcherBot", "slot_matcher"),
    }
    bots: BotCatalog = []
    for profile, username in settings.bot_peers.items():
        display_name, role = roles.get(profile, (f"Bot {profile}", "bot"))
        normalized_username = username if username.startswith("@") else f"@{username}"
        bots.append(
            {
                "profile": profile,
                "username": normalized_username,
                "display_name": display_name,
                "role": role,
                "aliases": ",".join(bot_aliases(normalized_username, display_name, role)),
            }
        )
    return bots


def roster_event(bot_catalog: BotCatalog, invited_profiles: set[str]) -> dict[str, Any]:
    return {
        "type": "bot_roster",
        "bots": [
            {**bot, "invited": bot["profile"] in invited_profiles}
            for bot in bot_catalog
        ],
    }


def mentions(text: str) -> list[str]:
    return re.findall(r"(?<![\w.])@[A-Za-z][A-Za-z0-9_]{2,31}", text)


def find_bot_by_mention(bot_catalog: BotCatalog, mention: str) -> dict[str, str] | None:
    normalized = mention.lower().removeprefix("@")
    for bot in bot_catalog:
        if normalized in bot_mention_keys(bot):
            return bot
    return None


def find_bot_by_profile(bot_catalog: BotCatalog, profile: str) -> dict[str, str] | None:
    normalized = profile.strip().upper()
    for bot in bot_catalog:
        if bot["profile"].upper() == normalized:
            return bot
    return None


def mentions_orchestrator(bot_catalog: BotCatalog, text: str) -> bool:
    mentioned = {item.lower().removeprefix("@") for item in mentions(text)}
    return any(
        bot["role"] == "orchestrator"
        and bool(bot_mention_keys(bot) & mentioned)
        for bot in bot_catalog
    )


def bot_aliases(username: str, display_name: str, role: str) -> set[str]:
    aliases = {
        username,
        display_name,
    }
    role_aliases = {
        "orchestrator": {"OrchestratorBot", "orchestrator"},
        "calendar": {"CalendarBot", "calendar"},
        "weather": {"WeatherBot", "weather"},
        "slot_matcher": {"SlotMatcherBot", "SlotMatcher", "slotmatcher"},
    }
    aliases.update(role_aliases.get(role, set()))
    return {
        alias.lower().removeprefix("@")
        for alias in aliases
        if alias.strip()
    }


def bot_mention_keys(bot: dict[str, str]) -> set[str]:
    aliases = set()
    aliases.add(str(bot.get("username", "")).lower().removeprefix("@"))
    aliases.add(str(bot.get("display_name", "")).lower().removeprefix("@"))
    aliases.update(
        item.strip().lower().removeprefix("@")
        for item in str(bot.get("aliases", "")).split(",")
        if item.strip()
    )
    return {item for item in aliases if item}


def strip_matched_mentions(text: str, matched_mentions: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        mention = match.group(0).lower().removeprefix("@")
        return "" if mention in matched_mentions else match.group(0)

    stripped = re.sub(r"(?<![\w.])@[A-Za-z][A-Za-z0-9_]{2,31}", replace, text)
    return re.sub(r"\s+", " ", stripped).strip()
