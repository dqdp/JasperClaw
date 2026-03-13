import json
import logging

from app.api import deps
from app.core.config import get_settings
from app.core.logging import log_event
from app.core.metrics import get_agent_metrics
from app.repositories.postgres import MemorySearchHit
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


def test_metrics_endpoint_exports_chat_request_runtime_and_storage_metrics(
    client, monkeypatch, auth_headers
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

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(),
        headers={**auth_headers, "X-Request-ID": "req_metrics_chat"},
    )
    metrics_response = client.get("/metrics")

    assert response.status_code == 200
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain")
    assert (
        'agent_api_http_request_total{method="POST",path_group="chat_completions",status_class="2xx"} 1'
        in metrics_response.text
    )
    assert (
        'agent_api_chat_runtime_total{outcome="success",phase="final",public_model="assistant-v1"} 1'
        in metrics_response.text
    )
    assert 'agent_api_chat_storage_total{outcome="success"} 1' in metrics_response.text


def test_metrics_endpoint_exports_tool_metrics_for_telegram_policy_denial(
    client, monkeypatch, auth_headers
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
                    "content": '{"tool":"web-search","query":"latest status"}',
                },
                "prompt_eval_count": 4,
                "eval_count": 2,
            },
        ),
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": "I cannot verify fresh results from Telegram.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(metadata={"source": "telegram"}),
        headers={**auth_headers, "X-Request-ID": "req_metrics_tooldeny"},
    )
    metrics_response = client.get("/metrics")

    assert response.status_code == 200
    assert (
        'agent_api_tool_execution_total{error_type="policy_error",outcome="failed",tool_name="web-search"} 1'
        in metrics_response.text
    )
    assert 'agent_api_tool_audit_total{outcome="success"} 1' in metrics_response.text


def test_metrics_endpoint_exports_readiness_and_request_failure_metrics(client) -> None:
    client.app.dependency_overrides[deps.get_readiness_service] = lambda: type(
        "ReadinessStub",
        (),
        {
            "check": lambda self: (
                get_agent_metrics().record_readiness(status="not_ready"),
                ReadinessResult(
                    status="not_ready",
                    checks={"config": "ok", "postgres": "fail", "ollama": "ok"},
                ),
            )[1]
        },
    )()

    response = client.get("/readyz", headers={"X-Request-ID": "req_metrics_readyz"})
    metrics_response = client.get("/metrics")

    assert response.status_code == 503
    assert 'agent_api_readiness_total{status="not_ready"} 1' in metrics_response.text
    assert (
        'agent_api_http_request_total{method="GET",path_group="readyz",status_class="5xx"} 1'
        in metrics_response.text
    )


def test_metrics_endpoint_exports_memory_retrieval_and_materialization_metrics(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "all-minilm")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    repository = _FakeRepository(
        memory_hits=[
            MemorySearchHit(
                memory_item_id="mem_blue",
                source_message_id="msg_old",
                content="My favorite color is blue.",
                score=0.94,
            )
        ]
    )
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(),
        headers={**auth_headers, "X-Request-ID": "req_metrics_memory"},
    )
    metrics_response = client.get("/metrics")

    assert response.status_code == 200
    assert 'agent_api_memory_retrieval_total{outcome="success"} 1' in metrics_response.text
    assert "agent_api_memory_retrieval_hits_total 1" in metrics_response.text
    assert 'agent_api_memory_audit_total{outcome="success"} 1' in metrics_response.text
    assert 'agent_api_memory_materialization_total{outcome="skipped"} 1' in metrics_response.text


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


def test_chat_request_emits_tool_audit_events_for_telegram_tool_denial(
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
                    "content": '{"tool":"web-search","query":"latest status"}',
                },
                "prompt_eval_count": 4,
                "eval_count": 2,
            },
        ),
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": "I cannot verify fresh results from Telegram.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]

    with caplog.at_level(logging.INFO, logger="agent_api"):
        response = client.post(
            "/v1/chat/completions",
            json=_chat_payload(metadata={"source": "telegram"}),
            headers={**auth_headers, "X-Request-ID": "req_tg_tooldeny"},
        )

    assert response.status_code == 200
    events = _events(caplog)

    tool_event = next(event for event in events if event["event"] == "chat_tool_completed")
    assert tool_event["request_id"] == "req_tg_tooldeny"
    assert tool_event["tool_name"] == "web-search"
    assert tool_event["outcome"] == "failed"
    assert tool_event["error_code"] == "tool_not_allowed"

    audit_event = next(
        event for event in events if event["event"] == "chat_tool_audit_completed"
    )
    assert audit_event["request_id"] == "req_tg_tooldeny"
    assert audit_event["tool_name"] == "web-search"
    assert audit_event["tool_status"] == "failed"
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
