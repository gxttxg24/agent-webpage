from __future__ import annotations

import json

from tg_agent_bot.b2b.protocol import B2BEnvelope
from tg_agent_bot.telegram.formatting import TELEGRAM_TEXT_LIMIT, telegram_safe_envelope_text


def envelope_with_payload(payload: dict) -> B2BEnvelope:
    return B2BEnvelope(
        id="message-id",
        message_type="ack",
        source="@WeatherBot",
        target="@OrchestratorBot",
        conversation_id="conversation-id",
        correlation_id="request-id",
        payload=payload,
    )


def test_short_envelope_is_returned_unchanged() -> None:
    envelope = envelope_with_payload({"kind": "ack", "ok": True})

    assert telegram_safe_envelope_text(envelope) == envelope.to_text()


def test_long_weather_result_is_compacted_by_removing_hours_and_source_url() -> None:
    envelope = envelope_with_payload(
        {
            "kind": "weather.result",
            "service": "weather",
            "action": "hourly_forecast",
            "ok": True,
            "hours": [{"time": f"2099-06-10T{hour:02d}:00", "text": "x" * 500} for hour in range(24)],
            "periods": [{"starts_at": "2099-06-10T00:00", "weather": "clear"}],
            "source": {"forecast_url": "https://example.test/" + "x" * 3000},
        }
    )

    text = telegram_safe_envelope_text(envelope)
    payload = json.loads(text)["payload"]

    assert len(text) <= TELEGRAM_TEXT_LIMIT
    assert "hours" not in payload
    assert payload["truncated"] is True
    assert payload["source"]["forecast_url"] == ""


def test_uncompactable_envelope_falls_back_to_minimal_payload() -> None:
    envelope = envelope_with_payload(
        {
            "kind": "calendar.result",
            "service": "calendar",
            "action": "list_events",
            "ok": True,
            "events": [{"title": "x" * 5000}],
        }
    )

    text = telegram_safe_envelope_text(envelope)
    payload = json.loads(text)["payload"]

    assert len(text) <= TELEGRAM_TEXT_LIMIT
    assert payload == {
        "kind": "calendar.result",
        "service": "calendar",
        "action": "list_events",
        "ok": True,
        "truncated": True,
        "error": "Structured response was too long for one Telegram message.",
    }
