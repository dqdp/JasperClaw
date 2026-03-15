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


def _is_truthy_env(name: str) -> bool:
    return _get_env(name, "").lower() in {"1", "true", "yes", "on"}


def _get_int_list_env(name: str) -> tuple[int, ...]:
    raw = _get_env(name, "")
    if not raw:
        return ()
    values: list[int] = []
    for item in raw.split(","):
        normalized = item.strip()
        if not normalized:
            continue
        values.append(int(normalized))
    return tuple(values)


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


def _wait_for_success(
    *,
    request_fn,
    success_predicate,
    timeout_seconds: float,
    error_context: str,
) -> tuple[int, dict]:
    deadline = time.monotonic() + timeout_seconds
    last_result: tuple[int, dict] = (0, {"error": "not started"})

    while True:
        try:
            last_result = request_fn()
        except urllib.error.URLError as exc:
            last_result = (0, {"error": str(exc.reason)})

        status, payload = last_result
        if success_predicate(status, payload):
            return last_result
        if time.monotonic() >= deadline:
            raise SystemExit(f"{error_context}: {status} {payload}")
        time.sleep(2)


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
    alert_token = _require_env("TELEGRAM_SMOKE_ALERT_AUTH_TOKEN")
    alert_bot_token = _require_env("TELEGRAM_SMOKE_ALERT_BOT_TOKEN")
    alert_default_chat_ids = _get_int_list_env("TELEGRAM_SMOKE_ALERT_CHAT_IDS")
    alert_warning_chat_ids = _get_int_list_env("TELEGRAM_SMOKE_ALERT_WARNING_CHAT_IDS")
    alert_critical_chat_ids = _get_int_list_env("TELEGRAM_SMOKE_ALERT_CRITICAL_CHAT_IDS")
    timeout_seconds = float(_get_env("TELEGRAM_SMOKE_TIMEOUT_SECONDS", "180"))
    check_household = _is_truthy_env("TELEGRAM_SMOKE_CHECK_HOUSEHOLD")
    trusted_chat_id = int(_get_env("TELEGRAM_SMOKE_TRUSTED_CHAT_ID", "123456789"))
    untrusted_chat_id = int(
        _get_env("TELEGRAM_SMOKE_UNTRUSTED_CHAT_ID", str(trusted_chat_id + 1))
    )
    alias_name = _get_env("TELEGRAM_SMOKE_ALIAS", "demo_home")
    alias_chat_id = int(_get_env("TELEGRAM_SMOKE_ALIAS_CHAT_ID", "111111111"))

    _wait_ready(ingress_base_url, timeout_seconds)
    _wait_ready(fake_base_url, timeout_seconds)

    status, payload = _request_json(f"{fake_base_url}/test/reset", body={}, method="POST")
    if status != 200:
        raise SystemExit(f"fake telegram reset failed: {status} {payload}")

    run_id = int(time.time() * 1000)
    chat_id = trusted_chat_id if check_household else 900000 + (run_id % 100000)
    expected_sent_messages = 0
    expected_send_attempts = 0

    valid_update = {
        "update_id": run_id,
        "message": {
            "message_id": run_id + 100,
            "chat": {"id": chat_id},
            "from": {"id": 1234, "is_bot": False},
            "text": "Reply with ok.",
        },
    }
    status, payload = _wait_for_success(
        request_fn=lambda: _request_json(
            f"{ingress_base_url}{webhook_path}",
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            body=valid_update,
            method="POST",
        ),
        success_predicate=lambda status, payload: status == 200,
        timeout_seconds=30.0,
        error_context="telegram happy path did not stabilize before timeout",
    )

    state = _fake_state(fake_base_url)
    expected_sent_messages += 1
    expected_send_attempts += 1
    _assert(
        len(state["sent_messages"]) == expected_sent_messages,
        f"expected {expected_sent_messages} sent telegram messages, got {state}",
    )
    first_message = state["sent_messages"][0]
    _assert(first_message["bot_token"] == bot_token, f"unexpected bot token in fake state: {state}")
    _assert(first_message["chat_id"] == chat_id, f"unexpected chat id in fake state: {state}")
    _assert(bool(first_message["text"].strip()), f"empty telegram reply in fake state: {state}")

    follow_up_update = {
        "update_id": run_id + 1,
        "message": {
            "message_id": run_id + 101,
            "chat": {"id": chat_id},
            "from": {"id": 1234, "is_bot": False},
            "text": "Second message in the same chat.",
        },
    }
    status, payload = _request_json(
        f"{ingress_base_url}{webhook_path}",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        body=follow_up_update,
        method="POST",
    )
    if status != 200:
        raise SystemExit(f"telegram continuity happy path failed: {status} {payload}")

    state = _fake_state(fake_base_url)
    expected_sent_messages += 1
    expected_send_attempts += 1
    _assert(
        len(state["sent_messages"]) == expected_sent_messages,
        f"expected {expected_sent_messages} sent telegram messages after continuity check, got {state}",
    )
    follow_up_message = state["sent_messages"][-1]
    _assert(follow_up_message["chat_id"] == chat_id, f"unexpected continuity chat id: {state}")
    _assert(bool(follow_up_message["text"].strip()), f"empty continuity reply in fake state: {state}")

    invalid_secret_update = {
        "update_id": run_id + 2,
        "message": {
            "message_id": run_id + 102,
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
    _assert(
        len(state["sent_messages"]) == expected_sent_messages,
        f"auth failure should not send telegram replies: {state}",
    )

    if check_household:
        aliases_update = {
            "update_id": run_id + 20,
            "message": {
                "message_id": run_id + 120,
                "chat": {"id": trusted_chat_id},
                "from": {"id": 1234, "is_bot": False},
                "text": "/aliases",
            },
        }
        status, payload = _request_json(
            f"{ingress_base_url}{webhook_path}",
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            body=aliases_update,
            method="POST",
        )
        if status != 200:
            raise SystemExit(f"telegram aliases command failed: {status} {payload}")
        state = _fake_state(fake_base_url)
        expected_sent_messages += 1
        expected_send_attempts += 1
        _assert(
            len(state["sent_messages"]) == expected_sent_messages,
            f"aliases command should add one reply message: {state}",
        )
        aliases_message = state["sent_messages"][-1]
        _assert(aliases_message["chat_id"] == trusted_chat_id, f"unexpected aliases chat: {state}")
        _assert(alias_name in aliases_message["text"], f"aliases reply missing alias name: {state}")

        send_text = "Smoke household send."
        send_update = {
            "update_id": run_id + 21,
            "message": {
                "message_id": run_id + 121,
                "chat": {"id": trusted_chat_id},
                "from": {"id": 1234, "is_bot": False},
                "text": f"/send {alias_name} {send_text}",
            },
        }
        status, payload = _request_json(
            f"{ingress_base_url}{webhook_path}",
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            body=send_update,
            method="POST",
        )
        if status != 200:
            raise SystemExit(f"telegram send command failed: {status} {payload}")
        state = _fake_state(fake_base_url)
        expected_sent_messages += 2
        expected_send_attempts += 2
        _assert(
            len(state["sent_messages"]) == expected_sent_messages,
            f"send command should add alias delivery and sender acknowledgement: {state}",
        )
        recent_messages = state["sent_messages"][-2:]
        _assert(
            {message["chat_id"] for message in recent_messages}
            == {trusted_chat_id, alias_chat_id},
            f"send command used unexpected telegram targets: {state}",
        )
        alias_delivery = next(
            message for message in recent_messages if message["chat_id"] == alias_chat_id
        )
        _assert(alias_delivery["text"] == send_text, f"unexpected alias delivery body: {state}")
        sender_ack = next(
            message for message in recent_messages if message["chat_id"] == trusted_chat_id
        )
        _assert(alias_name in sender_ack["text"], f"sender acknowledgement missing alias: {state}")

        untrusted_update = {
            "update_id": run_id + 22,
            "message": {
                "message_id": run_id + 122,
                "chat": {"id": untrusted_chat_id},
                "from": {"id": 2234, "is_bot": False},
                "text": "Should be rejected",
            },
        }
        status, payload = _request_json(
            f"{ingress_base_url}{webhook_path}",
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            body=untrusted_update,
            method="POST",
        )
        if status != 200:
            raise SystemExit(f"telegram untrusted rejection path failed: {status} {payload}")
        state = _fake_state(fake_base_url)
        expected_sent_messages += 1
        expected_send_attempts += 1
        _assert(
            len(state["sent_messages"]) == expected_sent_messages,
            f"untrusted chat should add one bounded rejection reply: {state}",
        )
        untrusted_message = state["sent_messages"][-1]
        _assert(untrusted_message["chat_id"] == untrusted_chat_id, f"unexpected untrusted chat: {state}")
        _assert(
            "not authorized for household assistant access" in untrusted_message["text"],
            f"unexpected untrusted rejection text: {state}",
        )

    denied_command_update = {
        "update_id": run_id + 3,
        "message": {
            "message_id": run_id + 103,
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
    _assert(
        len(state["sent_messages"]) == expected_sent_messages,
        f"denied command should not send telegram replies: {state}",
    )

    status, payload = _request_json(
        f"{fake_base_url}/test/fail-next-send",
        body={"status_code": 503, "description": "simulated-send-failure"},
        method="POST",
    )
    if status != 200:
        raise SystemExit(f"failed to arm telegram send failure: {status} {payload}")

    retry_update = {
        "update_id": run_id + 4,
        "message": {
            "message_id": run_id + 104,
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
    expected_send_attempts += 1
    _assert(
        len(state["sent_messages"]) == expected_sent_messages,
        f"failed send should not add successful messages: {state}",
    )
    _assert(
        len(state["send_attempts"]) == expected_send_attempts,
        f"expected one extra failed send attempt: {state}",
    )

    status, payload = _request_json(
        f"{ingress_base_url}{webhook_path}",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        body=retry_update,
        method="POST",
    )
    if status != 200:
        raise SystemExit(f"retry after downstream failure did not recover: {status} {payload}")
    state = _fake_state(fake_base_url)
    expected_sent_messages += 1
    expected_send_attempts += 1
    _assert(
        len(state["sent_messages"]) == expected_sent_messages,
        f"retry should add a successful message: {state}",
    )
    _assert(
        len(state["send_attempts"]) == expected_send_attempts,
        f"retry should create a new send attempt: {state}",
    )
    retry_message = state["sent_messages"][-1]
    _assert(retry_message["chat_id"] == chat_id, f"unexpected retry chat id: {state}")
    _assert(bool(retry_message["text"].strip()), f"retry reply should be non-empty: {state}")

    status, payload = _request_json(f"{fake_base_url}/test/reset", body={}, method="POST")
    if status != 200:
        raise SystemExit(f"fake telegram reset before alert policy checks failed: {status} {payload}")

    status, payload = _request_json(
        f"{ingress_base_url}/telegram/alerts",
        headers={"X-Telegram-Alert-Token": "wrong-alert-token"},
        body={"text": "alert auth should fail"},
        method="POST",
    )
    _assert(status == 401, f"expected alert auth failure 401, got {status} {payload}")
    state = _fake_state(fake_base_url)
    _assert(not state["sent_messages"], f"alert auth failure should not send telegram messages: {state}")

    critical_alert = {
        "status": "firing",
        "alerts": [
            {
                "labels": {
                    "alertname": "telegram_ingress_down",
                    "severity": "critical",
                    "service": "telegram-ingress",
                },
                "annotations": {
                    "description": "Ingress health failed",
                },
            }
        ],
    }
    expected_alert_recipients = {
        *alert_default_chat_ids,
        *alert_warning_chat_ids,
        *alert_critical_chat_ids,
    }
    alert_idempotency_key = "smoke-critical-alert-1"

    status, payload = _request_json(
        f"{fake_base_url}/test/fail-next-send",
        body={
            "status_code": 429,
            "description": "simulated-alert-rate-limit",
            "retry_after": 4,
        },
        method="POST",
    )
    if status != 200:
        raise SystemExit(f"failed to arm alert send failure: {status} {payload}")

    status, payload = _request_json(
        f"{ingress_base_url}/telegram/alerts",
        headers={
            "X-Telegram-Alert-Token": alert_token,
            "X-Telegram-Alert-Idempotency-Key": alert_idempotency_key,
        },
        body=critical_alert,
        method="POST",
    )
    _assert(status == 202, f"expected accepted alert payload, got {status} {payload}")
    _assert(payload.get("status") == "accepted", f"unexpected accepted alert payload: {payload}")
    _assert(payload.get("deduplicated") is False, f"unexpected accepted dedupe flag: {payload}")
    _assert(
        payload.get("recipients") == len(expected_alert_recipients),
        f"unexpected alert recipient count: {payload}",
    )
    time.sleep(1.5)
    state = _fake_state(fake_base_url)
    _assert(
        len(state["sent_messages"]) == len(expected_alert_recipients) - 1,
        f"alert retry should wait for Telegram retry_after before final delivery: {state}",
    )
    _assert(
        len(state["send_attempts"]) == len(expected_alert_recipients),
        f"alert retry should not create an extra attempt before retry_after: {state}",
    )
    _, state = _wait_for_success(
        request_fn=lambda: (200, _fake_state(fake_base_url)),
        success_predicate=lambda _, state: len(state["sent_messages"]) == len(expected_alert_recipients),
        timeout_seconds=30.0,
        error_context="telegram alert retry did not complete before timeout",
    )
    _assert(
        len(state["sent_messages"]) == len(expected_alert_recipients),
        f"unexpected alert sent state: {state}",
    )
    _assert(
        len(state["send_attempts"]) == len(expected_alert_recipients) + 1,
        f"unexpected alert attempt count after retry: {state}",
    )
    sent_alert_chats = {message["chat_id"] for message in state["sent_messages"]}
    _assert(
        sent_alert_chats == expected_alert_recipients,
        f"unexpected alert chat ids in fake state: {state}",
    )
    for message in state["sent_messages"]:
        _assert(message["bot_token"] == alert_bot_token, f"unexpected alert bot token in fake state: {state}")
        _assert("[critical]" in message["text"], f"critical alert text missing severity marker: {state}")

    status, payload = _request_json(
        f"{ingress_base_url}/telegram/alerts",
        headers={
            "X-Telegram-Alert-Token": alert_token,
            "X-Telegram-Alert-Idempotency-Key": alert_idempotency_key,
        },
        body=critical_alert,
        method="POST",
    )
    _assert(status == 200, f"expected deduplicated alert replay 200, got {status} {payload}")
    _assert(payload.get("status") == "sent", f"unexpected deduplicated alert payload: {payload}")
    _assert(payload.get("deduplicated") is True, f"expected deduplicated alert replay: {payload}")
    replay_state = _fake_state(fake_base_url)
    _assert(
        replay_state["sent_messages"] == state["sent_messages"],
        f"deduplicated replay should not send new messages: {replay_state}",
    )
    _assert(
        replay_state["send_attempts"] == state["send_attempts"],
        f"deduplicated replay should not create new send attempts: {replay_state}",
    )

    resolved_alert = {
        "status": "resolved",
        "alerts": [
            {
                "labels": {
                    "alertname": "telegram_ingress_down",
                    "severity": "warning",
                    "service": "telegram-ingress",
                },
                "annotations": {
                    "description": "Ingress recovered",
                },
            }
        ],
    }
    status, payload = _request_json(
        f"{ingress_base_url}/telegram/alerts",
        headers={"X-Telegram-Alert-Token": alert_token},
        body=resolved_alert,
        method="POST",
    )
    if status != 200:
        raise SystemExit(f"telegram resolved alert policy check failed: {status} {payload}")
    _assert(
        payload == {
            "status": "ignored",
            "reason": "alert_policy_filtered",
            "matched_alerts": 0,
        },
        f"unexpected resolved alert policy payload: {payload}",
    )
    state = _fake_state(fake_base_url)
    _assert(
        len(state["sent_messages"]) == len(expected_alert_recipients),
        f"resolved alert should not add sent messages: {state}",
    )

    print("Telegram ingress smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
