from __future__ import annotations

import json

import httpx
import pytest

from app.clients.ollama import OllamaChatClient
from app.core.errors import APIError
from app.schemas.chat import ChatMessage


class _FakeStreamResponse:
    def __init__(self, status_code: int, events: list[object]) -> None:
        self.status_code = status_code
        self._events = events

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _ = exc_type, exc, tb
        return False

    def iter_lines(self):
        for event in self._events:
            if isinstance(event, Exception):
                raise event
            yield event


class _FakeClient:
    stream_calls: list[dict[str, object]] = []
    stream_responses: list[_FakeStreamResponse] = []

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _ = exc_type, exc, tb
        return False

    def stream(self, method: str, url: str, json: dict[str, object]):
        self.stream_calls.append(
            {
                "method": method,
                "url": url,
                "json": json,
            }
        )
        return self.stream_responses.pop(0)


def test_stream_chat_does_not_retry_after_yielding_first_chunk(monkeypatch) -> None:
    monkeypatch.setattr("app.clients.ollama.httpx.Client", _FakeClient)
    _FakeClient.stream_calls = []
    _FakeClient.stream_responses = [
        _FakeStreamResponse(
            200,
            [
                json.dumps(
                    {
                        "message": {"content": "hello "},
                        "done": False,
                    }
                ),
                httpx.ReadTimeout("timed out"),
            ],
        ),
        _FakeStreamResponse(
            200,
            [
                json.dumps(
                    {
                        "message": {"content": "hello "},
                        "done": False,
                    }
                ),
                json.dumps(
                    {
                        "message": {"content": "world"},
                        "done": True,
                    }
                ),
            ],
        ),
    ]

    client = OllamaChatClient(
        base_url="http://ollama.test",
        timeout_seconds=5.0,
        max_retries=1,
    )
    stream = client.stream_chat(
        model="assistant-fast",
        messages=[ChatMessage(role="user", content="hi")],
    )

    first = next(stream)

    assert first.content == "hello "
    assert first.done is False
    with pytest.raises(APIError) as exc_info:
        next(stream)

    assert exc_info.value.code == "dependency_timeout"
    assert len(_FakeClient.stream_calls) == 1
