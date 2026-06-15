from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


PROTOCOL = "tg-agent-b2b"
VERSION = 1
REQUEST = "request"
ACK = "ack"


class B2BProtocolError(ValueError):
    """Raised when a text message is not a valid bot-to-bot envelope."""


@dataclass(frozen=True)
class B2BEnvelope:
    id: str
    message_type: str
    source: str
    target: str
    payload: dict[str, Any]
    conversation_id: str
    depth: int = 0
    max_depth: int = 1
    correlation_id: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "protocol": PROTOCOL,
            "version": VERSION,
            "id": self.id,
            "type": self.message_type,
            "source": normalize_username(self.source),
            "target": normalize_username(self.target),
            "conversation_id": self.conversation_id,
            "depth": self.depth,
            "max_depth": self.max_depth,
            "created_at": self.created_at or _now_iso(),
            "payload": self.payload,
        }
        if self.correlation_id:
            data["correlation_id"] = self.correlation_id
        return data

    def to_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def normalize_username(username: str) -> str:
    value = username.strip()
    if not value:
        return value
    return value if value.startswith("@") else f"@{value}"


def username_matches(left: str, right: str) -> bool:
    return normalize_username(left).casefold() == normalize_username(right).casefold()


def make_request(source: str, target: str, text: str) -> B2BEnvelope:
    return make_payload_request(
        source=source,
        target=target,
        payload={
            "kind": "hello",
            "text": text,
        },
    )


def make_payload_request(
    source: str,
    target: str,
    payload: dict[str, Any],
) -> B2BEnvelope:
    message_id = str(uuid4())
    return B2BEnvelope(
        id=message_id,
        message_type=REQUEST,
        source=source,
        target=target,
        conversation_id=message_id,
        payload=payload,
    )


def make_ack(source: str, request: B2BEnvelope) -> B2BEnvelope:
    return make_response(
        source=source,
        request=request,
        payload={
            "kind": "ack",
            "received_id": request.id,
            "received_payload_kind": str(request.payload.get("kind", "")),
        },
    )


def make_response(
    source: str,
    request: B2BEnvelope,
    payload: dict[str, Any],
) -> B2BEnvelope:
    return B2BEnvelope(
        id=str(uuid4()),
        message_type=ACK,
        source=source,
        target=request.source,
        conversation_id=request.conversation_id,
        correlation_id=request.id,
        depth=request.depth + 1,
        max_depth=request.max_depth,
        payload=payload,
    )


def parse_envelope(text: str) -> B2BEnvelope | None:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None

    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError:
        return None

    if not isinstance(raw, dict) or raw.get("protocol") != PROTOCOL:
        return None

    try:
        version = int(raw["version"])
        message_id = str(raw["id"]).strip()
        message_type = str(raw["type"]).strip().lower()
        source = normalize_username(str(raw["source"]))
        target = normalize_username(str(raw["target"]))
        conversation_id = str(raw["conversation_id"]).strip()
        depth = int(raw.get("depth", 0))
        max_depth = int(raw.get("max_depth", 1))
        payload = raw.get("payload")
    except (KeyError, TypeError, ValueError) as exc:
        raise B2BProtocolError("Invalid bot-to-bot envelope fields.") from exc

    if version != VERSION:
        raise B2BProtocolError(f"Unsupported bot-to-bot protocol version: {version}.")
    if message_type not in {REQUEST, ACK}:
        raise B2BProtocolError(f"Unsupported bot-to-bot message type: {message_type}.")
    if not message_id or not source or not target or not conversation_id:
        raise B2BProtocolError("Bot-to-bot envelope identifiers must not be empty.")
    if depth < 0 or max_depth < 0:
        raise B2BProtocolError("Bot-to-bot depth values must not be negative.")
    if not isinstance(payload, dict):
        raise B2BProtocolError("Bot-to-bot payload must be a JSON object.")

    correlation_id = raw.get("correlation_id")
    return B2BEnvelope(
        id=message_id,
        message_type=message_type,
        source=source,
        target=target,
        conversation_id=conversation_id,
        correlation_id=str(correlation_id) if correlation_id else None,
        depth=depth,
        max_depth=max_depth,
        created_at=str(raw.get("created_at", "")),
        payload=payload,
    )


def should_ack(envelope: B2BEnvelope, seen_ids: set[str], my_username: str) -> bool:
    if envelope.id in seen_ids:
        return False
    if not username_matches(envelope.target, my_username):
        return False
    if envelope.message_type != REQUEST:
        return False
    return envelope.depth < envelope.max_depth


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
