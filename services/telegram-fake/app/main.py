from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict


@dataclass(slots=True)
class FakeTelegramState:
    sent_messages: list[dict[str, Any]] = field(default_factory=list)
    send_attempts: list[dict[str, Any]] = field(default_factory=list)
    webhook_calls: list[dict[str, Any]] = field(default_factory=list)
    updates: list[dict[str, Any]] = field(default_factory=list)
    fail_next_send_status_code: int | None = None
    fail_next_send_description: str = "telegram-fake-send-failure"
    fail_next_send_retry_after: int | None = None


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chat_id: int
    text: str


class SetWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    secret_token: str | None = None
    drop_pending_updates: bool = True
    max_connections: int | None = None
    allowed_updates: list[str] | None = None


class FailNextSendRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status_code: int = 503
    description: str = "telegram-fake-send-failure"
    retry_after: int | None = None


app = FastAPI(title="telegram-fake", version="0.1.0")
_state = FakeTelegramState()
_lock = Lock()


def _snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "sent_messages": list(_state.sent_messages),
            "send_attempts": list(_state.send_attempts),
            "webhook_calls": list(_state.webhook_calls),
            "updates": list(_state.updates),
            "fail_next_send_status_code": _state.fail_next_send_status_code,
            "fail_next_send_description": _state.fail_next_send_description,
            "fail_next_send_retry_after": _state.fail_next_send_retry_after,
        }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/test/state")
def test_state() -> dict[str, Any]:
    return _snapshot()


@app.post("/test/reset")
def test_reset() -> dict[str, str]:
    with _lock:
        _state.sent_messages.clear()
        _state.send_attempts.clear()
        _state.webhook_calls.clear()
        _state.updates.clear()
        _state.fail_next_send_status_code = None
        _state.fail_next_send_description = "telegram-fake-send-failure"
        _state.fail_next_send_retry_after = None
    return {"status": "ok"}


@app.post("/test/fail-next-send")
def fail_next_send(request: FailNextSendRequest) -> dict[str, Any]:
    with _lock:
        _state.fail_next_send_status_code = request.status_code
        _state.fail_next_send_description = request.description
        _state.fail_next_send_retry_after = request.retry_after
    return {
        "status": "armed",
        "status_code": request.status_code,
        "description": request.description,
        "retry_after": request.retry_after,
    }


@app.post("/bot{bot_token}/sendMessage")
def send_message(bot_token: str, request: SendMessageRequest) -> dict[str, Any]:
    with _lock:
        _state.send_attempts.append(
            {
                "bot_token": bot_token,
                "chat_id": request.chat_id,
                "text": request.text,
            }
        )
        failure_status = _state.fail_next_send_status_code
        failure_description = _state.fail_next_send_description
        failure_retry_after = _state.fail_next_send_retry_after
        if failure_status is not None:
            _state.fail_next_send_status_code = None
            _state.fail_next_send_description = "telegram-fake-send-failure"
            _state.fail_next_send_retry_after = None
            failure_payload: dict[str, Any] = {
                "ok": False,
                "error_code": failure_status,
                "description": failure_description,
            }
            if failure_retry_after is not None:
                failure_payload["parameters"] = {
                    "retry_after": failure_retry_after,
                }
            return JSONResponse(status_code=failure_status, content=failure_payload)

        _state.sent_messages.append(
            {
                "bot_token": bot_token,
                "chat_id": request.chat_id,
                "text": request.text,
            }
        )

    return {
        "ok": True,
        "result": {
            "message_id": len(_state.sent_messages),
            "chat": {"id": request.chat_id},
            "text": request.text,
        },
    }


@app.post("/bot{bot_token}/setWebhook")
def set_webhook(bot_token: str, request: SetWebhookRequest) -> dict[str, Any]:
    with _lock:
        _state.webhook_calls.append(
            {
                "bot_token": bot_token,
                "url": request.url,
                "secret_token": request.secret_token,
                "drop_pending_updates": request.drop_pending_updates,
                "max_connections": request.max_connections,
                "allowed_updates": request.allowed_updates,
            }
        )

    return {"ok": True, "result": True}


@app.get("/bot{bot_token}/getUpdates")
def get_updates(bot_token: str, timeout: int = 30, offset: int | None = None, limit: int = 100) -> dict[str, Any]:
    with _lock:
        output: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        for update in _state.updates:
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                continue
            if offset is not None and update_id < offset:
                continue
            if len(output) < limit:
                output.append(update)
            else:
                remaining.append(update)
        _state.updates = remaining

    return {
        "ok": True,
        "result": output,
        "meta": {
            "bot_token": bot_token,
            "timeout": timeout,
        },
    }
