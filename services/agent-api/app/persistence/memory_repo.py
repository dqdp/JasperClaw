from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import TypeVar
from uuid import uuid4

import psycopg

from app.core.errors import APIError
from app.persistence.models import (
    MemoryLifecycleTransitionResult,
    MemoryRetrievalRecord,
    MemorySearchHit,
    PersistedMessage,
)

_T = TypeVar("_T")

_DEFAULT_PRINCIPAL_ID = "prn_local_assistant"
_MEMORY_KIND_USER_MESSAGE = "user_message"
_MEMORY_SCOPE_PRINCIPAL = "principal"
_MEMORY_STATUS_ACTIVE = "active"
_MEMORY_STATUS_INVALIDATED = "invalidated"
_MEMORY_STATUS_DELETED = "deleted"
_SUPPORTED_MEMORY_STATUSES = frozenset(
    (
        _MEMORY_STATUS_ACTIVE,
        _MEMORY_STATUS_INVALIDATED,
        _MEMORY_STATUS_DELETED,
    )
)


class PostgresMemoryRepository:
    """Owns semantic-memory retrieval audit and materialization storage."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def retrieve_memory(
        self,
        *,
        query_embedding: Sequence[float],
        limit: int,
        min_score: float,
    ) -> list[MemorySearchHit]:
        vector_literal = self._vector_literal(query_embedding)

        def read(conn: psycopg.Connection) -> list[MemorySearchHit]:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        source_message_id,
                        content,
                        1 - (embedding <=> %s::vector) AS score
                    FROM memory_items
                    WHERE principal_id = %s
                      AND status = %s
                      AND embedding IS NOT NULL
                      AND 1 - (embedding <=> %s::vector) >= %s
                    ORDER BY embedding <=> %s::vector ASC, created_at DESC
                    LIMIT %s
                    """,
                    (
                        vector_literal,
                        _DEFAULT_PRINCIPAL_ID,
                        _MEMORY_STATUS_ACTIVE,
                        vector_literal,
                        min_score,
                        vector_literal,
                        limit,
                    ),
                )
                return [
                    MemorySearchHit(
                        memory_item_id=row[0],
                        source_message_id=row[1],
                        content=row[2],
                        score=float(row[3]),
                    )
                    for row in cur.fetchall()
                ]

        return self._execute(read)

    def record_retrieval(
        self,
        *,
        conversation_id: str,
        request_id: str,
        public_model: str,
        retrieval: MemoryRetrievalRecord,
        created_at: datetime,
    ) -> None:
        timestamp = created_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> None:
            retrieval_run_id = self._new_id("retr")
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO retrieval_runs (
                        id,
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
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        retrieval_run_id,
                        conversation_id,
                        request_id,
                        retrieval.query_text,
                        public_model,
                        "semantic_memory_v1",
                        retrieval.top_k,
                        retrieval.status,
                        retrieval.latency_ms,
                        retrieval.error_type,
                        retrieval.error_code,
                        timestamp,
                    ),
                )

            for rank, hit in enumerate(retrieval.hits, start=1):
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO retrieval_hits (
                            id,
                            retrieval_run_id,
                            memory_item_id,
                            rank,
                            score,
                            included_in_prompt,
                            created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            self._new_id("hit"),
                            retrieval_run_id,
                            hit.memory_item_id,
                            rank,
                            hit.score,
                            True,
                            timestamp,
                        ),
                    )

        self._execute(write)

    def store_memory_items(
        self,
        *,
        conversation_id: str,
        messages: Sequence[PersistedMessage],
        embeddings: Sequence[Sequence[float]],
        embedding_model: str,
        created_at: datetime,
    ) -> None:
        if not messages:
            return
        if len(messages) != len(embeddings):
            raise APIError(
                status_code=500,
                error_type="internal_error",
                code="memory_embedding_mismatch",
                message="Memory embedding count mismatch",
            )

        timestamp = created_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> None:
            for message, embedding in zip(messages, embeddings, strict=True):
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO memory_items (
                            id,
                            principal_id,
                            kind,
                            scope,
                            content,
                            status,
                            source_message_id,
                            conversation_id,
                            embedding,
                            embedding_model,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s
                        )
                        """,
                        (
                            self._new_id("mem"),
                            _DEFAULT_PRINCIPAL_ID,
                            _MEMORY_KIND_USER_MESSAGE,
                            _MEMORY_SCOPE_PRINCIPAL,
                            message.content,
                            _MEMORY_STATUS_ACTIVE,
                            message.message_id,
                            conversation_id,
                            self._vector_literal(embedding),
                            embedding_model,
                            timestamp,
                            timestamp,
                        ),
                    )

        self._execute(write)

    def transition_memory_item_status(
        self,
        *,
        memory_item_id: str,
        target_status: str,
        updated_at: datetime,
    ) -> MemoryLifecycleTransitionResult:
        if target_status not in _SUPPORTED_MEMORY_STATUSES:
            raise APIError(
                status_code=500,
                error_type="internal_error",
                code="memory_lifecycle_invalid_target",
                message="Unsupported memory lifecycle target status",
            )

        timestamp = updated_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> MemoryLifecycleTransitionResult:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status
                    FROM memory_items
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (memory_item_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise APIError(
                        status_code=404,
                        error_type="not_found",
                        code="memory_item_not_found",
                        message="Memory item not found",
                    )

                current_status = str(row[0])
                if current_status == target_status:
                    return MemoryLifecycleTransitionResult(
                        memory_item_id=memory_item_id,
                        previous_status=current_status,
                        current_status=current_status,
                        changed=False,
                    )
                if not self._is_allowed_lifecycle_transition(
                    current_status=current_status,
                    target_status=target_status,
                ):
                    raise APIError(
                        status_code=409,
                        error_type="validation_error",
                        code="memory_lifecycle_conflict",
                        message="Memory lifecycle transition not allowed",
                    )

                cur.execute(
                    """
                    UPDATE memory_items
                    SET status = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (target_status, timestamp, memory_item_id),
                )
                return MemoryLifecycleTransitionResult(
                    memory_item_id=memory_item_id,
                    previous_status=current_status,
                    current_status=target_status,
                    changed=True,
                )

        return self._execute(write)

    def _execute(self, operation: Callable[[psycopg.Connection], _T]) -> _T:
        try:
            with psycopg.connect(self._database_url) as conn:
                with conn.transaction():
                    return operation(conn)
        except psycopg.Error as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="storage_unavailable",
                message="Persistent storage unavailable",
            ) from exc

    def _vector_literal(self, embedding: Sequence[float]) -> str:
        serialized = ",".join(str(float(value)) for value in embedding)
        return f"[{serialized}]"

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"

    def _is_allowed_lifecycle_transition(
        self,
        *,
        current_status: str,
        target_status: str,
    ) -> bool:
        return (
            current_status == _MEMORY_STATUS_ACTIVE
            and target_status in (_MEMORY_STATUS_INVALIDATED, _MEMORY_STATUS_DELETED)
        ) or (
            current_status == _MEMORY_STATUS_INVALIDATED
            and target_status == _MEMORY_STATUS_DELETED
        )
