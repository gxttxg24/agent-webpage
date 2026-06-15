from __future__ import annotations

from typing import Any


def make_pending_slot(service: str, original_text: str, ask_user: str) -> dict[str, Any]:
    return {
        "service": service,
        "original_text": original_text.strip(),
        "followups": [],
        "ask_user": ask_user,
    }


def append_pending_followup(pending: dict[str, Any], user_text: str) -> str:
    text = user_text.strip()
    if text:
        followups = pending.setdefault("followups", [])
        if isinstance(followups, list):
            followups.append(text)
        else:
            pending["followups"] = [text]
        pending["last_user_text"] = text
    return pending_prompt_text(pending)


def pending_prompt_text(pending: dict[str, Any]) -> str:
    original_text = str(pending.get("original_text") or "").strip()
    followups = [
        str(item).strip()
        for item in pending.get("followups") or []
        if str(item).strip()
    ]
    if not followups:
        return original_text

    followup_lines = "\n".join(f"- {item}" for item in followups)
    return f"{original_text}\n用户补充信息：\n{followup_lines}"
