from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .chat_service import WebChatService


logger = logging.getLogger(__name__)

app = FastAPI(title="Telegram Agents Web")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("WEB_CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_service: WebChatService | None = None


@app.on_event("startup")
async def startup() -> None:
    global _service
    profile = os.getenv("WEB_BOT_PROFILE") or os.getenv("ORCHESTRATOR_PROFILE") or "C"
    _service = WebChatService(profile)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"ok": "true"}


@app.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    service = _require_service()
    session_id = websocket.query_params.get("session_id") or "web-default"
    await websocket.send_json({"type": "system", "text": "connected"})
    await websocket.send_json(service.bot_roster(session_id))

    async def send(event: dict[str, Any]) -> None:
        await websocket.send_json(event)

    try:
        while True:
            data = await websocket.receive_json()
            event_type = str(data.get("type", "user_message"))
            if event_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if event_type == "reset_session":
                service.reset(session_id)
                await websocket.send_json({"type": "system", "text": "session reset"})
                await websocket.send_json(service.bot_roster(session_id))
                continue
            if event_type == "schedule_overview":
                days = int(data.get("days", 7) or 7)
                owner_profile = str(data.get("owner_profile") or "ME").strip() or "ME"
                await websocket.send_json({"type": "workflow_status", "label": "Loading schedule"})
                await websocket.send_json(
                    service.schedule_overview(
                        session_id,
                        days=days,
                        owner_profile=owner_profile,
                    )
                )
                continue
            if event_type != "user_message":
                await websocket.send_json({"type": "error", "text": f"Unsupported event type: {event_type}"})
                continue

            text = str(data.get("text", "")).strip()
            if not text:
                continue
            conversation = str(data.get("conversation") or "group").strip().lower()
            target_profile = str(data.get("target_profile") or "").strip()
            await websocket.send_json({"type": "user_message_ack", "text": text})
            try:
                await service.handle_text(
                    session_id,
                    text,
                    send,
                    conversation=conversation,
                    target_profile=target_profile or None,
                )
            except Exception as exc:
                logger.exception("Web chat turn failed")
                await websocket.send_json(
                    {
                        "type": "error",
                        "text": f"{type(exc).__name__}: {exc}",
                    }
                )
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", session_id)


def _require_service() -> WebChatService:
    if _service is None:
        raise RuntimeError("WebChatService has not started.")
    return _service
