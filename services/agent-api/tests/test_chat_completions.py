import httpx
import pytest

from app.api import deps
from app.clients.ollama import OllamaChatStreamChunk
from app.core.config import get_settings
from app.core.errors import APIError
from app.clients.spotify import SpotifyPlaylistItem, SpotifyTrackItem
from app.repositories.postgres import (
    ChatPersistenceResult,
    ConversationContext,
    MemorySearchHit,
    PersistedMessage,
    ToolExecutionRecord,
)
from app.schemas.chat import ChatCompletionRequest
from app.services.chat import ChatService


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
    embed_response = _FakeResponse(
        200,
        {"embeddings": [[1.0, 0.0]]},
    )
    embed_error = None
    last_url = None
    last_json = None
    last_stream_url = None
    last_stream_json = None
    chat_calls = []
    stream_calls = []
    response_queue = []
    stream_response_queue = []
    embed_calls = []

    def __init__(self, *args, **kwargs):
        _ = args, kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def post(self, url, json):
        if url.endswith("/api/embed"):
            _FakeClient.embed_calls.append({"url": url, "json": json})
            if _FakeClient.embed_error is not None:
                raise _FakeClient.embed_error
            return _FakeClient.embed_response
        _FakeClient.last_url = url
        _FakeClient.last_json = json
        _FakeClient.chat_calls.append({"url": url, "json": json})
        if _FakeClient.error is not None:
            raise _FakeClient.error
        if _FakeClient.response_queue:
            return _FakeClient.response_queue.pop(0)
        return _FakeClient.response

    def stream(self, method, url, json):
        _FakeClient.last_stream_url = url
        _FakeClient.last_stream_json = json
        _FakeClient.stream_calls.append({"method": method, "url": url, "json": json})
        if _FakeClient.stream_error is not None:
            raise _FakeClient.stream_error
        if _FakeClient.stream_response_queue:
            return _FakeClient.stream_response_queue.pop(0)
        return _FakeClient.stream_response

    def get(self, url):
        raise AssertionError("Unexpected GET in chat completion test")


class _FakeSearchClient:
    results = []
    error = None
    calls = []

    def search(self, *, query: str, limit: int):
        _FakeSearchClient.calls.append({"query": query, "limit": limit})
        if _FakeSearchClient.error is not None:
            raise _FakeSearchClient.error
        return list(_FakeSearchClient.results)


class _FakeSpotifyClient:
    search_results = []
    playlist_results = []
    error = None
    list_calls = []
    search_calls = []
    play_calls = []
    play_playlist_calls = []
    start_station_calls = []
    pause_calls = []
    next_calls = []

    def search_tracks(self, *, query: str, limit: int):
        _FakeSpotifyClient.search_calls.append({"query": query, "limit": limit})
        if _FakeSpotifyClient.error is not None:
            raise _FakeSpotifyClient.error
        return list(_FakeSpotifyClient.search_results)

    def list_playlists(self, *, limit: int):
        _FakeSpotifyClient.list_calls.append({"limit": limit})
        if _FakeSpotifyClient.error is not None:
            raise _FakeSpotifyClient.error
        return list(_FakeSpotifyClient.playlist_results)

    def play_track(self, *, track_uri: str, device_id: str | None = None):
        _FakeSpotifyClient.play_calls.append(
            {"track_uri": track_uri, "device_id": device_id}
        )
        if _FakeSpotifyClient.error is not None:
            raise _FakeSpotifyClient.error

    def play_playlist(self, *, playlist_uri: str, device_id: str | None = None):
        _FakeSpotifyClient.play_playlist_calls.append(
            {"playlist_uri": playlist_uri, "device_id": device_id}
        )
        if _FakeSpotifyClient.error is not None:
            raise _FakeSpotifyClient.error

    def start_station(
        self,
        *,
        seed_kind: str,
        seed_value: str,
        limit: int,
        device_id: str | None = None,
    ):
        _FakeSpotifyClient.start_station_calls.append(
            {
                "seed_kind": seed_kind,
                "seed_value": seed_value,
                "limit": limit,
                "device_id": device_id,
            }
        )
        if _FakeSpotifyClient.error is not None:
            raise _FakeSpotifyClient.error

    def pause_playback(self, *, device_id: str | None = None):
        _FakeSpotifyClient.pause_calls.append({"device_id": device_id})
        if _FakeSpotifyClient.error is not None:
            raise _FakeSpotifyClient.error

    def next_track(self, *, device_id: str | None = None):
        _FakeSpotifyClient.next_calls.append({"device_id": device_id})
        if _FakeSpotifyClient.error is not None:
            raise _FakeSpotifyClient.error


class _FakeTelegramClient:
    calls = []
    error = None

    def send_message(self, *, chat_id: int, text: str):
        _FakeTelegramClient.calls.append({"chat_id": chat_id, "text": text})
        if _FakeTelegramClient.error is not None:
            raise _FakeTelegramClient.error


def _patch_http_client(monkeypatch):
    monkeypatch.setattr("app.clients.ollama.httpx.Client", _FakeClient)
    _FakeClient.error = None
    _FakeClient.stream_error = None
    _FakeClient.embed_error = None
    _FakeClient.last_url = None
    _FakeClient.last_json = None
    _FakeClient.last_stream_url = None
    _FakeClient.last_stream_json = None
    _FakeClient.chat_calls = []
    _FakeClient.stream_calls = []
    _FakeClient.response_queue = []
    _FakeClient.stream_response_queue = []
    _FakeClient.embed_calls = []
    deps.get_ollama_client.cache_clear()


def _patch_search_client():
    _FakeSearchClient.results = []
    _FakeSearchClient.error = None
    _FakeSearchClient.calls = []
    deps.get_web_search_client.cache_clear()


def _patch_spotify_client():
    _FakeSpotifyClient.search_results = []
    _FakeSpotifyClient.playlist_results = []
    _FakeSpotifyClient.error = None
    _FakeSpotifyClient.list_calls = []
    _FakeSpotifyClient.search_calls = []
    _FakeSpotifyClient.play_calls = []
    _FakeSpotifyClient.play_playlist_calls = []
    _FakeSpotifyClient.start_station_calls = []
    _FakeSpotifyClient.pause_calls = []
    _FakeSpotifyClient.next_calls = []
    deps.get_spotify_client.cache_clear()


def _patch_telegram_client():
    _FakeTelegramClient.calls = []
    _FakeTelegramClient.error = None
    deps.get_telegram_client.cache_clear()


class _FakeRepository:
    def __init__(
        self,
        error: APIError | None = None,
        prepare_error: APIError | None = None,
        memory_hits: list[MemorySearchHit] | None = None,
        memory_error: APIError | None = None,
    ):
        self.error = error
        self.prepare_error = prepare_error
        self.memory_hits = memory_hits or []
        self.memory_error = memory_error
        self.prepare_calls = []
        self.memory_lookup_calls = []
        self.success_calls = []
        self.failed_calls = []
        self.retrieval_calls = []
        self.store_memory_calls = []
        self.tool_execution_calls = []
        self.pending_confirmations = {}
        self.pending_create_calls = []
        self.pending_resolve_calls = []
        self.pending_clarification_calls = []

    def prepare_conversation(self, **kwargs):
        self.prepare_calls.append(kwargs)
        if self.prepare_error is not None:
            raise self.prepare_error
        conversation_id = kwargs.get("conversation_id_hint") or "conv_test"
        return ConversationContext(
            conversation_id=conversation_id,
            existing_message_count=0,
            matched_request_message_count=0,
            conversation_created=conversation_id == "conv_test",
        )

    def record_successful_completion(self, **kwargs):
        self.success_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        request_messages = tuple(
            PersistedMessage(
                message_id=f"msg_req_{index}",
                message_index=index,
                role=message.role,
                content=message.content,
                source="request_transcript",
            )
            for index, message in enumerate(kwargs["request_messages"])
        )
        assistant_message = PersistedMessage(
            message_id="msg_test",
            message_index=len(kwargs["request_messages"]),
            role="assistant",
            content=kwargs["response_content"],
            source="assistant_response",
        )
        return ChatPersistenceResult(
            conversation_id=kwargs.get("conversation_id_hint") or "conv_test",
            assistant_message_id="msg_test",
            model_run_id="run_test",
            persisted_messages=(*request_messages, assistant_message),
        )

    def record_failed_completion(self, **kwargs):
        self.failed_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        request_messages = tuple(
            PersistedMessage(
                message_id=f"msg_req_{index}",
                message_index=index,
                role=message.role,
                content=message.content,
                source="request_transcript",
            )
            for index, message in enumerate(kwargs["request_messages"])
        )
        return ChatPersistenceResult(
            conversation_id=kwargs.get("conversation_id_hint") or "conv_test",
            assistant_message_id=None,
            model_run_id="run_test",
            persisted_messages=request_messages,
        )

    def retrieve_memory(self, **kwargs):
        self.memory_lookup_calls.append(kwargs)
        if self.memory_error is not None:
            raise self.memory_error
        return list(self.memory_hits)

    def record_retrieval(self, **kwargs):
        self.retrieval_calls.append(kwargs)

    def store_memory_items(self, **kwargs):
        self.store_memory_calls.append(kwargs)

    def record_tool_execution(self, **kwargs):
        self.tool_execution_calls.append(kwargs)

    def get_active_pending_tool_confirmation(self, *, conversation_id: str):
        return self.pending_confirmations.get(conversation_id)

    def replace_pending_tool_confirmation(self, **kwargs):
        from app.persistence.models import PendingToolConfirmationRecord

        self.pending_create_calls.append(kwargs)
        record = PendingToolConfirmationRecord(
            confirmation_id=kwargs["confirmation_id"],
            conversation_id=kwargs["conversation_id"],
            request_id=kwargs["request_id"],
            source_class=kwargs["source_class"],
            tool_name=kwargs["tool_name"],
            status="pending",
            clarification_count=0,
            arguments=dict(kwargs["arguments"]),
            created_at=kwargs["created_at"],
            expires_at=kwargs["expires_at"],
            resolved_at=None,
        )
        self.pending_confirmations[kwargs["conversation_id"]] = record
        return record

    def resolve_pending_tool_confirmation(self, **kwargs):
        from app.persistence.models import PendingToolConfirmationRecord

        self.pending_resolve_calls.append(kwargs)
        current = self.pending_confirmations.get(kwargs["conversation_id"])
        if current is None or current.confirmation_id != kwargs["confirmation_id"]:
            return None
        resolved = PendingToolConfirmationRecord(
            confirmation_id=current.confirmation_id,
            conversation_id=current.conversation_id,
            request_id=current.request_id,
            source_class=current.source_class,
            tool_name=current.tool_name,
            status=kwargs["status"],
            clarification_count=current.clarification_count,
            arguments=dict(current.arguments),
            created_at=current.created_at,
            expires_at=current.expires_at,
            resolved_at=kwargs["resolved_at"],
        )
        if kwargs["status"] == "executing":
            self.pending_confirmations[kwargs["conversation_id"]] = resolved
        else:
            self.pending_confirmations.pop(kwargs["conversation_id"], None)
        return resolved

    def increment_pending_tool_confirmation_clarification(self, **kwargs):
        from app.persistence.models import PendingToolConfirmationRecord

        self.pending_clarification_calls.append(kwargs)
        current = self.pending_confirmations.get(kwargs["conversation_id"])
        if current is None or current.confirmation_id != kwargs["confirmation_id"]:
            return None
        updated = PendingToolConfirmationRecord(
            confirmation_id=current.confirmation_id,
            conversation_id=current.conversation_id,
            request_id=current.request_id,
            source_class=current.source_class,
            tool_name=current.tool_name,
            status=current.status,
            clarification_count=current.clarification_count + 1,
            arguments=dict(current.arguments),
            created_at=current.created_at,
            expires_at=current.expires_at,
            resolved_at=current.resolved_at,
        )
        self.pending_confirmations[kwargs["conversation_id"]] = updated
        return updated


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


def test_chat_completions_non_streaming_web_search_augments_runtime_prompt(
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
    _FakeSearchClient.results = [
        {
            "title": "OpenAI API changelog",
            "url": "https://example.test/changelog",
            "snippet": "Latest API updates and release notes.",
        }
    ]

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(metadata={"web_search": "true"}),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert _FakeSearchClient.calls == [{"query": "Hello", "limit": 3}]
    runtime_messages = _FakeClient.last_json["messages"]
    assert runtime_messages[0]["role"] == "system"
    assert "Relevant web search results" in runtime_messages[0]["content"]
    assert "OpenAI API changelog" in runtime_messages[0]["content"]
    assert "https://example.test/changelog" in runtime_messages[0]["content"]
    assert runtime_messages[1:] == [{"role": "user", "content": "Hello"}]
    assert len(repository.tool_execution_calls) == 1
    assert repository.tool_execution_calls[0]["conversation_id"] == "conv_test"
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert isinstance(tool_execution, ToolExecutionRecord)
    assert tool_execution.tool_name == "web-search"
    assert tool_execution.status == "completed"
    assert tool_execution.arguments == {"query": "Hello", "limit": 3}
    assert tool_execution.error_code is None


def test_chat_completions_streaming_web_search_augments_runtime_prompt(
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
    _FakeSearchClient.results = [
        {
            "title": "OpenAI API changelog",
            "url": "https://example.test/changelog",
            "snippet": "Latest API updates and release notes.",
        }
    ]

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(stream=True, metadata={"web_search": "true"}),
        headers=auth_headers,
    )

    assert response.status_code == 200
    runtime_messages = _FakeClient.last_stream_json["messages"]
    assert runtime_messages[0]["role"] == "system"
    assert "Relevant web search results" in runtime_messages[0]["content"]
    assert "OpenAI API changelog" in runtime_messages[0]["content"]
    assert len(repository.tool_execution_calls) == 1
    assert repository.tool_execution_calls[0]["tool_execution"].status == "completed"


def test_chat_completions_web_search_failure_degrades_without_breaking_chat(
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
    _FakeSearchClient.error = APIError(
        status_code=504,
        error_type="dependency_unavailable",
        code="dependency_timeout",
        message="Search provider timed out",
    )

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(metadata={"web_search": "true"}),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert _FakeClient.last_json["messages"] == [{"role": "user", "content": "Hello"}]
    assert len(repository.tool_execution_calls) == 1
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.status == "failed"
    assert tool_execution.error_code == "dependency_timeout"
    assert tool_execution.output is None


def test_chat_completions_non_streaming_model_driven_web_search_uses_bounded_two_pass(
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

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "Final answer with cited release notes."
    assert body["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }
    assert len(_FakeClient.chat_calls) == 2
    planning_messages = _FakeClient.chat_calls[0]["json"]["messages"]
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert planning_messages[-1] == {"role": "user", "content": "Hello"}
    assert final_messages[0]["role"] == "system"
    assert "Relevant web search results" in final_messages[0]["content"]
    assert "Assistant release notes" in final_messages[0]["content"]
    assert _FakeSearchClient.calls == [
        {"query": "latest assistant release notes", "limit": 3}
    ]
    assert len(repository.success_calls) == 1
    assert repository.success_calls[0]["response_content"] == (
        "Final answer with cited release notes."
    )
    assert len(repository.tool_execution_calls) == 1
    assert repository.tool_execution_calls[0]["tool_execution"].status == "completed"


def test_chat_completions_streaming_model_driven_web_search_hides_planning_pass(
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
                    "content": '{"tool":"web-search","query":"latest assistant release notes"}',
                },
                "prompt_eval_count": 3,
                "eval_count": 2,
            },
        )
    ]
    _FakeClient.stream_response_queue = [
        _FakeStreamResponse(
            200,
            [
                '{"message":{"role":"assistant","content":"Final "},"done":false}',
                '{"message":{"role":"assistant","content":"response"},"done":true,"prompt_eval_count":11,"eval_count":7}',
            ],
        )
    ]
    _FakeSearchClient.results = [
        {
            "title": "Assistant release notes",
            "url": "https://example.test/releases",
            "snippet": "Latest release notes for the assistant runtime.",
        }
    ]

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(stream=True),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert "[DONE]" in response.text
    assert '{"tool":"web-search"' not in response.text
    assert "Final " in response.text
    assert "response" in response.text
    assert len(_FakeClient.chat_calls) == 1
    assert len(_FakeClient.stream_calls) == 1
    final_messages = _FakeClient.stream_calls[0]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Relevant web search results" in final_messages[0]["content"]
    assert _FakeSearchClient.calls == [
        {"query": "latest assistant release notes", "limit": 3}
    ]
    assert len(repository.tool_execution_calls) == 1
    assert repository.tool_execution_calls[0]["tool_execution"].status == "completed"


def test_chat_completions_model_driven_malformed_tool_json_is_treated_as_final_answer(
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
                    "content": '{"tool":"web-search"',
                },
                "prompt_eval_count": 5,
                "eval_count": 4,
            },
        )
    ]

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == '{"tool":"web-search"'
    assert len(_FakeClient.chat_calls) == 1
    assert _FakeSearchClient.calls == []
    assert repository.tool_execution_calls == []


def test_chat_completions_model_driven_tool_failure_runs_final_fallback_pass(
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
                    "content": "I could not verify fresh results, so this answer uses built-in knowledge.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]
    _FakeSearchClient.error = APIError(
        status_code=504,
        error_type="dependency_unavailable",
        code="dependency_timeout",
        message="Search provider timed out",
    )

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == (
        "I could not verify fresh results, so this answer uses built-in knowledge."
    )
    assert len(_FakeClient.chat_calls) == 2
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Web search was requested but is currently unavailable." in final_messages[0][
        "content"
    ]
    assert _FakeSearchClient.calls == [
        {"query": "latest assistant release notes", "limit": 3}
    ]
    assert len(repository.tool_execution_calls) == 1
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.status == "failed"
    assert tool_execution.error_code == "dependency_timeout"


def test_chat_completions_model_driven_spotify_search_uses_spotify_adapter(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_spotify_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_spotify_client] = (
        lambda: _FakeSpotifyClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": '{"tool":"spotify-search","query":"lofi"}',
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
                    "content": "This answer uses Spotify tracks.",
                },
                "prompt_eval_count": 11,
                "eval_count": 7,
            },
        ),
    ]
    _FakeSpotifyClient.search_results = [
        SpotifyTrackItem(
            name="Calm Piano",
            artists="Piano Studio",
            uri="spotify:track:001",
            album="Focus",
            external_url="https://open.spotify.com/track/001",
        )
    ]

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == (
        "This answer uses Spotify tracks."
    )
    assert len(_FakeClient.chat_calls) == 2
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Relevant Spotify tracks" in final_messages[0]["content"]
    assert "Calm Piano" in final_messages[0]["content"]
    assert _FakeSpotifyClient.search_calls == [{"query": "lofi", "limit": 3}]
    assert len(repository.tool_execution_calls) == 1
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "spotify-search"
    assert tool_execution.status == "completed"
    assert tool_execution.output["results"][0]["uri"] == "spotify:track:001"


def test_chat_completions_model_driven_spotify_play_executes_action(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_spotify_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_spotify_client] = (
        lambda: _FakeSpotifyClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": '{"tool":"spotify-play","track_uri":"spotify:track:001"}',
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
                    "content": "Started playback.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Started playback."
    assert len(_FakeSpotifyClient.play_calls) == 1
    assert _FakeSpotifyClient.play_calls[0]["track_uri"] == "spotify:track:001"
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Spotify action completed: spotify-play." in final_messages[0]["content"]
    assert len(repository.tool_execution_calls) == 1
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "spotify-play"
    assert tool_execution.status == "completed"


def test_chat_completions_model_driven_spotify_playlist_listing_uses_spotify_adapter(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://assistant.test/callback")
    monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_TOP_K", "5")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_spotify_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_spotify_client] = (
        lambda: _FakeSpotifyClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": '{"tool":"spotify-list-playlists"}',
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
                    "content": "Here are your playlists.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]
    _FakeSpotifyClient.playlist_results = [
        SpotifyPlaylistItem(
            name="Focus Flow",
            owner="Alex",
            uri="spotify:playlist:001",
            external_url="https://open.spotify.com/playlist/001",
        )
    ]

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Here are your playlists."
    assert _FakeSpotifyClient.list_calls == [{"limit": 5}]
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Available Spotify playlists" in final_messages[0]["content"]
    assert "Focus Flow" in final_messages[0]["content"]
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "spotify-list-playlists"
    assert tool_execution.status == "completed"


def test_chat_completions_model_driven_spotify_playlist_play_executes_action(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://assistant.test/callback")
    monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_TOP_K", "5")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_spotify_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_spotify_client] = (
        lambda: _FakeSpotifyClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"tool":"spotify-play-playlist","playlist_name":"Focus Flow",'
                        '"device_id":"speaker"}'
                    ),
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
                    "content": "Started your playlist.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]
    _FakeSpotifyClient.playlist_results = [
        SpotifyPlaylistItem(
            name="Focus Flow",
            owner="Alex",
            uri="spotify:playlist:001",
            external_url="https://open.spotify.com/playlist/001",
        )
    ]

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Started your playlist."
    assert _FakeSpotifyClient.play_playlist_calls == [
        {"playlist_uri": "spotify:playlist:001", "device_id": "speaker"}
    ]
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Spotify action completed: spotify-play-playlist." in final_messages[0]["content"]
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "spotify-play-playlist"
    assert tool_execution.status == "completed"


def test_chat_completions_model_driven_spotify_station_executes_action(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://assistant.test/callback")
    monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("SPOTIFY_STATION_TOP_K", "20")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_spotify_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_spotify_client] = (
        lambda: _FakeSpotifyClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"tool":"spotify-start-station","seed_kind":"mood",'
                        '"seed_value":"energy","device_id":"speaker"}'
                    ),
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
                    "content": "Started an energetic station.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == (
        "Started an energetic station."
    )
    assert _FakeSpotifyClient.start_station_calls == [
        {
            "seed_kind": "mood",
            "seed_value": "energy",
            "limit": 20,
            "device_id": "speaker",
        }
    ]
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Spotify action completed: spotify-start-station." in final_messages[0][
        "content"
    ]
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "spotify-start-station"
    assert tool_execution.status == "completed"


def test_chat_completions_model_driven_telegram_alias_listing_augments_prompt(
    client, monkeypatch, auth_headers, tmp_path
) -> None:
    household_path = tmp_path / "household.toml"
    household_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
""".strip()
    )
    monkeypatch.setenv("HOUSEHOLD_CONFIG_PATH", str(household_path))
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": '{"tool":"telegram-list-aliases"}',
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
                    "content": "You can send a message to wife.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == (
        "You can send a message to wife."
    )
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Available Telegram aliases" in final_messages[0]["content"]
    assert "wife" in final_messages[0]["content"]
    assert "chat_id" not in final_messages[0]["content"]
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "telegram-list-aliases"
    assert tool_execution.status == "completed"


def test_chat_completions_model_driven_telegram_send_requires_confirmation(
    client, monkeypatch, auth_headers, tmp_path
) -> None:
    household_path = tmp_path / "household.toml"
    household_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
""".strip()
    )
    monkeypatch.setenv("HOUSEHOLD_CONFIG_PATH", str(household_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-bot-token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_telegram_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_telegram_client] = (
        lambda: _FakeTelegramClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"tool":"telegram-send","alias":"wife","text":"Running late"}'
                    ),
                },
                "prompt_eval_count": 4,
                "eval_count": 2,
            },
        ),
    ]

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["x-conversation-id"] == "conv_test"
    assert response.json()["choices"][0]["message"]["content"] == (
        "Отправить wife сообщение: Running late? Скажи 'да' или 'отмена'."
    )
    assert len(_FakeClient.chat_calls) == 1
    assert _FakeTelegramClient.calls == []
    assert len(repository.pending_create_calls) == 1
    assert repository.pending_confirmations["conv_test"].arguments == {
        "alias": "wife",
        "text": "Running late",
    }
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "telegram-send"
    assert tool_execution.status == "pending_confirmation"


def test_chat_completions_pending_telegram_send_confirm_executes_once(
    client, monkeypatch, auth_headers, tmp_path
) -> None:
    household_path = tmp_path / "household.toml"
    household_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
""".strip()
    )
    monkeypatch.setenv("HOUSEHOLD_CONFIG_PATH", str(household_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-bot-token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_telegram_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_telegram_client] = (
        lambda: _FakeTelegramClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"tool":"telegram-send","alias":"wife","text":"Running late"}'
                    ),
                },
                "prompt_eval_count": 4,
                "eval_count": 2,
            },
        ),
    ]

    first_response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(),
        headers=auth_headers,
    )
    second_response = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "да"}],
            "stream": False,
        },
        headers={**auth_headers, "X-Conversation-ID": "conv_test"},
    )
    third_response = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "да"}],
            "stream": False,
        },
        headers={**auth_headers, "X-Conversation-ID": "conv_test"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["choices"][0]["message"]["content"] == (
        "Сообщение отправлено wife."
    )
    assert _FakeTelegramClient.calls == [{"chat_id": 111111111, "text": "Running late"}]
    assert len(_FakeClient.chat_calls) == 2
    assert third_response.status_code == 200
    assert _FakeTelegramClient.calls == [{"chat_id": 111111111, "text": "Running late"}]


def test_chat_completions_pending_telegram_send_cancel_skips_send(
    client, monkeypatch, auth_headers, tmp_path
) -> None:
    household_path = tmp_path / "household.toml"
    household_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
""".strip()
    )
    monkeypatch.setenv("HOUSEHOLD_CONFIG_PATH", str(household_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-bot-token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_telegram_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_telegram_client] = (
        lambda: _FakeTelegramClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"tool":"telegram-send","alias":"wife","text":"Running late"}'
                    ),
                },
                "prompt_eval_count": 4,
                "eval_count": 2,
            },
        ),
    ]

    first_response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(),
        headers=auth_headers,
    )
    second_response = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "отмена"}],
            "stream": False,
        },
        headers={**auth_headers, "X-Conversation-ID": "conv_test"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["choices"][0]["message"]["content"] == (
        "Отправку отменил."
    )
    assert _FakeTelegramClient.calls == []
    assert repository.pending_confirmations == {}
    assert repository.pending_resolve_calls[-1]["status"] == "cancelled"


def test_chat_completions_pending_telegram_send_unclear_once_then_cancels(
    client, monkeypatch, auth_headers, tmp_path
) -> None:
    household_path = tmp_path / "household.toml"
    household_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
""".strip()
    )
    monkeypatch.setenv("HOUSEHOLD_CONFIG_PATH", str(household_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-bot-token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_telegram_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_telegram_client] = (
        lambda: _FakeTelegramClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"tool":"telegram-send","alias":"wife","text":"Running late"}'
                    ),
                },
                "prompt_eval_count": 4,
                "eval_count": 2,
            },
        ),
    ]

    client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)
    first_unclear = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "может быть"}],
            "stream": False,
        },
        headers={**auth_headers, "X-Conversation-ID": "conv_test"},
    )

    assert first_unclear.status_code == 200
    assert first_unclear.json()["choices"][0]["message"]["content"] == (
        "Подтвердить отправку или отменить? Скажи 'да' или 'отмена'."
    )
    assert repository.pending_confirmations["conv_test"].clarification_count == 1
    second_unclear = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "может быть"}],
            "stream": False,
        },
        headers={**auth_headers, "X-Conversation-ID": "conv_test"},
    )
    assert second_unclear.status_code == 200
    assert second_unclear.json()["choices"][0]["message"]["content"] == (
        "Не получил понятного подтверждения, отправку отменил."
    )
    assert repository.pending_confirmations == {}
    assert _FakeTelegramClient.calls == []


def test_chat_completions_pending_telegram_send_timeout_returns_bounded_reply(
    client, monkeypatch, auth_headers, tmp_path
) -> None:
    from app.persistence.models import PendingToolConfirmationRecord
    from datetime import datetime, timedelta, timezone

    household_path = tmp_path / "household.toml"
    household_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
""".strip()
    )
    monkeypatch.setenv("HOUSEHOLD_CONFIG_PATH", str(household_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-bot-token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_telegram_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_telegram_client] = (
        lambda: _FakeTelegramClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"tool":"telegram-send","alias":"wife","text":"Running late"}'
                    ),
                },
                "prompt_eval_count": 4,
                "eval_count": 2,
            },
        ),
    ]

    client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)
    pending = repository.pending_confirmations["conv_test"]
    repository.pending_confirmations["conv_test"] = PendingToolConfirmationRecord(
        confirmation_id=pending.confirmation_id,
        conversation_id=pending.conversation_id,
        request_id=pending.request_id,
        source_class=pending.source_class,
        tool_name=pending.tool_name,
        status=pending.status,
        clarification_count=pending.clarification_count,
        arguments=dict(pending.arguments),
        created_at=pending.created_at,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        resolved_at=pending.resolved_at,
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "да"}],
            "stream": False,
        },
        headers={**auth_headers, "X-Conversation-ID": "conv_test"},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == (
        "Подтверждение истекло. Попроси отправить сообщение заново."
    )
    assert repository.pending_confirmations == {}
    assert repository.pending_resolve_calls[-1]["status"] == "expired"
    assert _FakeTelegramClient.calls == []


def test_chat_completions_pending_telegram_send_new_request_invalidates_pending(
    client, monkeypatch, auth_headers, tmp_path
) -> None:
    household_path = tmp_path / "household.toml"
    household_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
""".strip()
    )
    monkeypatch.setenv("HOUSEHOLD_CONFIG_PATH", str(household_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-bot-token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_telegram_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_telegram_client] = (
        lambda: _FakeTelegramClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"tool":"telegram-send","alias":"wife","text":"Running late"}'
                    ),
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
                    "content": "Weather is clear.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]

    client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "какая погода"}],
            "stream": False,
        },
        headers={**auth_headers, "X-Conversation-ID": "conv_test"},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Weather is clear."
    assert repository.pending_confirmations == {}
    assert repository.pending_resolve_calls[-1]["status"] == "interrupted"
    assert _FakeTelegramClient.calls == []


def test_chat_completions_model_driven_spotify_pause_executes_action(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_spotify_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_spotify_client] = (
        lambda: _FakeSpotifyClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": '{"tool":"spotify-pause","device_id":"device-123"}',
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
                    "content": "Paused playback.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Paused playback."
    assert len(_FakeSpotifyClient.pause_calls) == 1
    assert _FakeSpotifyClient.pause_calls[0]["device_id"] == "device-123"
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Spotify action completed: spotify-pause." in final_messages[0]["content"]
    assert "device id=device-123" in final_messages[0]["content"]
    assert len(repository.tool_execution_calls) == 1
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "spotify-pause"
    assert tool_execution.status == "completed"


def test_chat_completions_model_driven_spotify_next_executes_action(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_spotify_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_spotify_client] = (
        lambda: _FakeSpotifyClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": '{"tool":"spotify-next"}',
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
                    "content": "Skipped to next track.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Skipped to next track."
    assert len(_FakeSpotifyClient.next_calls) == 1
    assert _FakeSpotifyClient.next_calls[0]["device_id"] is None
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Spotify action completed: spotify-next." in final_messages[0]["content"]
    assert len(repository.tool_execution_calls) == 1
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "spotify-next"
    assert tool_execution.status == "completed"


def test_chat_completions_model_driven_unimplemented_tool_is_denied_with_policy_and_fallback(
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
                    "content": '{"tool":"spotify-play","track_uri":"abc123"}',
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
                    "content": "I cannot perform playback actions in this deployment.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert len(_FakeClient.chat_calls) == 2
    assert _FakeSearchClient.calls == []
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "spotify-play" in final_messages[0]["content"]
    assert "currently unavailable or blocked by policy" in final_messages[0]["content"]
    assert len(repository.tool_execution_calls) == 1
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "spotify-play"
    assert tool_execution.status == "failed"
    assert tool_execution.error_type == "policy_error"
    assert tool_execution.error_code == "tool_not_allowed"


def test_chat_completions_telegram_source_denies_model_driven_web_search(
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
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == (
        "I cannot verify fresh results from Telegram."
    )
    assert len(_FakeClient.chat_calls) == 2
    assert _FakeSearchClient.calls == []
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "Web search was requested but is currently unavailable." in final_messages[0][
        "content"
    ]
    assert len(repository.tool_execution_calls) == 1
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "web-search"
    assert tool_execution.status == "failed"
    assert tool_execution.error_type == "policy_error"
    assert tool_execution.error_code == "tool_not_allowed"


def test_chat_completions_telegram_source_denies_model_driven_spotify_play(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "token")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_spotify_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_spotify_client] = (
        lambda: _FakeSpotifyClient()
    )
    _FakeClient.response_queue = [
        _FakeResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": '{"tool":"spotify-play","track_uri":"spotify:track:001"}',
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
                    "content": "I cannot control playback from Telegram.",
                },
                "prompt_eval_count": 9,
                "eval_count": 6,
            },
        ),
    ]

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(metadata={"source": "telegram"}),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == (
        "I cannot control playback from Telegram."
    )
    assert len(_FakeClient.chat_calls) == 2
    assert _FakeSpotifyClient.play_calls == []
    final_messages = _FakeClient.chat_calls[1]["json"]["messages"]
    assert final_messages[0]["role"] == "system"
    assert "spotify-play" in final_messages[0]["content"]
    assert "currently unavailable or blocked by policy" in final_messages[0]["content"]
    assert len(repository.tool_execution_calls) == 1
    tool_execution = repository.tool_execution_calls[0]["tool_execution"]
    assert tool_execution.tool_name == "spotify-play"
    assert tool_execution.status == "failed"
    assert tool_execution.error_type == "policy_error"
    assert tool_execution.error_code == "tool_not_allowed"


def test_chat_completions_model_driven_unsupported_tool_directive_is_passed_as_content(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    _patch_search_client()
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    _FakeClient.response = _FakeResponse(
        200,
        {
            "message": {
                "role": "assistant",
                "content": '{"tool":"unknown-action","query":"x"}',
            },
            "prompt_eval_count": 11,
            "eval_count": 7,
        },
    )

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload(stream=False),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == (
        '{"tool":"unknown-action","query":"x"}'
    )
    assert len(_FakeClient.chat_calls) == 1
    assert repository.tool_execution_calls == []


def test_chat_completions_non_streaming_memory_retrieval_augments_runtime_prompt(
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

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert len(_FakeClient.embed_calls) == 1
    assert _FakeClient.embed_calls[0]["url"] == "http://ollama.test/api/embed"
    assert _FakeClient.embed_calls[0]["json"] == {
        "model": "all-minilm",
        "input": "Hello",
    }
    runtime_messages = _FakeClient.last_json["messages"]
    assert runtime_messages[0]["role"] == "system"
    assert "Relevant memory from prior conversations" in runtime_messages[0]["content"]
    assert "My favorite color is blue." in runtime_messages[0]["content"]
    assert runtime_messages[1:] == [{"role": "user", "content": "Hello"}]
    assert len(repository.memory_lookup_calls) == 1
    assert len(repository.retrieval_calls) == 1
    assert repository.retrieval_calls[0]["conversation_id"] == "conv_test"
    assert repository.retrieval_calls[0]["retrieval"].status == "completed"
    assert len(repository.retrieval_calls[0]["retrieval"].hits) == 1
    assert len(repository.store_memory_calls) == 0


def test_chat_completions_streaming_memory_retrieval_augments_runtime_prompt(
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
        json=_chat_payload(stream=True),
        headers=auth_headers,
    )

    assert response.status_code == 200
    runtime_messages = _FakeClient.last_stream_json["messages"]
    assert runtime_messages[0]["role"] == "system"
    assert "My favorite color is blue." in runtime_messages[0]["content"]
    assert runtime_messages[1:] == [{"role": "user", "content": "Hello"}]
    assert len(repository.retrieval_calls) == 1
    assert repository.retrieval_calls[0]["retrieval"].status == "completed"


def test_chat_completions_memory_embedding_failure_degrades_without_breaking_chat(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "all-minilm")
    get_settings.cache_clear()
    _patch_http_client(monkeypatch)
    repository = _FakeRepository()
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    request = httpx.Request("POST", "http://ollama.test/api/embed")
    _FakeClient.embed_error = httpx.ConnectError("boom", request=request)

    response = client.post("/v1/chat/completions", json=_chat_payload(), headers=auth_headers)

    assert response.status_code == 200
    assert _FakeClient.last_json["messages"] == [{"role": "user", "content": "Hello"}]
    assert len(repository.retrieval_calls) == 1
    assert repository.retrieval_calls[0]["retrieval"].status == "error"
    assert repository.retrieval_calls[0]["retrieval"].error_code == "runtime_unavailable"
    assert len(repository.store_memory_calls) == 0


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


def test_chat_completions_metadata_client_binding_is_not_treated_as_canonical_hint(
    client, monkeypatch, auth_headers
) -> None:
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
        json=_chat_payload(
            metadata={
                "source": "telegram",
                "client_conversation_id": "telegram:42",
            }
        ),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert repository.success_calls[0]["conversation_id_hint"] is None
    assert repository.success_calls[0]["client_source"] == "telegram"
    assert repository.success_calls[0]["client_conversation_id"] == "telegram:42"


def test_chat_completions_metadata_chat_id_is_not_used_as_canonical_hint(
    client, monkeypatch, auth_headers
) -> None:
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
        json=_chat_payload(metadata={"chat_id": "telegram:42"}),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert repository.success_calls[0]["conversation_id_hint"] is None


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


def test_streaming_chat_completion_raises_after_partial_output_on_runtime_failure() -> None:
    class _StreamingFailureClient:
        def chat(self, model, messages):
            raise AssertionError("Unexpected non-streaming runtime call")

        def stream_chat(self, model, messages):
            yield OllamaChatStreamChunk(content="Runtime ", done=False)
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_unavailable",
                message="Model runtime unavailable",
            )

    repository = _FakeRepository()
    service = ChatService(
        settings=get_settings(),
        ollama_client=_StreamingFailureClient(),
        repository=repository,
    )
    session = service.create_streaming_chat_completion(
        request_id="req_stream_fail",
        request=ChatCompletionRequest.model_validate(_chat_payload(stream=True)),
    )

    first_event = next(session.events)

    assert first_event.content == "Runtime "
    assert first_event.role == "assistant"
    with pytest.raises(APIError) as exc_info:
        next(session.events)

    assert exc_info.value.code == "runtime_unavailable"
    assert len(repository.success_calls) == 0
    assert len(repository.failed_calls) == 1
    assert repository.failed_calls[0]["conversation_id_hint"] == "conv_test"
    assert repository.failed_calls[0]["error_code"] == "runtime_unavailable"
