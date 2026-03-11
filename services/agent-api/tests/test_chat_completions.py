import httpx

from app.api import deps
from app.core.errors import APIError
from app.repositories.postgres import ChatPersistenceResult, ConversationContext


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str]):
        self.status_code = status_code
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def iter_lines(self):
        yield from self._lines


class _FakeClient:
    response = _FakeResponse(
        200,
        {
            "message": {"role": "assistant", "content": "Runtime response"},
            "prompt_eval_count": 11,
            "eval_count": 7,
        },
    )
    stream_response = _FakeStreamResponse(
        200,
        [
            '{"message":{"role":"assistant","content":"Runtime "},"done":false}',
            '{"message":{"role":"assistant","content":"response"},"done":true,"prompt_eval_count":11,"eval_count":7}',
        ],
    )
    error = None
    stream_error = None
    last_url = None
    last_json = None
    last_stream_url = None
    last_stream_json = None

    def __init__(self, *args, **kwargs):
        _ = args, kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def post(self, url, json):
        _FakeClient.last_url = url
        _FakeClient.last_json = json
        if _FakeClient.error is not None:
            raise _FakeClient.error
        return _FakeClient.response

    def stream(self, method, url, json):
        _FakeClient.last_stream_url = url
        _FakeClient.last_stream_json = json
        if _FakeClient.stream_error is not None:
            raise _FakeClient.stream_error
        return _FakeClient.stream_response

    def get(self, url):
        raise AssertionError("Unexpected GET in chat completion test")


def _patch_http_client(monkeypatch):
    monkeypatch.setattr("app.clients.ollama.httpx.Client", _FakeClient)
    _FakeClient.error = None
    _FakeClient.stream_error = None
    _FakeClient.last_url = None
    _FakeClient.last_json = None
    _FakeClient.last_stream_url = None
    _FakeClient.last_stream_json = None
    deps.get_ollama_client.cache_clear()


class _FakeRepository:
    def __init__(
        self,
        error: APIError | None = None,
        prepare_error: APIError | None = None,
    ):
        self.error = error
        self.prepare_error = prepare_error
        self.prepare_calls = []
        self.success_calls = []
        self.failed_calls = []

    def prepare_conversation(self, **kwargs):
        self.prepare_calls.append(kwargs)
        if self.prepare_error is not None:
            raise self.prepare_error
        conversation_id = kwargs.get("conversation_id_hint") or "conv_test"
        return ConversationContext(
            conversation_id=conversation_id,
            existing_message_count=0,
            conversation_created=conversation_id == "conv_test",
        )

    def record_successful_completion(self, **kwargs):
        self.success_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return ChatPersistenceResult(
            conversation_id=kwargs.get("conversation_id_hint") or "conv_test",
            assistant_message_id="msg_test",
            model_run_id="run_test",
        )

    def record_failed_completion(self, **kwargs):
        self.failed_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return ChatPersistenceResult(
            conversation_id=kwargs.get("conversation_id_hint") or "conv_test",
            assistant_message_id=None,
            model_run_id="run_test",
        )


def _chat_payload(
    stream: bool = False,
    metadata: dict[str, str] | None = None,
) -> dict:
    payload = {
        "model": "assistant-v1",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": stream,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def test_chat_completions_non_streaming_success(client, monkeypatch, auth_headers) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    _FakeClient.error = None
    _FakeClient.stream_error = None
    _FakeClient.response = _FakeResponse(
        200,
        {
            "message": {"role": "assistant", "content": "Runtime response"},
            "prompt_eval_count": 11,
            "eval_count": 7,
        },
    )

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "assistant-v1"
    assert body["choices"][0]["message"]["content"] == "Runtime response"
    assert body["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }
    assert response.headers["x-conversation-id"] == "conv_test"
    assert _FakeClient.last_url == "http://ollama.test/api/chat"
    assert _FakeClient.last_json["model"] == "qwen3:8b"
    assert _FakeClient.last_json["stream"] is False
    assert len(repository.success_calls) == 1
    assert repository.success_calls[0]["request_id"].startswith("req_")
    assert repository.success_calls[0]["public_model"] == "assistant-v1"
    assert repository.success_calls[0]["runtime_model"] == "qwen3:8b"
    assert repository.success_calls[0]["response_content"] == "Runtime response"
    assert repository.success_calls[0]["conversation_id_hint"] is None


def test_chat_completions_streaming_success(client, monkeypatch, auth_headers) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    _FakeClient.stream_error = None
    _FakeClient.stream_response = _FakeStreamResponse(
        200,
        [
            '{"message":{"role":"assistant","content":"Runtime "},"done":false}',
            '{"message":{"role":"assistant","content":"response"},"done":true,"prompt_eval_count":11,"eval_count":7}',
        ],
    )

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(stream=True),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-conversation-id"] == "conv_test"
    assert '"content": "Runtime "' in response.text or '"content":"Runtime "' in response.text
    assert '"content": "response"' in response.text or '"content":"response"' in response.text
    assert "[DONE]" in response.text
    assert _FakeClient.last_stream_url == "http://ollama.test/api/chat"
    assert _FakeClient.last_stream_json["stream"] is True
    assert len(repository.prepare_calls) == 1
    assert len(repository.success_calls) == 1
    assert repository.success_calls[0]["response_content"] == "Runtime response"
    assert repository.success_calls[0]["conversation_id_hint"] == "conv_test"


def test_chat_completions_streaming_runtime_unavailable_before_first_chunk(
    client, monkeypatch, auth_headers
) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    request = httpx.Request("POST", "http://ollama.test/api/chat")
    _FakeClient.stream_error = httpx.ConnectError("boom", request=request)

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(stream=True),
        headers=auth_headers,
    )

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "dependency_unavailable"
    assert response.json()["error"]["code"] == "runtime_unavailable"
    assert len(repository.prepare_calls) == 1
    assert len(repository.failed_calls) == 1
    assert repository.failed_calls[0]["conversation_id_hint"] == "conv_test"


def test_chat_completions_header_conversation_hint(client, monkeypatch, auth_headers) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    _FakeClient.error = None
    _FakeClient.response = _FakeResponse(
        200,
        {"message": {"role": "assistant", "content": "Runtime response"}},
    )

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(),
        headers={**auth_headers, "X-Conversation-ID": "conv_existing"},
    )

    assert response.status_code == 200
    assert repository.success_calls[0]["conversation_id_hint"] == "conv_existing"


def test_chat_completions_metadata_conversation_hint(client, monkeypatch, auth_headers) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    _FakeClient.error = None
    _FakeClient.response = _FakeResponse(
        200,
        {"message": {"role": "assistant", "content": "Runtime response"}},
    )

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(metadata={"conversation_id": "conv_meta"}),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert repository.success_calls[0]["conversation_id_hint"] == "conv_meta"


def test_chat_completions_unknown_profile(client, monkeypatch, auth_headers) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    payload = _chat_payload()
    payload["model"] = "unknown-model"

    response = client.post("/v1/chat/completions", json=payload, headers=auth_headers)

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "unknown_profile"


def test_chat_completions_invalid_request(client, monkeypatch, auth_headers) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository

    response = client.post(
        "/v1/chat/completions",
        json={"messages": []},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "invalid_request"


def test_chat_completions_runtime_unavailable(client, monkeypatch, auth_headers) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    request = httpx.Request("POST", "http://ollama.test/api/chat")
    _FakeClient.error = httpx.ConnectError("boom", request=request)

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "dependency_unavailable"
    assert response.json()["error"]["code"] == "runtime_unavailable"
    assert len(repository.failed_calls) == 1
    assert repository.failed_calls[0]["error_code"] == "runtime_unavailable"


def test_chat_completions_upstream_bad_payload(client, monkeypatch, auth_headers) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    _FakeClient.error = None
    _FakeClient.response = _FakeResponse(200, {"unexpected": "shape"})

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "upstream_error"
    assert response.json()["error"]["code"] == "dependency_bad_response"
    assert len(repository.failed_calls) == 1
    assert repository.failed_calls[0]["error_code"] == "dependency_bad_response"


def test_chat_completions_storage_unavailable(client, monkeypatch, auth_headers) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository(
        error=APIError(
            status_code=503,
            error_type="dependency_unavailable",
            code="storage_unavailable",
            message="Persistent storage unavailable",
        )
    )
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    _FakeClient.error = None
    _FakeClient.response = _FakeResponse(
        200,
        {"message": {"role": "assistant", "content": "Runtime response"}},
    )

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "dependency_unavailable"
    assert response.json()["error"]["code"] == "storage_unavailable"


def test_chat_completions_conversation_mismatch(client, monkeypatch, auth_headers) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository(
        error=APIError(
            status_code=409,
            error_type="validation_error",
            code="conversation_mismatch",
            message="Conversation hint does not match request transcript",
        )
    )
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    _FakeClient.error = None
    _FakeClient.response = _FakeResponse(
        200,
        {"message": {"role": "assistant", "content": "Runtime response"}},
    )

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(),
        headers={**auth_headers, "X-Conversation-ID": "conv_wrong"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "conversation_mismatch"


def test_chat_completions_prepare_conversation_mismatch(
    client, monkeypatch, auth_headers
) -> None:
    _patch_http_client(monkeypatch)
    repository = _FakeRepository(
        prepare_error=APIError(
            status_code=409,
            error_type="validation_error",
            code="conversation_mismatch",
            message="Conversation hint does not match request transcript",
        )
    )
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(stream=True),
        headers={**auth_headers, "X-Conversation-ID": "conv_wrong"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "conversation_mismatch"
