import json
import logging

from app.api import deps
from app.core.config import get_settings
from app.core.logging import log_event
from app.services.readiness import ReadinessResult

from tests.test_chat_completions import (
    _FakeClient,
    _FakeRepository,
    _FakeResponse,
    _FakeSearchClient,
    _chat_payload,
    _patch_http_client,
    _patch_search_client,
)


def _events(caplog) -> list[dict]:
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "agent_api"
    ]


def test_chat_request_emits_structured_events(
    client, monkeypatch, caplog, auth_headers
) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    _FakeClient.error = None
    _FakeClient.response = _FakeResponse(
        200,
        {
            "message": {"role": "assistant", "content": "Runtime response"},
            "prompt_eval_count": 11,
            "eval_count": 7,
        },
    )

    with caplog.at_level(logging.INFO, logger="agent_api"):
        response = client.post(
            "/v1/chat/completions",
            json=_chat_payload(),
            headers={**auth_headers, "X-Request-ID": "req_testobs"},
        )

    assert response.status_code == 200
    events = _events(caplog)
    names = [event["event"] for event in events]
    assert "request_started" in names
    assert "chat_runtime_completed" in names
    assert "chat_storage_completed" in names
    assert "request_completed" in names

    runtime_event = next(event for event in events if event["event"] == "chat_runtime_completed")
    assert runtime_event["request_id"] == "req_testobs"
    assert runtime_event["outcome"] == "success"
    assert runtime_event["runtime_model"] == "qwen3:8b"
    assert runtime_event["duration_ms"] >= 0

    storage_event = next(event for event in events if event["event"] == "chat_storage_completed")
    assert storage_event["request_id"] == "req_testobs"
    assert storage_event["outcome"] == "success"


def test_chat_request_emits_tool_events_when_web_search_runs(
    client, monkeypatch, caplog, auth_headers
) -> None:
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_search_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_web_search_client] = (
        lambda: _FakeSearchClient()
    )
    _FakeClient.error = None
    _FakeClient.response = _FakeResponse(
        200,
        {
            "message": {"role": "assistant", "content": "Runtime response"},
            "prompt_eval_count": 11,
            "eval_count": 7,
        },
    )
    _FakeSearchClient.results = [
        {
            "title": "OpenAI API changelog",
            "url": "https://example.test/changelog",
            "snippet": "Latest API updates and release notes.",
        }
    ]

    with caplog.at_level(logging.INFO, logger="agent_api"):
        response = client.post(
            "/v1/chat/completions",
            json=_chat_payload(metadata={"web_search": "true"}),
            headers={**auth_headers, "X-Request-ID": "req_toolobs"},
        )

    assert response.status_code == 200
    events = _events(caplog)
    names = [event["event"] for event in events]
    assert "chat_tool_completed" in names
    assert "chat_tool_audit_completed" in names

    tool_event = next(event for event in events if event["event"] == "chat_tool_completed")
    assert tool_event["request_id"] == "req_toolobs"
    assert tool_event["tool_name"] == "web-search"
    assert tool_event["outcome"] == "completed"

    audit_event = next(
        event for event in events if event["event"] == "chat_tool_audit_completed"
    )
    assert audit_event["request_id"] == "req_toolobs"
    assert audit_event["tool_name"] == "web-search"
    assert audit_event["outcome"] == "success"


def test_chat_request_emits_tool_planning_events_for_model_driven_search(
    client, monkeypatch, caplog, auth_headers
) -> None:
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_search_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_web_search_client] = (
        lambda: _FakeSearchClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": '{"tool":"web-search","query":"latest assistant release notes"}',
                },
                "prompt_eval_count": 3,
                "eval_count": 2,
            },
        ),
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": "Final answer with cited release notes.",
                },
                "prompt_eval_count": 11,
                "eval_count": 7,
            },
        ),
    ]
    _FakeSearchClient.results = [
        {
            "title": "Assistant release notes",
            "url": "https://example.test/releases",
            "snippet": "Latest release notes for the assistant runtime.",
        }
    ]

    with caplog.at_level(logging.INFO, logger="agent_api"):
        response = client.post(
            "/v1/chat/completions",
            json=_chat_payload(),
            headers={**auth_headers, "X-Request-ID": "req_toolplan"},
        )

    assert response.status_code == 200
    events = _events(caplog)
    planning_event = next(
        event for event in events if event["event"] == "chat_tool_planning_completed"
    )
    assert planning_event["request_id"] == "req_toolplan"
    assert planning_event["outcome"] == "tool_requested"
    assert planning_event["tool_name"] == "web-search"

    runtime_events = [
        event for event in events if event["event"] == "chat_runtime_completed"
    ]
    assert [event["phase"] for event in runtime_events] == ["planning", "final"]


def test_readyz_emits_readiness_log(client, caplog) -> None:
    client.app.dependency_overrides[deps.get_readiness_service] = lambda: type(
        "ReadinessStub",
        (),
        {
            "check": lambda self: (
                log_event(
                    "readiness_check_completed",
                    status="ready",
                    checks={"config": "ok", "postgres": "ok", "ollama": "ok"},
                ),
                ReadinessResult(
                    status="ready",
                    checks={"config": "ok", "postgres": "ok", "ollama": "ok"},
                ),
            )[1]
        },
    )()

    with caplog.at_level(logging.INFO, logger="agent_api"):
        response = client.get("/readyz", headers={"X-Request-ID": "req_readyz"})

    assert response.status_code == 200
    events = _events(caplog)
    readiness_event = next(
        event for event in events if event["event"] == "readiness_check_completed"
    )
    assert readiness_event["status"] == "ready"
    assert readiness_event["checks"] == {
        "config": "ok",
        "postgres": "ok",
        "ollama": "ok",
    }
