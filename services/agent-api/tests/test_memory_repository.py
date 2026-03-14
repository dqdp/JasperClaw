from datetime import datetime, timezone

import pytest

from app.core.errors import APIError
from app.repositories.postgres import PostgresChatRepository


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False


class _FakeCursor:
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
        self._connection.executed.append((normalized, params))
        if normalized.startswith(
            "SELECT id, source_message_id, content, 1 - (embedding <=> %s::vector) AS score FROM memory_items"
        ):
            self._rows = list(self._connection.memory_rows)
            return
        if normalized == "SELECT status FROM memory_items WHERE id = %s FOR UPDATE":
            status = self._connection.memory_item_statuses.get(params[0])
            self._rows = [] if status is None else [(status,)]
            return
        if normalized == "UPDATE memory_items SET status = %s, updated_at = %s WHERE id = %s":
            self._connection.memory_item_statuses[params[2]] = params[0]
            self._rows = []
            return
        self._rows = []

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self, memory_rows=None, memory_item_statuses=None) -> None:
        self.executed = []
        self.memory_rows = list(memory_rows or [])
        self.memory_item_statuses = dict(memory_item_statuses or {})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def transaction(self):
        return _FakeTransaction()

    def cursor(self):
        return _FakeCursor(self)


def test_memory_repository_retrieve_memory_maps_hits(monkeypatch) -> None:
    from app.persistence.memory_repo import PostgresMemoryRepository
    from app.persistence.models import MemorySearchHit

    fake_connection = _FakeConnection(
        memory_rows=[("mem_1", "msg_1", "Remember blue", 0.87)]
    )
    monkeypatch.setattr(
        "app.persistence.memory_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )

    repository = PostgresMemoryRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )

    hits = repository.retrieve_memory(
        query_embedding=[0.1, 0.2],
        limit=3,
        min_score=0.35,
    )

    assert hits == [
        MemorySearchHit(
            memory_item_id="mem_1",
            source_message_id="msg_1",
            content="Remember blue",
            score=0.87,
        )
    ]
    assert fake_connection.executed == [
        (
            "SELECT id, source_message_id, content, 1 - (embedding <=> %s::vector) AS score FROM memory_items WHERE principal_id = %s AND status = %s AND embedding IS NOT NULL AND 1 - (embedding <=> %s::vector) >= %s ORDER BY embedding <=> %s::vector ASC, created_at DESC LIMIT %s",
            ("[0.1,0.2]", "prn_local_assistant", "active", "[0.1,0.2]", 0.35, "[0.1,0.2]", 3),
        )
    ]


def test_memory_repository_records_retrieval_run_and_hits(monkeypatch) -> None:
    from app.persistence.memory_repo import PostgresMemoryRepository
    from app.persistence.models import MemoryRetrievalRecord, MemorySearchHit

    fake_connection = _FakeConnection()
    monkeypatch.setattr(
        "app.persistence.memory_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )

    repository = PostgresMemoryRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    generated_ids = iter(("retr_fixed", "hit_1", "hit_2"))
    monkeypatch.setattr(repository, "_new_id", lambda prefix: next(generated_ids))

    repository.record_retrieval(
        conversation_id="conv_1",
        request_id="req_1",
        public_model="assistant-v1",
        retrieval=MemoryRetrievalRecord(
            query_text="favorite color",
            status="completed",
            top_k=2,
            latency_ms=12.5,
            hits=(
                MemorySearchHit(
                    memory_item_id="mem_1",
                    source_message_id="msg_1",
                    content="Blue",
                    score=0.91,
                ),
                MemorySearchHit(
                    memory_item_id="mem_2",
                    source_message_id="msg_2",
                    content="Berlin",
                    score=0.72,
                ),
            ),
        ),
        created_at=datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
    )

    assert len(fake_connection.executed) == 3
    assert fake_connection.executed[0] == (
        "INSERT INTO retrieval_runs ( id, conversation_id, request_id, query_text, profile_id, strategy, top_k, status, latency_ms, error_type, error_code, created_at ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "retr_fixed",
            "conv_1",
            "req_1",
            "favorite color",
            "assistant-v1",
            "semantic_memory_v1",
            2,
            "completed",
            12.5,
            None,
            None,
            datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
        ),
    )
    assert fake_connection.executed[1][1][0:5] == ("hit_1", "retr_fixed", "mem_1", 1, 0.91)
    assert fake_connection.executed[2][1][0:5] == ("hit_2", "retr_fixed", "mem_2", 2, 0.72)


def test_memory_repository_rejects_embedding_count_mismatch(monkeypatch) -> None:
    from app.persistence.memory_repo import PostgresMemoryRepository
    from app.persistence.models import PersistedMessage

    monkeypatch.setattr(
        "app.persistence.memory_repo.psycopg.connect",
        lambda database_url: (_ for _ in ()).throw(AssertionError("unexpected connect")),
    )
    repository = PostgresMemoryRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )

    with pytest.raises(APIError) as exc_info:
        repository.store_memory_items(
            conversation_id="conv_1",
            messages=(
                PersistedMessage(
                    message_id="msg_1",
                    message_index=0,
                    role="user",
                    content="Remember blue",
                    source="request",
                ),
            ),
            embeddings=(),
            embedding_model="nomic-embed-text",
            created_at=datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
        )

    assert exc_info.value.code == "memory_embedding_mismatch"


def test_memory_repository_transitions_active_item_to_invalidated(monkeypatch) -> None:
    from app.persistence.memory_repo import PostgresMemoryRepository
    from app.persistence.models import MemoryLifecycleTransitionResult

    fake_connection = _FakeConnection(memory_item_statuses={"mem_1": "active"})
    monkeypatch.setattr(
        "app.persistence.memory_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )
    repository = PostgresMemoryRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )

    result = repository.transition_memory_item_status(
        memory_item_id="mem_1",
        target_status="invalidated",
        updated_at=datetime(2026, 3, 14, 8, 0, tzinfo=timezone.utc),
    )

    assert result == MemoryLifecycleTransitionResult(
        memory_item_id="mem_1",
        previous_status="active",
        current_status="invalidated",
        changed=True,
    )
    assert fake_connection.memory_item_statuses["mem_1"] == "invalidated"
    assert fake_connection.executed == [
        ("SELECT status FROM memory_items WHERE id = %s FOR UPDATE", ("mem_1",)),
        (
            "UPDATE memory_items SET status = %s, updated_at = %s WHERE id = %s",
            ("invalidated", datetime(2026, 3, 14, 8, 0, tzinfo=timezone.utc), "mem_1"),
        ),
    ]


def test_memory_repository_transitions_invalidated_item_to_deleted(monkeypatch) -> None:
    from app.persistence.memory_repo import PostgresMemoryRepository
    from app.persistence.models import MemoryLifecycleTransitionResult

    fake_connection = _FakeConnection(memory_item_statuses={"mem_1": "invalidated"})
    monkeypatch.setattr(
        "app.persistence.memory_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )
    repository = PostgresMemoryRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )

    result = repository.transition_memory_item_status(
        memory_item_id="mem_1",
        target_status="deleted",
        updated_at=datetime(2026, 3, 14, 8, 5, tzinfo=timezone.utc),
    )

    assert result == MemoryLifecycleTransitionResult(
        memory_item_id="mem_1",
        previous_status="invalidated",
        current_status="deleted",
        changed=True,
    )
    assert fake_connection.memory_item_statuses["mem_1"] == "deleted"


def test_memory_repository_returns_noop_when_transition_matches_current_status(
    monkeypatch,
) -> None:
    from app.persistence.memory_repo import PostgresMemoryRepository
    from app.persistence.models import MemoryLifecycleTransitionResult

    fake_connection = _FakeConnection(memory_item_statuses={"mem_1": "invalidated"})
    monkeypatch.setattr(
        "app.persistence.memory_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )
    repository = PostgresMemoryRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )

    result = repository.transition_memory_item_status(
        memory_item_id="mem_1",
        target_status="invalidated",
        updated_at=datetime(2026, 3, 14, 8, 10, tzinfo=timezone.utc),
    )

    assert result == MemoryLifecycleTransitionResult(
        memory_item_id="mem_1",
        previous_status="invalidated",
        current_status="invalidated",
        changed=False,
    )
    assert fake_connection.executed == [
        ("SELECT status FROM memory_items WHERE id = %s FOR UPDATE", ("mem_1",))
    ]


def test_memory_repository_rejects_forbidden_resurrection_transition(monkeypatch) -> None:
    from app.persistence.memory_repo import PostgresMemoryRepository

    fake_connection = _FakeConnection(memory_item_statuses={"mem_1": "deleted"})
    monkeypatch.setattr(
        "app.persistence.memory_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )
    repository = PostgresMemoryRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )

    with pytest.raises(APIError) as exc_info:
        repository.transition_memory_item_status(
            memory_item_id="mem_1",
            target_status="invalidated",
            updated_at=datetime(2026, 3, 14, 8, 15, tzinfo=timezone.utc),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_type == "validation_error"
    assert exc_info.value.code == "memory_lifecycle_conflict"
    assert fake_connection.memory_item_statuses["mem_1"] == "deleted"


def test_memory_repository_rejects_missing_memory_item(monkeypatch) -> None:
    from app.persistence.memory_repo import PostgresMemoryRepository

    fake_connection = _FakeConnection()
    monkeypatch.setattr(
        "app.persistence.memory_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )
    repository = PostgresMemoryRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )

    with pytest.raises(APIError) as exc_info:
        repository.transition_memory_item_status(
            memory_item_id="mem_missing",
            target_status="deleted",
            updated_at=datetime(2026, 3, 14, 8, 20, tzinfo=timezone.utc),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_type == "not_found"
    assert exc_info.value.code == "memory_item_not_found"


def test_chat_repository_delegates_memory_calls_to_memory_repository() -> None:
    from app.persistence.models import (
        MemoryLifecycleTransitionResult,
        MemoryRetrievalRecord,
        MemorySearchHit,
        PersistedMessage,
    )

    class _FakeMemoryRepository:
        def __init__(self) -> None:
            self.retrieve_calls = []
            self.record_calls = []
            self.store_calls = []
            self.transition_calls = []

        def retrieve_memory(self, **kwargs):
            self.retrieve_calls.append(kwargs)
            return [
                MemorySearchHit(
                    memory_item_id="mem_1",
                    source_message_id="msg_1",
                    content="Remember blue",
                    score=0.87,
                )
            ]

        def record_retrieval(self, **kwargs):
            self.record_calls.append(kwargs)

        def store_memory_items(self, **kwargs):
            self.store_calls.append(kwargs)

        def transition_memory_item_status(self, **kwargs):
            self.transition_calls.append(kwargs)
            return MemoryLifecycleTransitionResult(
                memory_item_id=kwargs["memory_item_id"],
                previous_status="active",
                current_status=kwargs["target_status"],
                changed=True,
            )

    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    fake_memory_repository = _FakeMemoryRepository()
    repository._memory_repository = fake_memory_repository

    hits = repository.retrieve_memory(query_embedding=[0.1], limit=2, min_score=0.4)
    repository.record_retrieval(
        conversation_id="conv_1",
        request_id="req_1",
        public_model="assistant-v1",
        retrieval=MemoryRetrievalRecord(
            query_text="favorite color",
            status="completed",
            top_k=2,
            latency_ms=8.0,
        ),
        created_at=datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
    )
    repository.store_memory_items(
        conversation_id="conv_1",
        messages=(
            PersistedMessage(
                message_id="msg_1",
                message_index=0,
                role="user",
                content="Remember blue",
                source="request",
            ),
        ),
        embeddings=([0.1, 0.2],),
        embedding_model="nomic-embed-text",
        created_at=datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
    )
    transition = repository.transition_memory_item_status(
        memory_item_id="mem_1",
        target_status="invalidated",
        updated_at=datetime(2026, 3, 13, 10, 1, tzinfo=timezone.utc),
    )

    assert len(hits) == 1
    assert fake_memory_repository.retrieve_calls == [
        {"query_embedding": [0.1], "limit": 2, "min_score": 0.4}
    ]
    assert fake_memory_repository.record_calls[0]["conversation_id"] == "conv_1"
    assert fake_memory_repository.store_calls[0]["embedding_model"] == "nomic-embed-text"
    assert transition.current_status == "invalidated"
    assert fake_memory_repository.transition_calls == [
        {
            "memory_item_id": "mem_1",
            "target_status": "invalidated",
            "updated_at": datetime(2026, 3, 13, 10, 1, tzinfo=timezone.utc),
        }
    ]
