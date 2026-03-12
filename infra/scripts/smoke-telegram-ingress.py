#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _get_env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _require_env(name: str) -> str:
    value = _get_env(name, "")
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict | None = None,
    method: str | None = None,
) -> tuple[int, dict]:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        headers=request_headers,
        data=data,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode()
            return response.status, json.loads(payload)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode()
        try:
            body_json = json.loads(payload)
        except json.JSONDecodeError:
            body_json = {"raw": payload}
        return exc.code, body_json


def _wait_ready(base_url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            status, payload = _request_json(f"{base_url}/healthz")
        except urllib.error.URLError as exc:
            status, payload = 0, {"error": str(exc.reason)}
        if status == 200 and payload.get("status") == "ok":
            return
        if time.monotonic() >= deadline:
            raise SystemExit(f"{base_url}/healthz did not become ready: {status} {payload}")
        time.sleep(1)


def _fake_state(fake_base_url: str) -> dict:
    status, payload = _request_json(f"{fake_base_url}/test/state")
    if status != 200:
        raise SystemExit(f"fake telegram state endpoint failed: {status} {payload}")
    return payload


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    ingress_base_url = _get_env("TELEGRAM_SMOKE_BASE_URL", "http://127.0.0.1:18081").rstrip("/")
    fake_base_url = _get_env("TELEGRAM_FAKE_BASE_URL", "http://127.0.0.1:18082").rstrip("/")
    webhook_path = _get_env("TELEGRAM_SMOKE_WEBHOOK_PATH", "/telegram/webhook")
    secret = _require_env("TELEGRAM_SMOKE_WEBHOOK_SECRET_TOKEN")
    bot_token = _require_env("TELEGRAM_SMOKE_BOT_TOKEN")
    timeout_seconds = float(_get_env("TELEGRAM_SMOKE_TIMEOUT_SECONDS", "180"))

    _wait_ready(ingress_base_url, timeout_seconds)
    _wait_ready(fake_base_url, timeout_seconds)

    status, payload = _request_json(f"{fake_base_url}/test/reset", body={}, method="POST")
    if status != 200:
        raise SystemExit(f"fake telegram reset failed: {status} {payload}")

    run_id = int(time.time() * 1000)
    chat_id = 900000 + (run_id % 100000)

    valid_update = {
        "update_id": run_id,
        "message": {
            "message_id": run_id + 100,
            "chat": {"id": chat_id},
            "from": {"id": 1234, "is_bot": False},
            "text": "Reply with ok.",
        },
    }
    status, payload = _request_json(
        f"{ingress_base_url}{webhook_path}",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        body=valid_update,
        method="POST",
    )
    if status != 200:
        raise SystemExit(f"telegram happy path failed: {status} {payload}")

    state = _fake_state(fake_base_url)
    _assert(len(state["sent_messages"]) == 1, f"expected 1 sent telegram message, got {state}")
    first_message = state["sent_messages"][0]
    _assert(first_message["bot_token"] == bot_token, f"unexpected bot token in fake state: {state}")
    _assert(first_message["chat_id"] == chat_id, f"unexpected chat id in fake state: {state}")
    _assert(bool(first_message["text"].strip()), f"empty telegram reply in fake state: {state}")

    invalid_secret_update = {
        "update_id": run_id + 1,
        "message": {
            "message_id": run_id + 101,
            "chat": {"id": chat_id},
            "from": {"id": 1234, "is_bot": False},
            "text": "Should fail auth",
        },
    }
    status, payload = _request_json(
        f"{ingress_base_url}{webhook_path}",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
        body=invalid_secret_update,
        method="POST",
    )
    _assert(status == 401, f"expected webhook auth failure 401, got {status} {payload}")
    state = _fake_state(fake_base_url)
    _assert(len(state["sent_messages"]) == 1, f"auth failure should not send telegram replies: {state}")

    denied_command_update = {
        "update_id": run_id + 2,
        "message": {
            "message_id": run_id + 102,
            "chat": {"id": chat_id},
            "from": {"id": 1234, "is_bot": False},
            "text": "/play forbidden command",
        },
    }
    status, payload = _request_json(
        f"{ingress_base_url}{webhook_path}",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        body=denied_command_update,
        method="POST",
    )
    if status != 200:
        raise SystemExit(f"telegram command deny path failed: {status} {payload}")
    _assert(payload.get("status") == "ignored", f"expected ignored deny payload, got {payload}")
    _assert(payload.get("reason") == "command_not_allowed", f"unexpected deny reason: {payload}")
    state = _fake_state(fake_base_url)
    _assert(len(state["sent_messages"]) == 1, f"denied command should not send telegram replies: {state}")

    status, payload = _request_json(
        f"{fake_base_url}/test/fail-next-send",
        body={"status_code": 503, "description": "simulated-send-failure"},
        method="POST",
    )
    if status != 200:
        raise SystemExit(f"failed to arm telegram send failure: {status} {payload}")

    retry_update = {
        "update_id": run_id + 3,
        "message": {
            "message_id": run_id + 103,
            "chat": {"id": chat_id},
            "from": {"id": 1234, "is_bot": False},
            "text": "Retry this request.",
        },
    }
    status, payload = _request_json(
        f"{ingress_base_url}{webhook_path}",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        body=retry_update,
        method="POST",
    )
    _assert(status == 503, f"expected retryable downstream failure 503, got {status} {payload}")
    state = _fake_state(fake_base_url)
    _assert(len(state["sent_messages"]) == 1, f"failed send should not add successful messages: {state}")
    _assert(len(state["send_attempts"]) == 2, f"expected one extra failed send attempt: {state}")

    status, payload = _request_json(
        f"{ingress_base_url}{webhook_path}",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        body=retry_update,
        method="POST",
    )
    if status != 200:
        raise SystemExit(f"retry after downstream failure did not recover: {status} {payload}")
    state = _fake_state(fake_base_url)
    _assert(len(state["sent_messages"]) == 2, f"retry should add a successful message: {state}")
    _assert(len(state["send_attempts"]) == 3, f"retry should create a new send attempt: {state}")
    retry_message = state["sent_messages"][-1]
    _assert(retry_message["chat_id"] == chat_id, f"unexpected retry chat id: {state}")
    _assert(bool(retry_message["text"].strip()), f"retry reply should be non-empty: {state}")

    print("Telegram ingress smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
