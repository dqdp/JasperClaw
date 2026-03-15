from __future__ import annotations

import asyncio
import warnings
import json
import logging
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clients.agent_api import AgentApiClient, AgentApiError, CapabilityDiscovery
from app.clients.telegram import TelegramClient
from app.core.config import Settings
from app.core.metrics import AlertDeliveryMetrics
from app.main import create_app
from app.modules.alerts.facade import AlertFacade
from app.modules.webhook.facade import WebhookFacade
from app.services.alert_delivery import (
    AlertDeliveryRequest,
    AlertDeliveryStorageError,
    AlertSubmissionResult,
)
from app.services.bridge import TelegramBridgeService, WebhookResult


_TEST_HOUSEHOLD_CONFIG = (
    Path(__file__).resolve().parent / "fixtures" / "household.toml"
)


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
    def __init__(
        self,
        reply_text: str = "ok",
        *,
        help_text: str = "Help from agent-api",
        status_text: str = "Status from agent-api",
    ) -> None:
        self.calls: list[dict[str, str]] = []
        self.discovery_calls: list[str] = []
        self.closed = False
        self.reply_text = reply_text
        self.help_text = help_text
        self.status_text = status_text

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

    async def send_alias_command(
        self,
        *,
        model: str,
        alias: str,
        text: str,
        conversation_id: str,
        request_id: str,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "text": text,
                "alias": alias,
                "conversation_id": conversation_id,
                "request_id": request_id,
                "mode": "send_alias_command",
            }
        )
        return self.reply_text

    async def list_aliases_command(
        self,
        *,
        model: str,
        conversation_id: str,
        request_id: str,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "text": "",
                "conversation_id": conversation_id,
                "request_id": request_id,
                "mode": "list_aliases_command",
            }
        )
        return self.reply_text

    async def describe_capabilities(
        self,
        *,
        request_id: str,
    ) -> CapabilityDiscovery:
        self.discovery_calls.append(request_id)
        return CapabilityDiscovery(
            help_text=self.help_text,
            status_text=self.status_text,
        )

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

    async def describe_capabilities(
        self,
        *,
        request_id: str,
    ) -> CapabilityDiscovery:
        self.calls.append(
            {
                "model": "",
                "text": "",
                "conversation_id": "",
                "request_id": request_id,
            }
        )
        raise AgentApiError("agent-api unavailable")

    async def send_alias_command(
        self,
        *,
        model: str,
        alias: str,
        text: str,
        conversation_id: str,
        request_id: str,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "text": text,
                "alias": alias,
                "conversation_id": conversation_id,
                "request_id": request_id,
                "mode": "send_alias_command",
            }
        )
        raise AgentApiError("agent-api unavailable")

    async def list_aliases_command(
        self,
        *,
        model: str,
        conversation_id: str,
        request_id: str,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "text": "",
                "conversation_id": conversation_id,
                "request_id": request_id,
                "mode": "list_aliases_command",
            }
        )
        raise AgentApiError("agent-api unavailable")

    async def close(self) -> None:
        self.closed = True


class _FakeAlertDeliveryService:
    def __init__(
        self,
        *,
        results: list[AlertSubmissionResult | Exception] | None = None,
    ) -> None:
        self.requests: list[AlertDeliveryRequest] = []
        self.request_ids: list[str] = []
        self.process_due_calls: list[int] = []
        self.closed = False
        self._results = list(results or [])

    async def submit_delivery(
        self,
        *,
        request: AlertDeliveryRequest,
        request_id: str,
    ) -> AlertSubmissionResult:
        self.requests.append(request)
        self.request_ids.append(request_id)
        if self._results:
            result = self._results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return AlertSubmissionResult(
            delivery_id=f"alert_{len(self.requests)}",
            status="sent",
            recipients=len(request.deliveries),
            matched_alerts=request.matched_alerts,
            deduplicated=False,
        )

    async def process_due_deliveries(
        self,
        *,
        limit: int = 10,
    ) -> int:
        self.process_due_calls.append(limit)
        return 0

    async def close(self) -> None:
        self.closed = True


class _FakeWebhookBridgeService:
    def __init__(self, result: WebhookResult | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.result = result or WebhookResult.ok(
            update_id=1,
            chat_id=7,
            message_id=9,
            conversation_id="telegram:7",
            status="processed",
        )

    async def process_update(
        self,
        payload: dict[str, object],
        *,
        request_id: str,
    ) -> WebhookResult:
        self.calls.append(
            {
                "payload": payload,
                "request_id": request_id,
            }
        )
        return self.result


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
        "household_config_path": str(_TEST_HOUSEHOLD_CONFIG),
    }
    if overrides:
        base.update(overrides)
    return Settings(**base)


def _create_alert_client(
    *,
    settings: Settings | None = None,
    alert_service: _FakeAlertDeliveryService | None = None,
    alert_delivery_metrics: AlertDeliveryMetrics | None = None,
) -> tuple[TestClient, _FakeAlertDeliveryService]:
    settings = settings or _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
        }
    )
    alert_service = alert_service or _FakeAlertDeliveryService()
    app = create_app(
        settings=settings,
        bridge_service=TelegramBridgeService(
            agent_client=_FakeAgentApiClient(),
            telegram_client=_FakeTelegramClient(),
            settings=settings,
        ),
        alert_delivery_service=alert_service,
        alert_delivery_metrics=alert_delivery_metrics,
    )
    return TestClient(app), alert_service


def test_metrics_endpoint_exposes_alert_delivery_metrics() -> None:
    metrics = AlertDeliveryMetrics()
    metrics.record_claim(origin="pending")
    metrics.record_target_attempt(status="sent", error_code=None)
    metrics.record_finalize(status="completed")
    metrics.record_escalation(reason="retry_exhausted")
    client, _ = _create_alert_client(alert_delivery_metrics=metrics)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'telegram_alert_delivery_claim_total{origin="pending"} 1' in response.text
    assert (
        'telegram_alert_delivery_target_attempt_total{error_class="none",status="sent"} 1'
        in response.text
    )
    assert 'telegram_alert_delivery_finalize_total{status="completed"} 1' in response.text
    assert 'telegram_alert_delivery_escalated_total{reason="retry_exhausted"} 1' in response.text


def test_create_app_does_not_emit_on_event_deprecation_warning() -> None:
    settings = _operational_settings({})

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        create_app(settings=settings)

    assert not any(
        isinstance(warning.message, DeprecationWarning)
        and "on_event is deprecated" in str(warning.message)
        for warning in caught
    )


def test_webhook_facade_passes_request_id_to_bridge_service() -> None:
    bridge_service = _FakeWebhookBridgeService()
    facade = WebhookFacade(bridge_service=bridge_service)  # type: ignore[arg-type]

    result = asyncio.run(
        facade.handle_update(
            update={"update_id": 55},
            request_id="req_webhook_facade",
        )
    )

    assert bridge_service.calls == [
        {
            "payload": {"update_id": 55},
            "request_id": "req_webhook_facade",
        }
    ]
    assert result == bridge_service.result


def test_alert_facade_passes_explicit_idempotency_key_to_delivery_service() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_chat_ids": (11,),
        }
    )
    alert_service = _FakeAlertDeliveryService()
    facade = AlertFacade(
        settings=settings,
        alert_delivery_service=alert_service,
    )

    response = asyncio.run(
        facade.submit_alert(
            payload={"text": "manual downtime"},
            request_id="req_alert_facade",
            header_idempotency_key="alertmanager-notification-42",
        )
    )

    assert response.status_code == 200
    assert response.payload["status"] == "sent"
    assert alert_service.request_ids == ["req_alert_facade"]
    assert alert_service.requests == [
        AlertDeliveryRequest(
            deliveries=((11, "manual downtime"),),
            matched_alerts=1,
            idempotency_key="alertmanager-notification-42",
        )
    ]


def test_alert_facade_maps_accepted_delivery_and_process_due_once() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_chat_ids": (11,),
        }
    )
    alert_service = _FakeAlertDeliveryService(
        results=[
            AlertSubmissionResult(
                delivery_id="alert_retry",
                status="accepted",
                recipients=1,
                matched_alerts=1,
                deduplicated=False,
            )
        ]
    )
    facade = AlertFacade(
        settings=settings,
        alert_delivery_service=alert_service,
    )

    response = asyncio.run(
        facade.submit_alert(
            payload={"text": "manual downtime"},
            request_id="req_alert_facade",
            header_idempotency_key=None,
        )
    )
    processed = asyncio.run(facade.process_due_once(limit=7))

    assert response.status_code == 202
    assert response.payload == {
        "status": "accepted",
        "delivery_id": "alert_retry",
        "recipients": 1,
        "matched_alerts": 1,
        "deduplicated": False,
    }
    assert processed == 0
    assert alert_service.process_due_calls == [7]


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
    assert agent_client.discovery_calls == [response.headers["X-Request-ID"]]
    assert telegram_client.sent_messages == [(77, "Help from agent-api")]


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
    assert agent_client.discovery_calls == [response.headers["X-Request-ID"]]
    assert telegram_client.sent_messages == [(77, "Status from agent-api")]


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
    assert agent_client.discovery_calls == [response.headers["X-Request-ID"]]
    assert telegram_client.sent_messages == [(77, "Status from agent-api")]


def test_webhook_help_command_falls_back_to_bounded_local_reply_when_discovery_fails() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(
        settings=settings,
        agent_client=_FailingAgentApiClient(),
    )
    response = client.post(
        "/webhook",
        json={
            "update_id": 603,
            "message": {
                "message_id": 10,
                "chat": {"id": 77},
                "text": "/help",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert telegram_client.sent_messages == [
        (
            77,
            "Available commands: /help, /status, /ask <message>, /aliases, "
            "/send <alias> <message>",
        )
    ]
    assert agent_client.calls[0]["request_id"] == response.headers["X-Request-ID"]


def test_webhook_status_command_falls_back_to_bounded_local_reply_when_discovery_fails() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(
        settings=settings,
        agent_client=_FailingAgentApiClient(),
    )
    response = client.post(
        "/webhook",
        json={
            "update_id": 604,
            "message": {
                "message_id": 11,
                "chat": {"id": 77},
                "text": "/status",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert telegram_client.sent_messages == [
        (77, "Status is temporarily unavailable right now.")
    ]
    assert agent_client.calls[0]["request_id"] == response.headers["X-Request-ID"]


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


def test_webhook_aliases_command_routes_through_agent_api() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(
        settings=settings,
        agent_client=_FakeAgentApiClient(
            reply_text="Available aliases:\n- wife: Personal chat"
        ),
    )

    response = client.post(
        "/webhook",
        json={
            "update_id": 6051,
            "message": {
                "message_id": 15,
                "chat": {"id": 77},
                "text": "/aliases",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert agent_client.calls == [
        {
            "model": "assistant-fast",
            "text": "",
            "conversation_id": "telegram:77",
            "request_id": agent_client.calls[0]["request_id"],
            "mode": "list_aliases_command",
        }
    ]
    assert telegram_client.sent_messages == [
        (77, "Available aliases:\n- wife: Personal chat")
    ]


def test_webhook_send_command_routes_through_agent_api_and_acknowledges_sender() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(
        settings=settings,
        agent_client=_FakeAgentApiClient(reply_text="Sent to wife."),
    )

    response = client.post(
        "/webhook",
        json={
            "update_id": 6052,
            "message": {
                "message_id": 16,
                "chat": {"id": 77},
                "text": "/send wife Running late",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert agent_client.calls == [
        {
            "model": "assistant-fast",
            "text": "Running late",
            "alias": "wife",
            "conversation_id": "telegram:77",
            "request_id": agent_client.calls[0]["request_id"],
            "mode": "send_alias_command",
        }
    ]
    assert telegram_client.sent_messages == [(77, "Sent to wife.")]


def test_webhook_send_command_surfaces_agent_api_alias_validation() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(
        settings=settings,
        agent_client=_FakeAgentApiClient(
            reply_text="Unknown alias 'unknown'. Use /aliases to see configured recipients."
        ),
    )

    response = client.post(
        "/webhook",
        json={
            "update_id": 6053,
            "message": {
                "message_id": 17,
                "chat": {"id": 77},
                "text": "/send unknown Running late",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert agent_client.calls == [
        {
            "model": "assistant-fast",
            "text": "Running late",
            "alias": "unknown",
            "conversation_id": "telegram:77",
            "request_id": agent_client.calls[0]["request_id"],
            "mode": "send_alias_command",
        }
    ]
    assert telegram_client.sent_messages == [
        (77, "Unknown alias 'unknown'. Use /aliases to see configured recipients.")
    ]


def test_webhook_rejects_untrusted_chat_before_agent_call() -> None:
    settings = _operational_settings({})
    client, telegram_client, agent_client = _create_client(settings=settings)

    response = client.post(
        "/webhook",
        json={
            "update_id": 606,
            "message": {
                "message_id": 13,
                "chat": {"id": 1001},
                "text": "hello there",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert not agent_client.calls
    assert telegram_client.sent_messages == [
        (1001, "This chat is not authorized for household assistant access.")
    ]


def test_webhook_rejects_chat_when_household_config_is_missing() -> None:
    settings = _operational_settings({"household_config_path": ""})
    client, telegram_client, agent_client = _create_client(settings=settings)

    response = client.post(
        "/webhook",
        json={
            "update_id": 607,
            "message": {
                "message_id": 14,
                "chat": {"id": 77},
                "text": "/ask what is the status?",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert not agent_client.calls
    assert telegram_client.sent_messages == [
        (77, "This chat is not authorized for household assistant access.")
    ]


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
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
        }
    )
    client, alert_service = _create_alert_client(settings=settings)
    response = client.post(
        "/telegram/alerts",
        json={"text": "downtime"},
        headers={"X-Telegram-Alert-Token": "wrong"},
    )
    assert response.status_code == 401
    assert alert_service.requests == []


def test_alerts_endpoint_sends_to_all_configured_chats() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11, 22),
        }
    )
    client, alert_service = _create_alert_client(settings=settings)
    response = client.post(
        "/telegram/alerts",
        json={"text": "downtime"},
        headers={"X-Telegram-Alert-Token": "alert-secret"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "sent",
        "delivery_id": "alert_1",
        "recipients": 2,
        "matched_alerts": 1,
        "deduplicated": False,
    }
    assert alert_service.requests == [
        AlertDeliveryRequest(
            deliveries=((11, "downtime"), (22, "downtime")),
            matched_alerts=1,
            idempotency_key=None,
        )
    ]


def test_alerts_endpoint_formats_alert_payload() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
        }
    )
    client, alert_service = _create_alert_client(settings=settings)
    response = client.post(
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
    assert response.status_code == 200
    assert alert_service.requests == [
        AlertDeliveryRequest(
            deliveries=(
                (
                    11,
                    "FIRING high_cpu [critical] on agent-api: CPU usage exceeded 90% for 5m",
                ),
            ),
            matched_alerts=1,
            idempotency_key=None,
        )
    ]
    assert response.json()["status"] == "sent"


def test_alerts_endpoint_passes_explicit_idempotency_key() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
        }
    )
    client, alert_service = _create_alert_client(settings=settings)
    response = client.post(
        "/telegram/alerts",
        json={
            "status": "firing",
            "alerts": [
                {
                    "labels": {
                        "alertname": "high_cpu",
                        "severity": "critical",
                        "service": "agent-api",
                    },
                    "annotations": {
                        "description": "CPU usage exceeded 90% for 5m",
                    },
                }
            ],
        },
        headers={
            "X-Telegram-Alert-Token": "alert-secret",
            "X-Telegram-Alert-Idempotency-Key": "alertmanager-notification-42",
        },
    )

    assert response.status_code == 200
    assert alert_service.requests == [
        AlertDeliveryRequest(
            deliveries=(
                (
                    11,
                    "FIRING high_cpu [critical] on agent-api: CPU usage exceeded 90% for 5m",
                ),
            ),
            matched_alerts=1,
            idempotency_key="alertmanager-notification-42",
        )
    ]


def test_alerts_endpoint_routes_alerts_by_severity_policy() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
            "telegram_alert_warning_chat_ids": (22,),
            "telegram_alert_critical_chat_ids": (33,),
        }
    )
    client, alert_service = _create_alert_client(settings=settings)
    response = client.post(
        "/telegram/alerts",
        json={
            "status": "firing",
            "alerts": [
                {
                    "labels": {
                        "alertname": "high_latency",
                        "severity": "warning",
                        "service": "agent-api",
                    },
                    "annotations": {
                        "description": "Latency exceeded threshold",
                    },
                },
                {
                    "labels": {
                        "alertname": "ingress_down",
                        "severity": "critical",
                        "service": "telegram-ingress",
                    },
                    "annotations": {
                        "description": "Ingress health failed",
                    },
                },
            ],
        },
        headers={"X-Telegram-Alert-Token": "alert-secret"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert response.json()["recipients"] == 3
    assert alert_service.requests == [
        AlertDeliveryRequest(
            deliveries=(
                (
                    11,
                    "FIRING high_latency [warning] on agent-api: Latency exceeded threshold\n"
                    "FIRING ingress_down [critical] on telegram-ingress: Ingress health failed",
                ),
                (
                    22,
                    "FIRING high_latency [warning] on agent-api: Latency exceeded threshold\n"
                    "FIRING ingress_down [critical] on telegram-ingress: Ingress health failed",
                ),
                (
                    33,
                    "FIRING ingress_down [critical] on telegram-ingress: Ingress health failed",
                ),
            ),
            matched_alerts=2,
            idempotency_key=None,
        )
    ]


def test_alerts_endpoint_deduplicates_overlapping_route_recipients() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
            "telegram_alert_warning_chat_ids": (11, 22),
            "telegram_alert_critical_chat_ids": (11, 33),
        }
    )
    client, alert_service = _create_alert_client(settings=settings)
    response = client.post(
        "/telegram/alerts",
        json={
            "status": "firing",
            "alerts": [
                {
                    "labels": {
                        "alertname": "database_down",
                        "severity": "critical",
                        "service": "postgres",
                    },
                    "annotations": {
                        "description": "Database unavailable",
                    },
                }
            ],
        },
        headers={"X-Telegram-Alert-Token": "alert-secret"},
    )
    assert response.status_code == 200
    assert response.json()["recipients"] == 3
    assert alert_service.requests == [
        AlertDeliveryRequest(
            deliveries=(
                (11, "FIRING database_down [critical] on postgres: Database unavailable"),
                (22, "FIRING database_down [critical] on postgres: Database unavailable"),
                (33, "FIRING database_down [critical] on postgres: Database unavailable"),
            ),
            matched_alerts=1,
            idempotency_key=None,
        )
    ]


def test_alerts_endpoint_filters_resolved_alerts_by_default() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
        }
    )
    client, alert_service = _create_alert_client(settings=settings)
    response = client.post(
        "/telegram/alerts",
        json={
            "status": "resolved",
            "alerts": [
                {
                    "labels": {
                        "alertname": "high_cpu",
                        "severity": "critical",
                        "service": "agent-api",
                    },
                    "annotations": {
                        "description": "CPU back to normal",
                    },
                }
            ],
        },
        headers={"X-Telegram-Alert-Token": "alert-secret"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ignored",
        "reason": "alert_policy_filtered",
        "matched_alerts": 0,
    }
    assert alert_service.requests == []


def test_alerts_endpoint_can_send_resolved_alerts_when_enabled() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
            "telegram_alert_send_resolved": True,
        }
    )
    client, alert_service = _create_alert_client(settings=settings)
    response = client.post(
        "/telegram/alerts",
        json={
            "status": "resolved",
            "alerts": [
                {
                    "labels": {
                        "alertname": "high_cpu",
                        "severity": "critical",
                        "service": "agent-api",
                    },
                    "annotations": {
                        "description": "CPU back to normal",
                    },
                }
            ],
        },
        headers={"X-Telegram-Alert-Token": "alert-secret"},
    )
    assert response.status_code == 200
    assert alert_service.requests == [
        AlertDeliveryRequest(
            deliveries=(
                (11, "RESOLVED high_cpu [critical] on agent-api: CPU back to normal"),
            ),
            matched_alerts=1,
            idempotency_key=None,
        )
    ]
    assert response.json()["status"] == "sent"


def test_alerts_endpoint_uses_all_routes_for_manual_text_without_default_route() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (),
            "telegram_alert_warning_chat_ids": (22,),
            "telegram_alert_critical_chat_ids": (33,),
        }
    )
    client, alert_service = _create_alert_client(settings=settings)
    response = client.post(
        "/telegram/alerts",
        json={"text": "manual downtime"},
        headers={"X-Telegram-Alert-Token": "alert-secret"},
    )
    assert response.status_code == 200
    assert response.json()["recipients"] == 2
    assert alert_service.requests == [
        AlertDeliveryRequest(
            deliveries=((22, "manual downtime"), (33, "manual downtime")),
            matched_alerts=1,
            idempotency_key=None,
        )
    ]


def test_alerts_endpoint_returns_202_when_delivery_is_accepted_for_retry() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
            "telegram_alert_warning_chat_ids": (22,),
        }
    )
    alert_service = _FakeAlertDeliveryService(
        results=[
            AlertSubmissionResult(
                delivery_id="alert_retry",
                status="accepted",
                recipients=2,
                matched_alerts=1,
                deduplicated=False,
            )
        ]
    )
    client, _ = _create_alert_client(settings=settings, alert_service=alert_service)
    response = client.post(
        "/telegram/alerts",
        json={
            "status": "firing",
            "alerts": [
                {
                    "labels": {
                        "alertname": "high_latency",
                        "severity": "warning",
                        "service": "agent-api",
                    },
                    "annotations": {
                        "description": "Latency exceeded threshold",
                    },
                }
            ],
        },
        headers={"X-Telegram-Alert-Token": "alert-secret"},
    )
    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "delivery_id": "alert_retry",
        "recipients": 2,
        "matched_alerts": 1,
        "deduplicated": False,
    }


def test_alerts_endpoint_returns_502_when_delivery_terminally_fails() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
        }
    )
    alert_service = _FakeAlertDeliveryService(
        results=[
            AlertSubmissionResult(
                delivery_id="alert_failed",
                status="failed",
                recipients=1,
                matched_alerts=1,
                deduplicated=False,
            )
        ]
    )
    client, _ = _create_alert_client(settings=settings, alert_service=alert_service)
    response = client.post(
        "/telegram/alerts",
        json={"text": "manual downtime"},
        headers={"X-Telegram-Alert-Token": "alert-secret"},
    )
    assert response.status_code == 502
    assert response.json() == {
        "status": "failed",
        "delivery_id": "alert_failed",
        "recipients": 1,
        "matched_alerts": 1,
        "deduplicated": False,
    }


def test_alerts_endpoint_returns_503_when_durable_storage_is_unavailable() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
        }
    )
    alert_service = _FakeAlertDeliveryService(
        results=[AlertDeliveryStorageError("postgres unavailable")]
    )
    client, _ = _create_alert_client(settings=settings, alert_service=alert_service)
    response = client.post(
        "/telegram/alerts",
        json={"text": "manual downtime"},
        headers={"X-Telegram-Alert-Token": "alert-secret"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "telegram alert delivery unavailable"


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


def test_alert_delivery_service_is_closed_on_shutdown() -> None:
    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
        }
    )
    alert_service = _FakeAlertDeliveryService()
    app = create_app(
        settings=settings,
        bridge_service=TelegramBridgeService(
            agent_client=_FakeAgentApiClient(),
            telegram_client=_FakeTelegramClient(),
            settings=settings,
        ),
        alert_delivery_service=alert_service,
    )
    with TestClient(app):
        pass

    assert alert_service.closed is True


def test_alert_retry_worker_polls_due_deliveries(monkeypatch) -> None:
    from app import main as main_module

    settings = _operational_settings(
        {
            "telegram_alert_bot_token": "alert-bot-token",
            "telegram_alert_auth_token": "alert-secret",
            "telegram_alert_chat_ids": (11,),
            "telegram_alert_retry_poll_seconds": 0.01,
        }
    )
    alert_service = _FakeAlertDeliveryService()
    original_sleep = asyncio.sleep

    async def _fast_sleep(delay: float) -> None:
        await original_sleep(0 if delay > 0 else delay)

    monkeypatch.setattr(main_module.asyncio, "sleep", _fast_sleep)
    app = main_module.create_app(
        settings=settings,
        bridge_service=TelegramBridgeService(
            agent_client=_FakeAgentApiClient(),
            telegram_client=_FakeTelegramClient(),
            settings=settings,
        ),
        alert_delivery_service=alert_service,
    )

    with TestClient(app):
        deadline = time.time() + 1.0
        while not alert_service.process_due_calls and time.time() < deadline:
            time.sleep(0.01)
        assert getattr(app.state, "alert_retry_task", None) is not None
        assert not app.state.alert_retry_task.done()

    assert alert_service.process_due_calls
    assert app.state.alert_retry_task.done()


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
