from __future__ import annotations

import httpx
import pytest

from tg_agent_bot.llm import (
    _chat_messages,
    _extract_response_text,
    _parse_response_payload,
    _responses_url,
)


def test_extract_response_text_prefers_output_text() -> None:
    assert _extract_response_text({"output_text": "hello"}) == "hello"


def test_extract_response_text_concatenates_nested_content_text() -> None:
    data = {
        "output": [
            {"content": [{"text": "hello "}, {"text": "world"}]},
            {"content": [{"type": "metadata"}, {"text": "!"}]},
        ]
    }

    assert _extract_response_text(data) == "hello world!"


def test_responses_url_appends_responses_once() -> None:
    assert _responses_url("https://api.example.test") == "https://api.example.test/responses"
    assert _responses_url("https://api.example.test/") == "https://api.example.test/responses"
    assert _responses_url("https://api.example.test/responses") == "https://api.example.test/responses"


def test_chat_messages_appends_user_text_after_history() -> None:
    messages = _chat_messages(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        "next",
    )

    assert messages == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "next"},
    ]


def test_parse_response_payload_reads_json_response() -> None:
    response = httpx.Response(200, json={"output_text": "ok"})

    assert _parse_response_payload(response) == {"output_text": "ok"}


def test_parse_response_payload_reads_streaming_deltas() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=(
            'data: {"type":"response.output_text.delta","delta":"hel"}\n\n'
            'data: {"type":"response.output_text.delta","delta":"lo"}\n\n'
            'data: {"type":"response.completed","response":{"id":"resp_1"}}\n\n'
            "data: [DONE]\n\n"
        ),
    )

    assert _parse_response_payload(response) == {"id": "resp_1", "output_text": "hello"}


def test_parse_response_payload_raises_on_streaming_failure() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text='data: {"type":"response.failed","response":{"error":{"message":"bad"}}}\n\n',
    )

    with pytest.raises(RuntimeError, match="streaming response failed"):
        _parse_response_payload(response)


def test_parse_response_payload_raises_when_stream_has_no_text() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text='data: {"type":"response.created"}\n\n',
    )

    with pytest.raises(RuntimeError, match="did not include output text"):
        _parse_response_payload(response)
