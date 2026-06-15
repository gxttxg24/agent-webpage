from __future__ import annotations

import json

import pytest

from tg_agent_bot.b2b.protocol import (
    ACK,
    PROTOCOL,
    REQUEST,
    VERSION,
    B2BEnvelope,
    B2BProtocolError,
    make_request,
    make_response,
    normalize_username,
    parse_envelope,
    should_ack,
    username_matches,
)


def test_username_normalization_and_matching() -> None:
    assert normalize_username("CalendarBot") == "@CalendarBot"
    assert normalize_username("@CalendarBot") == "@CalendarBot"
    assert username_matches("@CalendarBot", "calendarbot")


def test_request_round_trip() -> None:
    message = make_request("BotC", "@BotA", "hello")

    parsed = parse_envelope(message.to_text())

    assert parsed is not None
    assert parsed.message_type == REQUEST
    assert parsed.source == "@BotC"
    assert parsed.target == "@BotA"
    assert parsed.conversation_id == parsed.id
    assert parsed.correlation_id is None
    assert parsed.payload == {"kind": "hello", "text": "hello"}


def test_response_correlates_to_request() -> None:
    request = make_request("@BotC", "@BotA", "hello")

    response = make_response("@BotA", request, {"kind": "calendar.result", "ok": True})

    assert response.message_type == ACK
    assert response.target == "@BotC"
    assert response.conversation_id == request.conversation_id
    assert response.correlation_id == request.id
    assert response.depth == request.depth + 1


def test_parse_envelope_ignores_non_protocol_text() -> None:
    assert parse_envelope("plain user text") is None
    assert parse_envelope("{not valid json") is None
    assert parse_envelope(json.dumps({"hello": "world"})) is None


@pytest.mark.parametrize(
    "patch",
    [
        {"version": VERSION + 1},
        {"type": "unknown"},
        {"id": ""},
        {"depth": -1},
        {"payload": "not an object"},
    ],
)
def test_parse_envelope_rejects_invalid_protocol_fields(patch: dict[str, object]) -> None:
    raw = {
        "protocol": PROTOCOL,
        "version": VERSION,
        "id": "message-id",
        "type": REQUEST,
        "source": "@BotC",
        "target": "@BotA",
        "conversation_id": "conversation-id",
        "depth": 0,
        "max_depth": 1,
        "payload": {"kind": "hello"},
    }
    raw.update(patch)

    with pytest.raises(B2BProtocolError):
        parse_envelope(json.dumps(raw))


def test_should_ack_only_for_unseen_matching_request_with_remaining_depth() -> None:
    envelope = B2BEnvelope(
        id="request-id",
        message_type=REQUEST,
        source="@BotC",
        target="@BotA",
        conversation_id="conversation-id",
        payload={"kind": "hello"},
        depth=0,
        max_depth=1,
    )

    assert should_ack(envelope, set(), "@BotA")
    assert not should_ack(envelope, {"request-id"}, "@BotA")
    assert not should_ack(envelope, set(), "@OtherBot")
    assert not should_ack(
        B2BEnvelope(
            id="ack-id",
            message_type=ACK,
            source="@BotA",
            target="@BotC",
            conversation_id="conversation-id",
            payload={"kind": "ack"},
        ),
        set(),
        "@BotC",
    )
    assert not should_ack(
        B2BEnvelope(
            id="request-id",
            message_type=REQUEST,
            source="@BotC",
            target="@BotA",
            conversation_id="conversation-id",
            payload={"kind": "hello"},
            depth=1,
            max_depth=1,
        ),
        set(),
        "@BotA",
    )
