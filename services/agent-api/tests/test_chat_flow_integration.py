from collections.abc import Iterator

from fastapi.testclient import TestClient

from app.api import deps
from app.clients.ollama import OllamaChatStreamChunk
from app.core.errors import APIError
from app.main import app
from app.repositories import PostgresChatRepository


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

        if normalized.startswith("UPDATE conversations SET updated_at = %s WHERE id = %s"):
            updated_at, conversation_id = params
            self._connection.conversations[conversation_id]["updated_at"] = updated_at
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
        self.messages: list[dict] = []
        self.model_runs: list[dict] = []

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
