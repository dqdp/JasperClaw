from __future__ import annotations

import asyncio

from app.clients.agent_api import AgentApiClient


class _FakeResponse:
    def __init__(self, status_code: int, payload: object, text: str = "ok") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses: list[object]) -> None:
        self.requests: list[tuple[str, str, dict[str, str], object | None]] = []
        self._responses = responses

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None = None,
    ) -> _FakeResponse:
        self.requests.append((method, url, headers, json))
        return self._responses.pop(0)


def test_complete_uses_request_id_header_and_client_conversation_metadata() -> None:
    fake_http = _FakeAsyncClient(
        responses=[
            _FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "ok",
                            }
                        }
                    ]
                },
            )
        ]
    )
    client = AgentApiClient(
        base_url="http://agent-api:8080",
        api_key="agent-token",
        http_client=fake_http,
    )

    reply = asyncio.run(
        client.complete(
            model="assistant-fast",
            text="Reply with ok.",
            conversation_id="telegram:42",
            request_id="req_123",
        )
    )

    assert reply == "ok"
    method, url, headers, payload = fake_http.requests[0]
    assert method == "POST"
    assert url == "http://agent-api:8080/v1/chat/completions"
    assert headers["Authorization"] == "Bearer agent-token"
    assert headers["X-Request-ID"] == "req_123"
    assert "X-Conversation-ID" not in headers
    assert payload == {
        "model": "assistant-fast",
        "messages": [{"role": "user", "content": "Reply with ok."}],
        "metadata": {
            "source": "telegram",
            "client_conversation_id": "telegram:42",
        },
    }


def test_describe_capabilities_uses_request_id_header() -> None:
    fake_http = _FakeAsyncClient(
        responses=[
            _FakeResponse(
                200,
                {
                    "help_text": "help text",
                    "status_text": "status text",
                },
            )
        ]
    )
    client = AgentApiClient(
        base_url="http://agent-api:8080",
        api_key="agent-token",
        http_client=fake_http,
    )

    discovery = asyncio.run(
        client.describe_capabilities(
            request_id="req_456",
        )
    )

    assert discovery.help_text == "help text"
    assert discovery.status_text == "status text"
    method, url, headers, payload = fake_http.requests[0]
    assert method == "GET"
    assert url == "http://agent-api:8080/v1/capabilities/discovery"
    assert headers["Authorization"] == "Bearer agent-token"
    assert headers["X-Request-ID"] == "req_456"
    assert payload is None
