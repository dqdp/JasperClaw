from collections.abc import Iterator
from datetime import datetime, timezone
import json
import math

from fastapi.testclient import TestClient

from app.api import deps
from app.clients.ollama import OllamaChatResult, OllamaChatStreamChunk
from app.core.config import get_settings
from app.core.errors import APIError
from app.main import app
from app.repositories import PostgresChatRepository


class _TranscribingSttClient:
    def __init__(self, transcripts: list[str]) -> None:
        self._transcripts = list(transcripts)
        self.calls: list[dict[str, object]] = []

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        self.calls.append(
            {
                "audio_bytes": audio_bytes,
                "filename": filename,
                "content_type": content_type,
            }
        )
        if not self._transcripts:
            raise AssertionError("Unexpected extra transcription request")
        return self._transcripts.pop(0)


class _InMemoryTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False


class _InMemoryCursor:
    def __init__(self, connection) -> None:
        self._connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def execute(self, sql, params=None) -> None:
        normalized = " ".join(sql.split())
        if normalized.startswith(
            "SELECT conversation_id FROM client_conversation_bindings WHERE client_source = %s"
        ):
            client_source, client_conversation_id, public_profile = params
            binding = self._connection.client_conversation_bindings.get(
                (client_source, client_conversation_id, public_profile)
            )
            self._rows = (
                [(binding["conversation_id"],)] if binding is not None else []
            )
            return

        if normalized.startswith("SELECT id FROM conversations WHERE public_profile = %s"):
            public_profile = params[0]
            matches = [
                conversation
                for conversation in self._connection.conversations.values()
                if conversation["public_profile"] == public_profile
            ]
            matches.sort(
                key=lambda conversation: (
                    conversation["updated_at"],
                    conversation["created_at"],
                ),
                reverse=True,
            )
            self._rows = [(conversation["id"],) for conversation in matches[:100]]
            return

        if normalized.startswith("SELECT id FROM conversations WHERE id = %s AND public_profile = %s"):
            conversation_id, public_profile = params
            conversation = self._connection.conversations.get(conversation_id)
            if conversation and conversation["public_profile"] == public_profile:
                self._rows = [(conversation["id"],)]
            else:
                self._rows = []
            return

        if normalized.startswith("SELECT role, content FROM messages WHERE conversation_id = %s"):
            conversation_id = params[0]
            rows = [
                (message["role"], message["content"])
                for message in sorted(
                    self._connection.messages,
                    key=lambda message: message["message_index"],
                )
                if message["conversation_id"] == conversation_id
            ]
            self._rows = rows
            return

        if normalized.startswith(
            "INSERT INTO conversations (id, public_profile, created_at, updated_at)"
        ):
            conversation_id, public_profile, created_at, updated_at = params
            self._connection.conversations[conversation_id] = {
                "id": conversation_id,
                "public_profile": public_profile,
                "created_at": created_at,
                "updated_at": updated_at,
            }
            self._rows = []
            return

        if normalized.startswith(
            "INSERT INTO client_conversation_bindings ( client_source, client_conversation_id, public_profile, conversation_id, created_at, updated_at )"
        ):
            (
                client_source,
                client_conversation_id,
                public_profile,
                conversation_id,
                created_at,
                updated_at,
            ) = params
            key = (client_source, client_conversation_id, public_profile)
            binding = self._connection.client_conversation_bindings.get(key)
            if binding is None:
                self._connection.client_conversation_bindings[key] = {
                    "client_source": client_source,
                    "client_conversation_id": client_conversation_id,
                    "public_profile": public_profile,
                    "conversation_id": conversation_id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
                self._rows = [(conversation_id,)]
            else:
                self._rows = [(binding["conversation_id"],)]
            return

        if normalized.startswith("INSERT INTO messages ( id, conversation_id, message_index, role, content, source, created_at )"):
            (
                message_id,
                conversation_id,
                message_index,
                role,
                content,
                source,
                created_at,
            ) = params
            self._connection.messages.append(
                {
                    "id": message_id,
                    "conversation_id": conversation_id,
                    "message_index": message_index,
                    "role": role,
                    "content": content,
                    "source": source,
                    "created_at": created_at,
                }
            )
            self._rows = []
            return

        if normalized.startswith(
            "INSERT INTO model_runs ( id, conversation_id, assistant_message_id, request_id, public_profile, runtime_model, status, error_type, error_code, error_message, prompt_tokens, completion_tokens, total_tokens, started_at, completed_at )"
        ):
            (
                model_run_id,
                conversation_id,
                assistant_message_id,
                request_id,
                public_profile,
                runtime_model,
                status,
                error_type,
                error_code,
                error_message,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                started_at,
                completed_at,
            ) = params
            self._connection.model_runs.append(
                {
                    "id": model_run_id,
                    "conversation_id": conversation_id,
                    "assistant_message_id": assistant_message_id,
                    "request_id": request_id,
                    "public_profile": public_profile,
                    "runtime_model": runtime_model,
                    "status": status,
                    "error_type": error_type,
                    "error_code": error_code,
                    "error_message": error_message,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "started_at": started_at,
                    "completed_at": completed_at,
                }
            )
            self._rows = []
            return

        if normalized.startswith(
            "SELECT id, source_message_id, content, 1 - (embedding <=> %s::vector) AS score FROM memory_items"
        ):
            vector_literal, principal_id, status, _, min_score, _, limit = params
            query_vector = _parse_vector_literal(vector_literal)
            hits = []
            for memory_item in self._connection.memory_items:
                if memory_item["principal_id"] != principal_id:
                    continue
                if memory_item["status"] != status:
                    continue
                score = _cosine_similarity(memory_item["embedding"], query_vector)
                if score < min_score:
                    continue
                hits.append(
                    (
                        memory_item["id"],
                        memory_item["source_message_id"],
                        memory_item["content"],
                        score,
                        memory_item["created_at"],
                    )
                )
            hits.sort(key=lambda hit: (-hit[3], -hit[4].timestamp()))
            self._rows = [(hit[0], hit[1], hit[2], hit[3]) for hit in hits[:limit]]
            return

        if normalized.startswith(
            "INSERT INTO retrieval_runs ( id, conversation_id, request_id, query_text, profile_id, strategy, top_k, status, latency_ms, error_type, error_code, created_at )"
        ):
            (
                retrieval_run_id,
                conversation_id,
                request_id,
                query_text,
                profile_id,
                strategy,
                top_k,
                status,
                latency_ms,
                error_type,
                error_code,
                created_at,
            ) = params
            self._connection.retrieval_runs.append(
                {
                    "id": retrieval_run_id,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "query_text": query_text,
                    "profile_id": profile_id,
                    "strategy": strategy,
                    "top_k": top_k,
                    "status": status,
                    "latency_ms": latency_ms,
                    "error_type": error_type,
                    "error_code": error_code,
                    "created_at": created_at,
                }
            )
            self._rows = []
            return

        if normalized.startswith(
            "INSERT INTO retrieval_hits ( id, retrieval_run_id, memory_item_id, rank, score, included_in_prompt, created_at )"
        ):
            (
                retrieval_hit_id,
                retrieval_run_id,
                memory_item_id,
                rank,
                score,
                included_in_prompt,
                created_at,
            ) = params
            self._connection.retrieval_hits.append(
                {
                    "id": retrieval_hit_id,
                    "retrieval_run_id": retrieval_run_id,
                    "memory_item_id": memory_item_id,
                    "rank": rank,
                    "score": score,
                    "included_in_prompt": included_in_prompt,
                    "created_at": created_at,
                }
            )
            self._rows = []
            return

        if normalized.startswith(
            "INSERT INTO memory_items ( id, principal_id, kind, scope, content, status, source_message_id, conversation_id, embedding, embedding_model, created_at, updated_at )"
        ):
            (
                memory_item_id,
                principal_id,
                kind,
                scope,
                content,
                status,
                source_message_id,
                conversation_id,
                embedding_literal,
                embedding_model,
                created_at,
                updated_at,
            ) = params
            self._connection.memory_items.append(
                {
                    "id": memory_item_id,
                    "principal_id": principal_id,
                    "kind": kind,
                    "scope": scope,
                    "content": content,
                    "status": status,
                    "source_message_id": source_message_id,
                    "conversation_id": conversation_id,
                    "embedding": _parse_vector_literal(embedding_literal),
                    "embedding_model": embedding_model,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
            self._rows = []
            return

        if normalized.startswith(
            "INSERT INTO tool_executions ( id, conversation_id, model_run_id, request_id, tool_name, status, started_at, finished_at, latency_ms, error_type, error_code, request_payload_json, response_payload_json, policy_decision, adapter_name, provider, created_at )"
        ):
            (
                tool_execution_id,
                conversation_id,
                model_run_id,
                request_id,
                tool_name,
                status,
                started_at,
                finished_at,
                latency_ms,
                error_type,
                error_code,
                request_payload_json,
                response_payload_json,
                policy_decision,
                adapter_name,
                provider,
                created_at,
            ) = params
            self._connection.tool_executions.append(
                {
                    "id": tool_execution_id,
                    "conversation_id": conversation_id,
                    "model_run_id": model_run_id,
                    "request_id": request_id,
                    "tool_name": tool_name,
                    "status": status,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "latency_ms": latency_ms,
                    "error_type": error_type,
                    "error_code": error_code,
                    "request_payload_json": json.loads(request_payload_json),
                    "response_payload_json": (
                        json.loads(response_payload_json)
                        if response_payload_json is not None
                        else None
                    ),
                    "policy_decision": policy_decision,
                    "adapter_name": adapter_name,
                    "provider": provider,
                    "created_at": created_at,
                }
            )
            self._rows = []
            return

        if normalized.startswith("UPDATE conversations SET updated_at = %s WHERE id = %s"):
            updated_at, conversation_id = params
            self._connection.conversations[conversation_id]["updated_at"] = updated_at
            self._rows = []
            return

        if normalized.startswith("DELETE FROM conversations WHERE id = %s"):
            conversation_id = params[0]
            self._connection.conversations.pop(conversation_id, None)
            self._rows = []
            return

        raise AssertionError(f"Unexpected SQL: {normalized}")

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _InMemoryConnection:
    def __init__(self) -> None:
        self.conversations: dict[str, dict] = {}
        self.client_conversation_bindings: dict[tuple[str, str, str], dict] = {}
        self.messages: list[dict] = []
        self.model_runs: list[dict] = []
        self.memory_items: list[dict] = []
        self.retrieval_runs: list[dict] = []
        self.retrieval_hits: list[dict] = []
        self.tool_executions: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def transaction(self):
        return _InMemoryTransaction()

    def cursor(self):
        return _InMemoryCursor(self)


class _SuccessfulStreamingClient:
    def chat(self, model, messages):
        raise AssertionError("Unexpected non-streaming runtime call")

    def embed(self, model, input_text):
        raise AssertionError("Unexpected embedding call")

    def stream_chat(self, model, messages) -> Iterator[OllamaChatStreamChunk]:
        _ = model, messages
        yield OllamaChatStreamChunk(content="Runtime ", done=False)
        yield OllamaChatStreamChunk(
            content="response",
            done=True,
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
        )


class _FailingStreamingClient:
    def chat(self, model, messages):
        raise AssertionError("Unexpected non-streaming runtime call")

    def embed(self, model, input_text):
        raise AssertionError("Unexpected embedding call")

    def stream_chat(self, model, messages) -> Iterator[OllamaChatStreamChunk]:
        _ = model, messages
        yield OllamaChatStreamChunk(content="Runtime ", done=False)
        raise APIError(
            status_code=503,
            error_type="dependency_unavailable",
            code="runtime_unavailable",
            message="Model runtime unavailable",
        )


def _payload(stream: bool = True) -> dict:
    return {
        "model": "assistant-v1",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": stream,
    }


def _parse_vector_literal(value: str) -> list[float]:
    return [float(component) for component in value.strip("[]").split(",") if component]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


class _MemoryAwareClient:
    def __init__(self) -> None:
        self.last_chat_messages = None

    def chat(self, model, messages):
        _ = model
        self.last_chat_messages = messages
        return OllamaChatResult(
            content="Runtime response",
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
        )

    def stream_chat(self, model, messages):
        raise AssertionError("Unexpected streaming runtime call")

    def embed(self, model, input_text):
        _ = model
        if isinstance(input_text, str):
            return [[1.0, 0.0]]
        return [[1.0, 0.0] for _ in input_text]


class _SearchStub:
    def search(self, *, query: str, limit: int):
        _ = query, limit
        return [
            {
                "title": "OpenAI API changelog",
                "url": "https://example.test/changelog",
                "snippet": "Latest API updates and release notes.",
            }
        ]


class _ModelDrivenSearchClient:
    def __init__(self) -> None:
        self.chat_calls: list[list] = []

    def chat(self, model, messages):
        _ = model
        self.chat_calls.append(list(messages))
        if len(self.chat_calls) == 1:
            return OllamaChatResult(
                content='{"tool":"web-search","query":"latest assistant release notes"}',
                prompt_tokens=3,
                completion_tokens=2,
                total_tokens=5,
            )
        return OllamaChatResult(
            content="Final answer with cited release notes.",
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
        )

    def stream_chat(self, model, messages):
        raise AssertionError("Unexpected streaming runtime call")

    def embed(self, model, input_text):
        raise AssertionError("Unexpected embedding call")


def test_streaming_chat_flow_persists_success_with_real_repository(
    monkeypatch, auth_headers
) -> None:
    connection = _InMemoryConnection()
    monkeypatch.setattr(
        "app.repositories.postgres.psycopg.connect",
        lambda database_url: connection,
    )
    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    client = TestClient(app)
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_ollama_client] = (
        lambda: _SuccessfulStreamingClient()
    )

    response = client.post(
        "/v1/chat/completions",
        json=_payload(),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "[DONE]" in response.text
    assert len(connection.conversations) == 1
    assert len(connection.messages) == 2
    assert [message["role"] for message in connection.messages] == ["user", "assistant"]
    assert connection.messages[1]["content"] == "Runtime response"
    assert len(connection.model_runs) == 1
    assert connection.model_runs[0]["status"] == "completed"
    assert connection.model_runs[0]["prompt_tokens"] == 11
    assert connection.model_runs[0]["completion_tokens"] == 7
    assert connection.model_runs[0]["total_tokens"] == 18


def test_non_streaming_client_binding_continues_same_conversation(
    monkeypatch, auth_headers
) -> None:
    connection = _InMemoryConnection()
    monkeypatch.setattr(
        "app.repositories.postgres.psycopg.connect",
        lambda database_url: connection,
    )
    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    client = TestClient(app)
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_ollama_client] = lambda: _MemoryAwareClient()

    first_response = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "First message"}],
            "stream": False,
            "metadata": {
                "source": "telegram",
                "client_conversation_id": "telegram:42",
            },
        },
        headers=auth_headers,
    )
    second_response = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "Second message"}],
            "stream": False,
            "metadata": {
                "source": "telegram",
                "client_conversation_id": "telegram:42",
            },
        },
        headers=auth_headers,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert (
        first_response.headers["x-conversation-id"]
        == second_response.headers["x-conversation-id"]
    )
    assert len(connection.conversations) == 1
    assert len(connection.client_conversation_bindings) == 1
    assert len(connection.messages) == 4
    assert [message["role"] for message in connection.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["content"] for message in connection.messages if message["role"] == "user"] == [
        "First message",
        "Second message",
    ]
    assert len(connection.model_runs) == 2


def test_audio_transcription_flow_persists_canonical_user_message(
    monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()
    connection = _InMemoryConnection()
    monkeypatch.setattr(
        "app.repositories.postgres.psycopg.connect",
        lambda database_url: connection,
    )
    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    stt_client = _TranscribingSttClient(["Privet mir"])
    client = TestClient(app)
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_stt_client] = lambda: stt_client

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Privet mir"}
    assert response.headers["x-conversation-id"]
    assert len(connection.conversations) == 1
    assert len(connection.messages) == 1
    assert connection.messages[0]["role"] == "user"
    assert connection.messages[0]["content"] == "Privet mir"
    assert connection.messages[0]["source"] == "audio_transcription"
    assert connection.messages[0]["message_index"] == 0


def test_audio_transcription_flow_appends_to_existing_conversation(
    monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()
    connection = _InMemoryConnection()
    monkeypatch.setattr(
        "app.repositories.postgres.psycopg.connect",
        lambda database_url: connection,
    )
    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    stt_client = _TranscribingSttClient(["First transcript", "Second transcript"])
    client = TestClient(app)
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_stt_client] = lambda: stt_client

    first_response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1"},
        headers=auth_headers,
    )
    second_response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1"},
        headers={
            **auth_headers,
            "X-Conversation-ID": first_response.headers["x-conversation-id"],
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert (
        first_response.headers["x-conversation-id"]
        == second_response.headers["x-conversation-id"]
    )
    assert len(connection.conversations) == 1
    assert len(connection.messages) == 2
    assert [message["content"] for message in connection.messages] == [
        "First transcript",
        "Second transcript",
    ]
    assert [message["message_index"] for message in connection.messages] == [0, 1]
    assert all(message["source"] == "audio_transcription" for message in connection.messages)


def test_streaming_chat_flow_persists_failure_without_done_sentinel(
    monkeypatch, auth_headers
) -> None:
    connection = _InMemoryConnection()
    monkeypatch.setattr(
        "app.repositories.postgres.psycopg.connect",
        lambda database_url: connection,
    )
    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_ollama_client] = lambda: _FailingStreamingClient()

    response = client.post(
        "/v1/chat/completions",
        json=_payload(),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert '"content": "Runtime "' in response.text or '"content":"Runtime "' in response.text
    assert "[DONE]" not in response.text
    assert len(connection.conversations) == 1
    assert len(connection.messages) == 1
    assert connection.messages[0]["role"] == "user"
    assert len(connection.model_runs) == 1
    assert connection.model_runs[0]["status"] == "failed"
    assert connection.model_runs[0]["error_code"] == "runtime_unavailable"


def test_non_streaming_memory_flow_records_retrieval_and_materialization(
    monkeypatch, auth_headers
) -> None:
    connection = _InMemoryConnection()
    connection.conversations["conv_seed"] = {
        "id": "conv_seed",
        "public_profile": "assistant-v1",
        "created_at": datetime(2026, 3, 12, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 3, 12, tzinfo=timezone.utc),
    }
    connection.messages.append(
        {
            "id": "msg_seed",
            "conversation_id": "conv_seed",
            "message_index": 0,
            "role": "user",
            "content": "My favorite color is blue.",
            "source": "request_transcript",
            "created_at": datetime(2026, 3, 12, tzinfo=timezone.utc),
        }
    )
    connection.memory_items.append(
        {
            "id": "mem_seed",
            "principal_id": "prn_local_assistant",
            "kind": "user_message",
            "scope": "principal",
            "content": "My favorite color is blue.",
            "status": "active",
            "source_message_id": "msg_seed",
            "conversation_id": "conv_seed",
            "embedding": [1.0, 0.0],
            "embedding_model": "all-minilm",
            "created_at": datetime(2026, 3, 12, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 3, 12, tzinfo=timezone.utc),
        }
    )
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "all-minilm")
    monkeypatch.setattr(
        "app.repositories.postgres.psycopg.connect",
        lambda database_url: connection,
    )
    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    runtime_client = _MemoryAwareClient()
    client = TestClient(app)
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_ollama_client] = lambda: runtime_client

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [
                {
                    "role": "user",
                    "content": "My favorite color is blue and I live in Berlin.",
                }
            ],
            "stream": False,
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert runtime_client.last_chat_messages is not None
    assert runtime_client.last_chat_messages[0].role == "system"
    assert "My favorite color is blue." in runtime_client.last_chat_messages[0].content
    assert len(connection.retrieval_runs) == 1
    assert connection.retrieval_runs[0]["status"] == "completed"
    assert len(connection.retrieval_hits) == 1
    assert connection.retrieval_hits[0]["memory_item_id"] == "mem_seed"
    assert len(connection.memory_items) == 2
    assert connection.memory_items[1]["content"] == "My favorite color is blue and I live in Berlin."


def test_non_streaming_web_search_flow_records_tool_execution_audit(
    monkeypatch, auth_headers
) -> None:
    connection = _InMemoryConnection()
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    monkeypatch.setattr(
        "app.repositories.postgres.psycopg.connect",
        lambda database_url: connection,
    )
    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    runtime_client = _MemoryAwareClient()
    client = TestClient(app)
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_ollama_client] = lambda: runtime_client
    client.app.dependency_overrides[deps.get_web_search_client] = lambda: _SearchStub()

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
            "metadata": {"web_search": "true"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert runtime_client.last_chat_messages is not None
    assert runtime_client.last_chat_messages[0].role == "system"
    assert "Relevant web search results" in runtime_client.last_chat_messages[0].content
    assert "OpenAI API changelog" in runtime_client.last_chat_messages[0].content
    assert len(connection.tool_executions) == 1
    assert connection.tool_executions[0]["tool_name"] == "web-search"
    assert connection.tool_executions[0]["status"] == "completed"
    assert connection.tool_executions[0]["request_payload_json"] == {
        "query": "Hello",
        "limit": 3,
    }
    assert connection.tool_executions[0]["response_payload_json"]["results"][0]["url"] == (
        "https://example.test/changelog"
    )


def test_model_driven_web_search_flow_persists_only_final_answer_and_tool_audit(
    monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    get_settings.cache_clear()
    connection = _InMemoryConnection()
    runtime_client = _ModelDrivenSearchClient()
    monkeypatch.setattr(
        "app.repositories.postgres.psycopg.connect",
        lambda database_url: connection,
    )
    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    client = TestClient(app)
    client.app.dependency_overrides[deps.get_chat_repository] = lambda: repository
    client.app.dependency_overrides[deps.get_ollama_client] = lambda: runtime_client
    client.app.dependency_overrides[deps.get_web_search_client] = lambda: _SearchStub()

    response = client.post(
        "/v1/chat/completions",
        json=_payload(stream=False),
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == (
        "Final answer with cited release notes."
    )
    assert len(runtime_client.chat_calls) == 2
    assert len(connection.messages) == 2
    assert [message["role"] for message in connection.messages] == ["user", "assistant"]
    assert connection.messages[1]["content"] == "Final answer with cited release notes."
    assert '{"tool":"web-search"' not in connection.messages[1]["content"]
    assert len(connection.tool_executions) == 1
    assert connection.tool_executions[0]["request_payload_json"] == {
        "query": "latest assistant release notes",
        "limit": 3,
    }
