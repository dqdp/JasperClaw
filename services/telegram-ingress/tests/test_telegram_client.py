from __future__ import annotations

import pytest

from app.clients.telegram import TelegramClient, TelegramSendError


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: object,
        text: str = "ok",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses: list[object]) -> None:
        self.requests: list[tuple[str, str, object | None, object | None]] = []
        self._responses = responses

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: object | None = None,
        params: object | None = None,
    ) -> _FakeResponse:
        self.requests.append((method, url, json, params))
        response = self._responses.pop(0)
        return response


def test_set_webhook_calls_telegram_api_with_expected_payload() -> None:
    fake_http = _FakeAsyncClient(
        responses=[_FakeResponse(200, {"ok": True})]
    )
    client = TelegramClient(
        bot_token="bot-token",
        http_client=fake_http,
    )

    # Async method cannot be awaited in normal test without event loop helpers.
    import asyncio

    asyncio.run(
        client.set_webhook(
            url="https://example.com/telegram/webhook",
            secret_token="secret-token",
            drop_pending_updates=False,
            max_connections=40,
            allowed_updates=["message", "edited_channel_post"],
        )
    )

    method, url, payload, _ = fake_http.requests[0]
    assert method == "POST"
    assert url == "https://api.telegram.org/botbot-token/setWebhook"
    assert payload["url"] == "https://example.com/telegram/webhook"
    assert payload["secret_token"] == "secret-token"
    assert payload["drop_pending_updates"] is False
    assert payload["max_connections"] == 40
    assert payload["allowed_updates"] == ["message", "edited_channel_post"]


def test_set_webhook_rejects_non_ok_response() -> None:
    fake_http = _FakeAsyncClient(
        responses=[_FakeResponse(200, {"ok": False, "description": "invalid"})]
    )
    client = TelegramClient(
        bot_token="bot-token",
        http_client=fake_http,
    )

    import asyncio

    with pytest.raises(TelegramSendError):
        asyncio.run(
            client.set_webhook(
                url="https://example.com/telegram/webhook",
                secret_token="secret-token",
            )
        )


def test_get_updates_filters_to_dict_payloads_and_extracts_result() -> None:
    fake_http = _FakeAsyncClient(
        responses=[
            _FakeResponse(
                200,
                {
                    "ok": True,
                    "result": [
                        {"update_id": 1, "message": {"chat": {"id": 1}, "text": "hi"}},
                        "not-a-dict",
                        {"update_id": 2, "message": {"chat": {"id": 2}, "text": "yo"}},
                    ],
                },
            )
        ]
    )
    client = TelegramClient(
        bot_token="bot-token",
        http_client=fake_http,
    )

    import asyncio

    updates = asyncio.run(client.get_updates(timeout=5, limit=10))
    assert updates == [
        {"update_id": 1, "message": {"chat": {"id": 1}, "text": "hi"}},
        {"update_id": 2, "message": {"chat": {"id": 2}, "text": "yo"}},
    ]
    assert fake_http.requests[0][0] == "GET"
    assert fake_http.requests[0][3] == {"timeout": 5, "limit": 10}


def test_send_message_surfaces_http_status_code_for_retry_classification() -> None:
    fake_http = _FakeAsyncClient(
        responses=[_FakeResponse(503, {"ok": False}, text="temporary failure")]
    )
    client = TelegramClient(
        bot_token="bot-token",
        http_client=fake_http,
    )

    import asyncio

    with pytest.raises(TelegramSendError) as excinfo:
        asyncio.run(client.send_message(chat_id=11, text="hello"))

    assert excinfo.value.status_code == 503
