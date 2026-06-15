
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..b2b.protocol import normalize_username


def command_payload(update: Update) -> str:
    if update.effective_message is None or update.effective_message.text is None:
        return ""
    _, _, payload = update.effective_message.text.partition(" ")
    return payload.strip()


def remember_b2b_event(context: ContextTypes.DEFAULT_TYPE, event: str) -> None:
    events = context.application.bot_data.setdefault("b2b_events", [])
    events.append(event)
    del events[:-20]


def resolve_b2b_target(context: ContextTypes.DEFAULT_TYPE, target_arg: str) -> str | None:
    target = target_arg.strip()
    if not target:
        return None
    if target.startswith("@"):
        return normalize_username(target)

    peers: dict[str, str] = context.application.bot_data.get("bot_peers", {})
    username = peers.get(target.upper())
    return normalize_username(username) if username else None


def format_b2b_peers(context: ContextTypes.DEFAULT_TYPE) -> str:
    peers: dict[str, str] = context.application.bot_data.get("bot_peers", {})
    if not peers:
        return "已配置 peers：暂无"
    peer_text = ", ".join(f"{profile}={username}" for profile, username in peers.items())
    return f"已配置 peers：{peer_text}"


async def own_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    cached = context.application.bot_data.get("bot_username")
    if isinstance(cached, str) and cached:
        return normalize_username(cached)

    me = await context.bot.get_me()
    username = normalize_username(me.username or str(me.id))
    context.application.bot_data["bot_username"] = username
    return username
