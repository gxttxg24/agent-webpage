from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WebSessionState:
    context_by_chat: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    group_context_by_chat: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    pending_slots: dict[int, dict[str, Any]] = field(default_factory=dict)
    invited_bots_by_chat: dict[int, set[str]] = field(default_factory=dict)

    def clear_chat(self, chat_id: int) -> None:
        self.context_by_chat.pop(chat_id, None)
        self.group_context_by_chat.pop(chat_id, None)
        self.pending_slots.pop(chat_id, None)
        self.invited_bots_by_chat.pop(chat_id, None)

    def personal_context(self, chat_id: int) -> list[dict[str, Any]]:
        return self.context_by_chat.setdefault(chat_id, [])

    def group_context(self, chat_id: int) -> list[dict[str, Any]]:
        return self.group_context_by_chat.setdefault(chat_id, [])

    def invited_profiles(self, chat_id: int) -> set[str]:
        return self.invited_bots_by_chat.setdefault(chat_id, set())


def chat_id(session_id: str) -> int:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def participant_chat_id(session_id: str, profile: str) -> int:
    normalized_profile = (profile or "ME").strip().upper() or "ME"
    return chat_id(f"{session_id}:participant:{normalized_profile}")


def combined_context(
    personal_context: list[dict[str, Any]],
    group_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for item in group_context[-8:]:
        combined.append({"scope": "group", **item})
    for item in personal_context[-6:]:
        combined.append({"scope": "self", **item})
    return combined[-10:]
