from __future__ import annotations

from fastapi.testclient import TestClient

from app.clients.agent_api import AgentApiClient
from app.clients.telegram import TelegramClient
from app.core.config import Settings
from app.main import create_app
from app.services.bridge import TelegramBridgeService


class _FakeTelegramClient(TelegramClient):
    def __init__(self) -> None:
        self.sent_messages: list[tuple[int, str]] = []
        self.closed = False

    async def send_message(self, *, chat_id: int, text: str) -> None:
        self.sent_messages.append((chat_id, text))

    async def close(self) -> None:
        self.closed = True


class _FakeAgentApiClient(AgentApiClient):
    def __init__(self, reply_text: str = "ok") -> None:
        self.calls: list[dict[str, str]] = []
        self.closed = False
        self.reply_text = reply_text

    async def complete(self, *, model: str, text: str, conversation_id: str) -> str:
        self.calls.append({"model": model, "text": text, "conversation_id": conversation_id})
        return self.reply_text

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


def _operational_settings(overrides: dict[str, str] | None = None) -> Settings:
    base: dict[str, str] = {
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
        {"model": "assistant-fast", "text": "привет", "conversation_id": "telegram:42"},
    ]
    assert telegram_client.sent_messages == [(42, "ok")]


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
