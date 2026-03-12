from fastapi.testclient import TestClient

from app.main import app


def test_healthz() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_send_message_records_payload_and_exposes_state() -> None:
    client = TestClient(app)
    client.post("/test/reset")

    response = client.post(
        "/botbot-token/sendMessage",
        json={"chat_id": 42, "text": "hello"},
    )

    assert response.status_code == 200
    state = client.get("/test/state")
    assert state.status_code == 200
    payload = state.json()
    assert payload["send_attempts"] == [
        {"bot_token": "bot-token", "chat_id": 42, "text": "hello"}
    ]
    assert payload["sent_messages"] == [
        {"bot_token": "bot-token", "chat_id": 42, "text": "hello"}
    ]


def test_fail_next_send_affects_only_one_attempt() -> None:
    client = TestClient(app)
    client.post("/test/reset")
    client.post(
        "/test/fail-next-send",
        json={"status_code": 503, "description": "simulated-send-failure"},
    )

    failing = client.post(
        "/botbot-token/sendMessage",
        json={"chat_id": 7, "text": "first"},
    )
    succeeding = client.post(
        "/botbot-token/sendMessage",
        json={"chat_id": 7, "text": "second"},
    )

    assert failing.status_code == 503
    assert succeeding.status_code == 200
    state = client.get("/test/state").json()
    assert len(state["send_attempts"]) == 2
    assert state["sent_messages"] == [
        {"bot_token": "bot-token", "chat_id": 7, "text": "second"}
    ]


def test_fail_next_send_can_return_telegram_rate_limit_payload() -> None:
    client = TestClient(app)
    client.post("/test/reset")
    client.post(
        "/test/fail-next-send",
        json={
            "status_code": 429,
            "description": "Too Many Requests: retry later",
            "retry_after": 9,
        },
    )

    response = client.post(
        "/botbot-token/sendMessage",
        json={"chat_id": 7, "text": "first"},
    )

    assert response.status_code == 429
    assert response.json() == {
        "ok": False,
        "error_code": 429,
        "description": "Too Many Requests: retry later",
        "parameters": {"retry_after": 9},
    }
