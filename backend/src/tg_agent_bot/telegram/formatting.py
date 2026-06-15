
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace


TELEGRAM_TEXT_LIMIT = 4096


def telegram_safe_envelope_text(envelope) -> str:
    text = envelope.to_text()
    if len(text) <= TELEGRAM_TEXT_LIMIT:
        return text

    payload = deepcopy(envelope.payload)
    if payload.get("kind") == "weather.result":
        payload.pop("hours", None)
        payload["truncated"] = True
        payload["note"] = "Response was compacted to fit Telegram message length."
        source = payload.get("source")
        if isinstance(source, dict) and "forecast_url" in source:
            source["forecast_url"] = ""

    compact = replace(envelope, payload=payload)
    compact_text = compact.to_text()
    if len(compact_text) <= TELEGRAM_TEXT_LIMIT:
        return compact_text

    fallback_payload = {
        "kind": str(envelope.payload.get("kind", "result")),
        "service": str(envelope.payload.get("service", "")),
        "action": str(envelope.payload.get("action", "")),
        "ok": bool(envelope.payload.get("ok", False)),
        "truncated": True,
        "error": "Structured response was too long for one Telegram message.",
    }
    return replace(envelope, payload=fallback_payload).to_text()
