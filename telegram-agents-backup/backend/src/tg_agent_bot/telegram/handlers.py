
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from ..b2b.dispatcher import handle_b2b_message
from ..b2b.protocol import B2BProtocolError, parse_envelope
from ..llm import LLMClient
from ..memory import MemoryStore
from ..orchestrator.workflows import handle_orchestrator_text, is_orchestrator_bot


logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return

    await update.effective_message.reply_text(
        "你好，我已经在线。私聊 OrchestratorBot 可以发起日程、天气和空闲时间匹配协作。"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    memory: MemoryStore = context.application.bot_data["memory"]
    memory.clear(update.effective_chat.id)
    context.application.bot_data.setdefault("orchestrator_context_by_chat", {}).pop(
        update.effective_chat.id,
        None,
    )
    context.application.bot_data.setdefault("orchestrator_pending_slots", {}).pop(
        update.effective_chat.id,
        None,
    )
    await update.effective_message.reply_text("已清空这段私聊的上下文记忆。")


async def handle_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    user_text = update.effective_message.text or ""
    if not user_text.strip():
        return

    if await handle_b2b_message(update, context, user_text):
        return

    if is_orchestrator_bot(context):
        if await handle_orchestrator_text(update, context, user_text):
            return

    memory: MemoryStore = context.application.bot_data["memory"]
    llm: LLMClient = context.application.bot_data["llm"]
    history_turns: int = context.application.bot_data["history_turns"]
    chat_id = update.effective_chat.id

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    history = memory.recent(chat_id, limit=history_turns * 2)

    try:
        reply = await llm.reply(history=history, user_text=user_text)
    except Exception:
        logger.exception("LLM request failed")
        reply = (
            "我收到了你的消息，但 Codex API 暂时不可用。"
            "请确认 CODEX_API_KEY、CODEX_BASE_URL 和模型配置可用。"
        )

    memory.add(chat_id, "user", user_text)
    memory.add(chat_id, "assistant", reply)
    await update.effective_message.reply_text(reply)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Telegram update failed", exc_info=context.error)
