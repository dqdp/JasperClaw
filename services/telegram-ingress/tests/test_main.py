from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clients.agent_api import AgentApiClient, AgentApiError
from app.clients.telegram import TelegramClient
from app.core.config import Settings
from app.main import create_app
from app.services.bridge import TelegramBridgeService


def _events(caplog) -> list[dict[str, object]]:
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "telegram_ingress"
    ]


class _FakeTelegramClient(TelegramClient):
    def __init__(self) -> None:
        self.sent_messages: list[tuple[int, str]] = []
        self.closed = False

    async def send_message(self, *, chat_id: int, text: str) -> None:
        self.sent_messages.append((chat_id, text))

    async def close(self) -> None:
        self.closed = True


class _StartupTelegramClient(TelegramClient):
    def __init__(
        self,
        *,
        bot_token: str,
        api_base_url: str = "https://api.telegram.org",
        timeout_seconds: float = 5.0,
        http_client: object | None = None,
    ) -> None:
        super().__init__(
            bot_token=bot_token,
            api_base_url=api_base_url,
            timeout_seconds=timeout_seconds,
            http_client=http_client,
        )
        self.webhook_calls: list[dict[str, Any]] = []
        self.get_updates_calls: list[dict[str, Any]] = []
        self.closed = False

    async def set_webhook(
        self,
        *,
        url: str,
        secret_token: str | None = None,
        drop_pending_updates: bool = True,
        max_connections: int | None = None,
        allowed_updates: list[str] | None = None,
    ) -> None:
        self.webhook_calls.append(
            {
                "url": url,
                "secret_token": secret_token,
                "drop_pending_updates": drop_pending_updates,
                "max_connections": max_connections,
                "allowed_updates": allowed_updates,
            }
        )

    async def get_updates(
        self,
        *,
        timeout: int,
        offset: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        self.get_updates_calls.append(
            {
                "timeout": timeout,
                "offset": offset,
                "limit": limit,
            }
        )
        return []

    async def close(self) -> None:
        self.closed = True


class _FakeAgentApiClient(AgentApiClient):
    def __init__(self, reply_text: str = "ok") -> None:
        self.calls: list[dict[str, str]] = []
        self.closed = False
        self.reply_text = reply_text

    async def complete(
        self,
        *,
        model: str,
        text: str,
        conversation_id: str,
        request_id: str,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "text": text,
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
        )
        return self.reply_text

    async def close(self) -> None:
        self.closed = True


class _FailingAgentApiClient(AgentApiClient):
    def __init__(
        self,
        *,
        base_url: str = "",
        api_key: str = "",
        timeout_seconds: float = 5.0,
        http_client: object | None = None,
    ) -> None:
        _ = base_url, api_key, timeout_seconds, http_client
        self.calls: list[dict[str, str]] = []
        self.closed = False

    async def complete(
        self,
        *,
        model: str,
        text: str,
        conversation_id: str,
        request_id: str,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "text": text,
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
        )
        raise AgentApiError("agent-api unavailable")

    async def close(self) -> None:
        self.closed = True


class _StartupAlertTelegramClient(TelegramClient):
    def __init__(
        self,
        *,
        bot_token: str,
        api_base_url: str = "https://api.telegram.org",
        timeout_seconds: float = 5.0,
        http_client: object | None = None,
    ) -> None:
        super().__init__(
            bot_token=bot_token,
            api_base_url=api_base_url,
            timeout_seconds=timeout_seconds,
            http_client=http_client,
        )
        self.bot_token = bot_token
        self.api_base_url = api_base_url
        self.timeout_seconds = timeout_seconds
        self.sent_messages: list[tuple[int, str]] = []
        self.closed = False

    async def send_message(self, *, chat_id: int, text: str) -> None:
        self.sent_messages.append((chat_id, text))

    async def close(self) -> None:
        self.closed = True


def _create_client(
    *,
    settings: Settings | None = None,
    telegram_client: _FakeTelegramClient | None = None,
    agent_client: _FakeAgentApiClient | None = None,
) -> tuple[TestClient, _FakeTelegramClient, _FakeAgentApiClient]:
    settings = settings or _operational_settings({})
    telegram_client = telegram_client or _FakeTelegramClient()
    agent_client = agent_client or _FakeAgentApiClient()

    app = create_app(
        settings=settings,
        bridge_service=TelegramBridgeService(
            agent_client=agent_client,
            telegram_client=telegram_client,
            settings=settings,
        ),
    )
    return TestClient(app), telegram_client, agent_client


def _operational_settings(overrides: dict[str, object] | None = None) -> Settings:
    base: dict[str, object] = {
        "telegram_bot_token": "bot-token",
        "agent_api_key": "agent-token",
        "webhook_path": "/webhook",
    }
    if overrides:
        base.update(overrides)
    return Settings(**base)


def test_webhook_rejects_when_ingress_not_configured() -> None:
    settings = Settings()
    app = create_app(
        settings=settings,
        bridge_service=TelegramBridgeService(
            agent_client=_FakeAgentApiClient(),
            telegram_client=_FakeTelegramClient(),
            settings=settings,
        ),
    )
    client = TestClient(app)
    response = client.post(
        "/webhook",
        json={"update_id": 500, "message": {"message_id": 1, "chat": {"id": 1}, "text": "hi"}},
    )
    assert response.status_code == 503


def test_webhook_rejects_wrong_secret() -> None:
    settings = _operational_settings({"telegram_webhook_secret_token": "secret"})
    app = create_app(
        settings=settings,
        bridge_service=TelegramBridgeService(
            agent_client=_FakeAgentApiClient(),
            telegram_client=_FakeTelegramClient(),
            settings=settings,
        ),
    )
    client = TestClient(app)
    response = client.post(
        settings.webhook_path,
        json={"update_id": 1, "message": {"message_id": 1, "chat": {"id": 100}, "text": "hi"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert response.status_code == 401


def test_webhook_processes_text_update() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(settings=settings)
    response = client.post(
        "/webhook",
        json={
            "update_id": 100,
            "message": {"message_id": 1, "chat": {"id": 42}, "text": "привет"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["chat_id"] == 42
    assert data["message_id"] == 1
    assert data["update_id"] == 100
    assert data["conversation_id"] == "telegram:42"
    assert agent_client.calls == [
        {
            "model": "assistant-fast",
            "text": "привет",
            "conversation_id": "telegram:42",
            "request_id": response.headers["X-Request-ID"],
        },
    ]
    assert telegram_client.sent_messages == [(42, "ok")]


def test_webhook_propagates_request_id_and_logs_update_context(caplog) -> None:
    settings = _operational_settings({})
    client, _, agent_client = _create_client(settings=settings)

    with caplog.at_level(logging.INFO, logger="telegram_ingress"):
        response = client.post(
            "/webhook",
            headers={"X-Request-ID": "req_telegram_obs"},
            json={
                "update_id": 102,
                "message": {"message_id": 7, "chat": {"id": 99}, "text": "status?"},
            },
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req_telegram_obs"
    assert agent_client.calls == [
        {
            "model": "assistant-fast",
            "text": "status?",
            "conversation_id": "telegram:99",
            "request_id": "req_telegram_obs",
        }
    ]

    events = _events(caplog)
    request_started = next(event for event in events if event["event"] == "request_started")
    assert request_started["request_id"] == "req_telegram_obs"

    update_received = next(
        event for event in events if event["event"] == "telegram_update_received"
    )
    assert update_received["request_id"] == "req_telegram_obs"
    assert update_received["update_id"] == 102
    assert update_received["chat_id"] == 99
    assert update_received["message_id"] == 7
    assert update_received["conversation_id"] == "telegram:99"

    update_completed = next(
        event for event in events if event["event"] == "telegram_update_completed"
    )
    assert update_completed["request_id"] == "req_telegram_obs"
    assert update_completed["outcome"] == "processed"
    assert update_completed["update_id"] == 102
    assert update_completed["chat_id"] == 99
    assert update_completed["message_id"] == 7
    assert update_completed["conversation_id"] == "telegram:99"

    request_completed = next(
        event for event in events if event["event"] == "request_completed"
    )
    assert request_completed["request_id"] == "req_telegram_obs"
    assert request_completed["status_code"] == 200


def test_webhook_generates_request_id_when_missing(caplog) -> None:
    settings = _operational_settings({})
    client, _, agent_client = _create_client(settings=settings)

    with caplog.at_level(logging.INFO, logger="telegram_ingress"):
        response = client.post(
            "/webhook",
            json={
                "update_id": 103,
                "message": {"message_id": 8, "chat": {"id": 77}, "text": "hello"},
            },
        )

    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 200
    assert request_id.startswith("req_")
    assert agent_client.calls[0]["request_id"] == request_id

    update_completed = next(
        event
        for event in _events(caplog)
        if event["event"] == "telegram_update_completed"
    )
    assert update_completed["request_id"] == request_id


def test_webhook_returns_503_when_agent_api_fails() -> None:
    settings = _operational_settings({})
    app = create_app(
        settings=settings,
        bridge_service=TelegramBridgeService(
            agent_client=_FailingAgentApiClient(),
            telegram_client=_FakeTelegramClient(),
            settings=settings,
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/webhook",
        json={
            "update_id": 101,
            "message": {"message_id": 2, "chat": {"id": 42}, "text": "привет"},
        },
    )

    assert response.status_code == 503


def test_webhook_logs_retryable_failure_with_request_context(caplog) -> None:
    settings = _operational_settings({})
    app = create_app(
        settings=settings,
        bridge_service=TelegramBridgeService(
            agent_client=_FailingAgentApiClient(),
            telegram_client=_FakeTelegramClient(),
            settings=settings,
        ),
    )
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="telegram_ingress"):
        response = client.post(
            "/webhook",
            headers={"X-Request-ID": "req_retryable"},
            json={
                "update_id": 104,
                "message": {"message_id": 9, "chat": {"id": 55}, "text": "retry me"},
            },
        )

    assert response.status_code == 503
    assert response.headers["X-Request-ID"] == "req_retryable"

    events = _events(caplog)
    update_failed = next(
        event for event in events if event["event"] == "telegram_update_failed"
    )
    assert update_failed["request_id"] == "req_retryable"
    assert update_failed["outcome"] == "retryable_error"
    assert update_failed["update_id"] == 104
    assert update_failed["chat_id"] == 55
    assert update_failed["message_id"] == 9
    assert update_failed["conversation_id"] == "telegram:55"

    request_failed = next(event for event in events if event["event"] == "request_failed")
    assert request_failed["request_id"] == "req_retryable"
    assert request_failed["status_code"] == 503


def test_webhook_rejects_unknown_command_when_command_allowlist_is_enabled() -> None:
    settings = _operational_settings({"telegram_allowed_commands": ("/help", "/status")})
    client, telegram_client, agent_client = _create_client(settings=settings)
    response = client.post(
        "/webhook",
        json={
            "update_id": 600,
            "message": {"message_id": 7, "chat": {"id": 77}, "text": "/delete all data"},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "command_not_allowed"
    assert not telegram_client.sent_messages
    assert not agent_client.calls


def test_webhook_help_command_returns_local_response_without_agent_call() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(settings=settings)
    response = client.post(
        "/webhook",
        json={
            "update_id": 601,
            "message": {
                "message_id": 8,
                "chat": {"id": 77},
                "text": "/help",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["chat_id"] == 77
    assert data["message_id"] == 8
    assert data["update_id"] == 601
    assert not agent_client.calls
    assert telegram_client.sent_messages == [
        (77, "Available commands: /help, /status, /ask <message>")
    ]


def test_webhook_status_command_returns_local_response_without_agent_call() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(settings=settings)
    response = client.post(
        "/webhook",
        json={
            "update_id": 602,
            "message": {
                "message_id": 9,
                "chat": {"id": 77},
                "text": "/status",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["chat_id"] == 77
    assert data["message_id"] == 9
    assert data["update_id"] == 602
    assert not agent_client.calls
    assert telegram_client.sent_messages == [(77, "telegram-ingress ok")]


def test_webhook_status_command_with_bot_username_returns_local_response() -> None:
    settings = _operational_settings({"telegram_allowed_commands": ("/status",)})
    client, telegram_client, agent_client = _create_client(settings=settings)
    response = client.post(
        "/webhook",
        json={
            "update_id": 603,
            "message": {
                "message_id": 10,
                "chat": {"id": 77},
                "text": "/status@acme_bot now",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert not agent_client.calls
    assert telegram_client.sent_messages == [(77, "telegram-ingress ok")]


def test_webhook_ask_command_forwards_stripped_text_to_agent_api() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(settings=settings)
    response = client.post(
        "/webhook",
        json={
            "update_id": 604,
            "message": {
                "message_id": 11,
                "chat": {"id": 77},
                "text": "/ask   what is the status?  ",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert agent_client.calls == [
        {
            "model": "assistant-fast",
            "text": "what is the status?",
            "conversation_id": "telegram:77",
            "request_id": response.headers["X-Request-ID"],
        }
    ]
    assert telegram_client.sent_messages == [(77, "ok")]


def test_webhook_ask_command_without_body_returns_usage_and_skips_agent_api() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(settings=settings)
    response = client.post(
        "/webhook",
        json={
            "update_id": 605,
            "message": {
                "message_id": 12,
                "chat": {"id": 77},
                "text": "/ask",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert not agent_client.calls
    assert telegram_client.sent_messages == [(77, "Usage: /ask <message>")]


def test_webhook_ignores_duplicate_update() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(settings=settings)
    payload = {
        "update_id": 200,
        "message": {"message_id": 3, "chat": {"id": 77}, "text": "loop"},
    }
    first = client.post("/webhook", json=payload)
    second = client.post("/webhook", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "processed"
    assert second.json()["status"] == "ignored"
    assert second.json()["reason"] == "duplicate_update"
    assert len(telegram_client.sent_messages) == 1
    assert len(agent_client.calls) == 1


def test_webhook_ignores_non_text_updates() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(settings=settings)
    response = client.post(
        "/webhook",
        json={
            "update_id": 300,
            "message": {
                "message_id": 4,
                "chat": {"id": 90},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "message not text or missing chat"
    assert not telegram_client.sent_messages
    assert not agent_client.calls


def test_webhook_ignores_messages_from_other_bots() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(settings=settings)
    response = client.post(
        "/webhook",
        json={
            "update_id": 400,
            "message": {
                "message_id": 5,
                "chat": {"id": 91},
                "text": "bot message",
                "from": {"id": 1, "is_bot": True},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "message not text or missing chat"
    assert not telegram_client.sent_messages
    assert not agent_client.calls


def test_alerts_endpoint_returns_503_when_alerting_is_not_configured() -> None:
    settings = _operational_settings({})
    client = TestClient(
        create_app(
            settings=settings,
            bridge_service=TelegramBridgeService(
                agent_client=_FakeAgentApiClient(),
                telegram_client=_FakeTelegramClient(),
                settings=settings,
            ),
        )
    )
    response = client.post("/telegram/alerts", json={"text": "downtime"})
    assert response.status_code == 503


def test_alerts_endpoint_requires_auth_token_when_configured() -> None:
    from app import main as main_module

    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
        }
    )
    captured: list[_StartupAlertTelegramClient] = []

    class _PatchedTelegramClient(_StartupAlertTelegramClient):
        def __init__(
            self,
            *,
            bot_token: str,
            api_base_url: str = "https://api.telegram.org",
            timeout_seconds: float = 5.0,
            http_client: object | None = None,
        ) -> None:
            super().__init__(
                bot_token=bot_token,
                api_base_url=api_base_url,
                timeout_seconds=timeout_seconds,
                http_client=http_client,
            )
            captured.append(self)

    original_client = main_module.TelegramClient
    main_module.TelegramClient = _PatchedTelegramClient
    try:
        app = main_module.create_app(settings=settings)
        with TestClient(app) as alert_client:
            response = alert_client.post(
                "/telegram/alerts",
                json={"text": "downtime"},
                headers={"X-Telegram-Alert-Token": "wrong"},
            )
    finally:
        main_module.TelegramClient = original_client

    assert response.status_code == 401
    assert captured[0].sent_messages == []


def test_alerts_endpoint_sends_to_all_configured_chats() -> None:
    from app import main as main_module

    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11, 22),
        }
    )
    captured: list[_StartupAlertTelegramClient] = []

    class _PatchedTelegramClient(_StartupAlertTelegramClient):
        def __init__(
            self,
            *,
            bot_token: str,
            api_base_url: str = "https://api.telegram.org",
            timeout_seconds: float = 5.0,
            http_client: object | None = None,
        ) -> None:
            super().__init__(
                bot_token=bot_token,
                api_base_url=api_base_url,
                timeout_seconds=timeout_seconds,
                http_client=http_client,
            )
            captured.append(self)

    original_client = main_module.TelegramClient
    main_module.TelegramClient = _PatchedTelegramClient
    try:
        app = main_module.create_app(settings=settings)
        with TestClient(app) as alert_client:
            response = alert_client.post(
                "/telegram/alerts",
                json={"text": "downtime"},
                headers={"X-Telegram-Alert-Token": "alert-secret"},
            )
    finally:
        main_module.TelegramClient = original_client

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert response.json()["recipients"] == 2

    alert_client = next(
        client for client in captured if client.bot_token == "alert-bot-token"
    )
    assert alert_client.sent_messages == [(11, "downtime"), (22, "downtime")]


def test_alerts_endpoint_formats_alert_payload() -> None:
    from app import main as main_module

    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
        }
    )
    captured: list[_StartupAlertTelegramClient] = []

    class _PatchedTelegramClient(_StartupAlertTelegramClient):
        def __init__(
            self,
            *,
            bot_token: str,
            api_base_url: str = "https://api.telegram.org",
            timeout_seconds: float = 5.0,
            http_client: object | None = None,
        ) -> None:
            super().__init__(
                bot_token=bot_token,
                api_base_url=api_base_url,
                timeout_seconds=timeout_seconds,
                http_client=http_client,
            )
            captured.append(self)

    original_client = main_module.TelegramClient
    main_module.TelegramClient = _PatchedTelegramClient
    try:
        app = main_module.create_app(settings=settings)
        with TestClient(app) as alert_client:
            response = alert_client.post(
                "/telegram/alerts",
                json={
                    "status": "firing",
                    "alerts": [
                        {
                            "status": "firing",
                            "labels": {
                                "alertname": "high_cpu",
                                "severity": "critical",
                                "service": "agent-api",
                            },
                            "annotations": {
                                "summary": "CPU usage too high",
                                "description": "CPU usage exceeded 90% for 5m",
                            },
                        }
                    ],
                },
                headers={"X-Telegram-Alert-Token": "alert-secret"},
            )
    finally:
        main_module.TelegramClient = original_client

    assert response.status_code == 200
    alert_client = next(
        client for client in captured if client.bot_token == "alert-bot-token"
    )
    assert alert_client.sent_messages
    text = alert_client.sent_messages[0][1]
    assert text == "FIRING high_cpu [critical] on agent-api: CPU usage exceeded 90% for 5m"
    assert response.json()["status"] == "sent"


def test_webhook_ignores_messages_that_exceed_input_limit() -> None:
    settings = _operational_settings({"telegram_max_input_chars": 4})
    client, telegram_client, agent_client = _create_client(settings=settings)
    response = client.post(
        "/webhook",
        json={
            "update_id": 500,
            "message": {"message_id": 6, "chat": {"id": 88}, "text": "toolong"},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "input_too_large"
    assert not telegram_client.sent_messages
    assert not agent_client.calls


def test_webhook_applies_per_chat_rate_limits() -> None:
    settings = _operational_settings(
        {
            "telegram_rate_limit_per_chat": 2,
            "telegram_rate_limit_global": 1000,
            "rate_limit_window_seconds": 60.0,
        }
    )
    client, telegram_client, agent_client = _create_client(settings=settings)
    base_payload = {
        "message": {"message_id": 1, "chat": {"id": 123}, "text": "hi"},
    }
    first = client.post("/webhook", json={**base_payload, "update_id": 1000, "message_id": 1})
    second = client.post("/webhook", json={**base_payload, "update_id": 1001, "message": {"message_id": 2, "chat": {"id": 123}, "text": "hi"}})
    third = client.post("/webhook", json={**base_payload, "update_id": 1002, "message": {"message_id": 3, "chat": {"id": 123}, "text": "hi"}})
    assert first.json()["status"] == "processed"
    assert second.json()["status"] == "processed"
    assert third.json()["status"] == "ignored"
    assert third.json()["reason"] == "rate_limited_chat"
    assert len(agent_client.calls) == 2
    assert len(telegram_client.sent_messages) == 2


def test_webhook_applies_global_rate_limits() -> None:
    settings = _operational_settings(
        {
            "telegram_rate_limit_per_chat": 1000,
            "telegram_rate_limit_global": 2,
            "rate_limit_window_seconds": 60.0,
        }
    )
    client, telegram_client, agent_client = _create_client(settings=settings)
    responses = [
        client.post("/webhook", json={"update_id": 2000, "message": {"message_id": 10, "chat": {"id": 10}, "text": "x"}}),
        client.post("/webhook", json={"update_id": 2001, "message": {"message_id": 20, "chat": {"id": 20}, "text": "x"}}),
        client.post("/webhook", json={"update_id": 2002, "message": {"message_id": 30, "chat": {"id": 30}, "text": "x"}}),
    ]
    assert responses[0].json()["status"] == "processed"
    assert responses[1].json()["status"] == "processed"
    assert responses[2].json()["status"] == "ignored"
    assert responses[2].json()["reason"] == "rate_limited_global"
    assert len(agent_client.calls) == 2
    assert len(telegram_client.sent_messages) == 2


def test_webhook_releases_http_clients_on_shutdown() -> None:
    settings = _operational_settings({})
    telegram_client = _FakeTelegramClient()
    agent_client = _FakeAgentApiClient()
    app = create_app(
        settings=settings,
        bridge_service=TelegramBridgeService(
            agent_client=agent_client,
            telegram_client=telegram_client,
            settings=settings,
        ),
    )
    with TestClient(app):
        pass

    assert telegram_client.closed is True
    assert agent_client.closed is True


def test_webhook_configuration_registers_webhook_on_startup(monkeypatch) -> None:
    from app import main as main_module

    calls: list[dict[str, Any]] = []

    class _PatchedTelegramClient(_StartupTelegramClient):
        async def set_webhook(
            self,
            *,
            url: str,
            secret_token: str | None = None,
            drop_pending_updates: bool = True,
            max_connections: int | None = None,
            allowed_updates: list[str] | None = None,
        ) -> None:
            calls.append(
                {
                    "url": url,
                    "secret_token": secret_token,
                    "drop_pending_updates": drop_pending_updates,
                    "max_connections": max_connections,
                    "allowed_updates": allowed_updates,
                }
            )

    monkeypatch.setattr(main_module, "TelegramClient", _PatchedTelegramClient)

    settings = _operational_settings(
        {
            "telegram_webhook_url": "https://example.com/telegram/webhook",
            "telegram_webhook_secret_token": "secret",
            "webhook_path": "/telegram/webhook",
        }
    )
    app = main_module.create_app(settings=settings)
    with TestClient(app):
        pass

    assert calls == [
        {
            "url": "https://example.com/telegram/webhook",
            "secret_token": "secret",
            "drop_pending_updates": True,
            "max_connections": None,
            "allowed_updates": None,
        }
    ]


def test_webhook_configuration_requires_secret_token(monkeypatch) -> None:
    from app import main as main_module

    monkeypatch.setattr(main_module, "TelegramClient", _StartupTelegramClient)

    settings = _operational_settings(
        {
            "telegram_webhook_url": "https://example.com/telegram/webhook",
            "telegram_webhook_secret_token": "",
            "webhook_path": "/telegram/webhook",
        }
    )
    app = main_module.create_app(settings=settings)

    with pytest.raises(RuntimeError, match="TELEGRAM_WEBHOOK_SECRET_TOKEN"):
        with TestClient(app):
            pass


def test_polling_enabled_starts_background_task(monkeypatch) -> None:
    from app import main as main_module

    captured: list[_StartupTelegramClient] = []

    class _PatchedTelegramClient(_StartupTelegramClient):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            captured.append(self)

    monkeypatch.setattr(main_module, "TelegramClient", _PatchedTelegramClient)

    settings = _operational_settings(
        {
            "telegram_polling_enabled": True,
            "telegram_webhook_url": "",
        }
    )
    app = main_module.create_app(settings=settings)
    with TestClient(app):
        assert app.state.telegram_polling_task is not None
        assert not app.state.telegram_polling_task.done()

    assert app.state.telegram_polling_task.done()

    assert captured and captured[0].closed


def test_polling_keeps_offset_when_bridge_processing_fails(monkeypatch) -> None:
    from app import main as main_module

    captured: list[_StartupTelegramClient] = []
    original_sleep = asyncio.sleep

    class _PatchedTelegramClient(_StartupTelegramClient):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            captured.append(self)

        async def get_updates(
            self,
            *,
            timeout: int,
            offset: int | None = None,
            limit: int = 100,
        ) -> list[dict[str, object]]:
            self.get_updates_calls.append(
                {
                    "timeout": timeout,
                    "offset": offset,
                    "limit": limit,
                }
            )
            return [
                {
                    "update_id": 10,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 22},
                        "text": "retry me",
                    },
                }
            ]

    async def _fast_sleep(_: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr(main_module, "TelegramClient", _PatchedTelegramClient)
    monkeypatch.setattr(main_module, "AgentApiClient", _FailingAgentApiClient)
    monkeypatch.setattr(main_module.asyncio, "sleep", _fast_sleep)

    settings = _operational_settings(
        {
            "telegram_polling_enabled": True,
            "telegram_webhook_url": "",
        }
    )
    app = main_module.create_app(settings=settings)
    with TestClient(app):
        deadline = time.time() + 1.0
        while (
            (not captured or len(captured[0].get_updates_calls) < 2)
            and time.time() < deadline
        ):
            time.sleep(0.01)

    assert captured
    assert captured[0].get_updates_calls[0]["offset"] is None
    assert captured[0].get_updates_calls[1]["offset"] == 10


def test_polling_generates_request_id_and_logs_update_context(monkeypatch, caplog) -> None:
    from app import main as main_module

    captured: list[_StartupTelegramClient] = []
    agent_calls: list[dict[str, str]] = []
    original_sleep = asyncio.sleep

    class _PatchedTelegramClient(_StartupTelegramClient):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            captured.append(self)
            self._delivered = False
            self.sent_messages: list[tuple[int, str]] = []

        async def get_updates(
            self,
            *,
            timeout: int,
            offset: int | None = None,
            limit: int = 100,
        ) -> list[dict[str, object]]:
            self.get_updates_calls.append(
                {
                    "timeout": timeout,
                    "offset": offset,
                    "limit": limit,
                }
            )
            if self._delivered:
                return []
            self._delivered = True
            return [
                {
                    "update_id": 12,
                    "message": {
                        "message_id": 2,
                        "chat": {"id": 44},
                        "text": "poll me",
                    },
                }
            ]

        async def send_message(self, *, chat_id: int, text: str) -> None:
            self.sent_messages.append((chat_id, text))

    class _PatchedAgentApiClient(AgentApiClient):
        def __init__(
            self,
            *,
            base_url: str,
            api_key: str,
            timeout_seconds: float = 5.0,
            http_client: object | None = None,
        ) -> None:
            _ = base_url, api_key, timeout_seconds, http_client

        async def complete(
            self,
            *,
            model: str,
            text: str,
            conversation_id: str,
            request_id: str,
        ) -> str:
            agent_calls.append(
                {
                    "model": model,
                    "text": text,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                }
            )
            return "ok"

        async def close(self) -> None:
            return None

    async def _fast_sleep(_: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr(main_module, "TelegramClient", _PatchedTelegramClient)
    monkeypatch.setattr(main_module, "AgentApiClient", _PatchedAgentApiClient)
    monkeypatch.setattr(main_module.asyncio, "sleep", _fast_sleep)

    settings = _operational_settings(
        {
            "telegram_polling_enabled": True,
            "telegram_webhook_url": "",
        }
    )
    app = main_module.create_app(settings=settings)

    with caplog.at_level(logging.INFO, logger="telegram_ingress"):
        with TestClient(app):
            deadline = time.time() + 1.0
            while not agent_calls and time.time() < deadline:
                time.sleep(0.01)

    assert agent_calls
    request_id = agent_calls[0]["request_id"]
    assert request_id.startswith("req_")
    assert agent_calls[0]["conversation_id"] == "telegram:44"
    assert captured[0].sent_messages == [(44, "ok")]

    update_completed = next(
        event
        for event in _events(caplog)
        if event["event"] == "telegram_update_completed"
        and event["update_id"] == 12
    )
    assert update_completed["request_id"] == request_id
    assert update_completed["conversation_id"] == "telegram:44"
