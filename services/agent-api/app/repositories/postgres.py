import json
from datetime import datetime, timezone
from typing import Protocol, Sequence
from uuid import uuid4

import psycopg

from app.core.errors import APIError
from app.persistence.memory_repo import PostgresMemoryRepository
from app.persistence.models import (
    ChatPersistenceResult,
    ConversationContext,
    MemoryRetrievalRecord,
    MemorySearchHit,
    PersistedMessage,
    ToolExecutionRecord,
    TranscriptMessage,
)
from app.schemas.chat import ChatCompletionUsage, ChatMessage

class ChatRepository(Protocol):
    def prepare_conversation(
        self,
        *,
        public_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
        client_source: str | None,
        client_conversation_id: str | None,
        created_at: datetime,
    ) -> ConversationContext: ...

    def record_successful_completion(
        self,
        *,
        request_id: str,
        public_model: str,
        runtime_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
        client_source: str | None,
        client_conversation_id: str | None,
        response_content: str,
        usage: ChatCompletionUsage | None,
        started_at: datetime,
        completed_at: datetime,
    ) -> ChatPersistenceResult: ...

    def record_failed_completion(
        self,
        *,
        request_id: str,
        public_model: str,
        runtime_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
        client_source: str | None,
        client_conversation_id: str | None,
        error_type: str,
        error_code: str,
        error_message: str,
        started_at: datetime,
        completed_at: datetime,
    ) -> ChatPersistenceResult: ...

    def retrieve_memory(
        self,
        *,
        query_embedding: Sequence[float],
        limit: int,
        min_score: float,
    ) -> list[MemorySearchHit]: ...

    def record_retrieval(
        self,
        *,
        conversation_id: str,
        request_id: str,
        public_model: str,
        retrieval: MemoryRetrievalRecord,
        created_at: datetime,
    ) -> None: ...

    def store_memory_items(
        self,
        *,
        conversation_id: str,
        messages: Sequence[PersistedMessage],
        embeddings: Sequence[Sequence[float]],
        embedding_model: str,
        created_at: datetime,
    ) -> None: ...

    def record_tool_execution(
        self,
        *,
        conversation_id: str,
        request_id: str,
        model_run_id: str | None,
        tool_execution: ToolExecutionRecord,
    ) -> None: ...


class PostgresChatRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        # Memory persistence is already a distinct storage concern and can be
        # split first without changing the public chat repository contract.
        self._memory_repository = PostgresMemoryRepository(database_url)

    def prepare_conversation(
        self,
        *,
        public_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
        client_source: str | None,
        client_conversation_id: str | None,
        created_at: datetime,
    ) -> ConversationContext:
        def write(conn: psycopg.Connection) -> ConversationContext:
            return self._resolve_conversation(
                conn,
                public_model=public_model,
                request_messages=request_messages,
                conversation_id_hint=conversation_id_hint,
                client_source=client_source,
                client_conversation_id=client_conversation_id,
                created_at=created_at.astimezone(timezone.utc),
            )

        return self._execute(write)

    def record_successful_completion(
        self,
        *,
        request_id: str,
        public_model: str,
        runtime_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
        client_source: str | None,
        client_conversation_id: str | None,
        response_content: str,
        usage: ChatCompletionUsage | None,
        started_at: datetime,
        completed_at: datetime,
    ) -> ChatPersistenceResult:
        assistant_message_id = self._new_id("msg")
        created_at = completed_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> ChatPersistenceResult:
            context = self._resolve_conversation(
                conn,
                public_model=public_model,
                request_messages=request_messages,
                conversation_id_hint=conversation_id_hint,
                client_source=client_source,
                client_conversation_id=client_conversation_id,
                created_at=created_at,
            )
            model_run_id = self._new_id("run")
            request_persisted_messages = self._insert_request_messages(
                conn,
                conversation_id=context.conversation_id,
                starting_index=context.existing_message_count,
                matched_request_message_count=context.matched_request_message_count,
                request_messages=request_messages,
                created_at=created_at,
            )
            assistant_persisted_message = self._insert_message(
                conn,
                message_id=assistant_message_id,
                conversation_id=context.conversation_id,
                message_index=len(request_messages),
                role="assistant",
                content=response_content,
                source="assistant_response",
                created_at=created_at,
            )
            self._insert_model_run(
                conn,
                model_run_id=model_run_id,
                conversation_id=context.conversation_id,
                assistant_message_id=assistant_message_id,
                request_id=request_id,
                public_model=public_model,
                runtime_model=runtime_model,
                status="completed",
                error_type=None,
                error_code=None,
                error_message=None,
                usage=usage,
                started_at=started_at,
                completed_at=completed_at,
            )
            self._touch_conversation(
                conn,
                conversation_id=context.conversation_id,
                updated_at=completed_at,
            )
            return ChatPersistenceResult(
                conversation_id=context.conversation_id,
                assistant_message_id=assistant_message_id,
                model_run_id=model_run_id,
                persisted_messages=(
                    *request_persisted_messages,
                    assistant_persisted_message,
                ),
            )

        return self._execute(write)

    def record_failed_completion(
        self,
        *,
        request_id: str,
        public_model: str,
        runtime_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
        client_source: str | None,
        client_conversation_id: str | None,
        error_type: str,
        error_code: str,
        error_message: str,
        started_at: datetime,
        completed_at: datetime,
    ) -> ChatPersistenceResult:
        created_at = completed_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> ChatPersistenceResult:
            context = self._resolve_conversation(
                conn,
                public_model=public_model,
                request_messages=request_messages,
                conversation_id_hint=conversation_id_hint,
                client_source=client_source,
                client_conversation_id=client_conversation_id,
                created_at=created_at,
            )
            model_run_id = self._new_id("run")
            request_persisted_messages = self._insert_request_messages(
                conn,
                conversation_id=context.conversation_id,
                starting_index=context.existing_message_count,
                matched_request_message_count=context.matched_request_message_count,
                request_messages=request_messages,
                created_at=created_at,
            )
            self._insert_model_run(
                conn,
                model_run_id=model_run_id,
                conversation_id=context.conversation_id,
                assistant_message_id=None,
                request_id=request_id,
                public_model=public_model,
                runtime_model=runtime_model,
                status="failed",
                error_type=error_type,
                error_code=error_code,
                error_message=error_message,
                usage=None,
                started_at=started_at,
                completed_at=completed_at,
            )
            self._touch_conversation(
                conn,
                conversation_id=context.conversation_id,
                updated_at=completed_at,
            )
            return ChatPersistenceResult(
                conversation_id=context.conversation_id,
                assistant_message_id=None,
                model_run_id=model_run_id,
                persisted_messages=tuple(request_persisted_messages),
            )

        return self._execute(write)

    def retrieve_memory(
        self,
        *,
        query_embedding: Sequence[float],
        limit: int,
        min_score: float,
    ) -> list[MemorySearchHit]:
        return self._memory_repository.retrieve_memory(
            query_embedding=query_embedding,
            limit=limit,
            min_score=min_score,
        )

    def record_retrieval(
        self,
        *,
        conversation_id: str,
        request_id: str,
        public_model: str,
        retrieval: MemoryRetrievalRecord,
        created_at: datetime,
    ) -> None:
        self._memory_repository.record_retrieval(
            conversation_id=conversation_id,
            request_id=request_id,
            public_model=public_model,
            retrieval=retrieval,
            created_at=created_at,
        )

    def store_memory_items(
        self,
        *,
        conversation_id: str,
        messages: Sequence[PersistedMessage],
        embeddings: Sequence[Sequence[float]],
        embedding_model: str,
        created_at: datetime,
    ) -> None:
        self._memory_repository.store_memory_items(
            conversation_id=conversation_id,
            messages=messages,
            embeddings=embeddings,
            embedding_model=embedding_model,
            created_at=created_at,
        )

    def record_tool_execution(
        self,
        *,
        conversation_id: str,
        request_id: str,
        model_run_id: str | None,
        tool_execution: ToolExecutionRecord,
    ) -> None:
        def write(conn: psycopg.Connection) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tool_executions (
                        id,
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
                        created_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s, %s, %s, %s
                    )
                    """,
                    (
                        tool_execution.invocation_id,
                        conversation_id,
                        model_run_id,
                        request_id,
                        tool_execution.tool_name,
                        tool_execution.status,
                        tool_execution.started_at.astimezone(timezone.utc),
                        tool_execution.completed_at.astimezone(timezone.utc),
                        tool_execution.latency_ms,
                        tool_execution.error_type,
                        tool_execution.error_code,
                        json.dumps(tool_execution.arguments),
                        (
                            json.dumps(tool_execution.output)
                            if tool_execution.output is not None
                            else None
                        ),
                        tool_execution.policy_decision,
                        tool_execution.adapter_name,
                        tool_execution.provider,
                        tool_execution.completed_at.astimezone(timezone.utc),
                    ),
                )

        self._execute(write)

    def _execute(self, operation):
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

    def _resolve_conversation(
        self,
        conn: psycopg.Connection,
        *,
        public_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
        client_source: str | None,
        client_conversation_id: str | None,
        created_at: datetime,
    ) -> ConversationContext:
        bound_context = None
        if client_source and client_conversation_id:
            bound_context = self._resolve_client_conversation_binding(
                conn,
                client_source=client_source,
                client_conversation_id=client_conversation_id,
                public_model=public_model,
            )

        if bound_context is not None:
            if (
                conversation_id_hint is not None
                and bound_context.conversation_id != conversation_id_hint
            ):
                raise APIError(
                    status_code=409,
                    error_type="validation_error",
                    code="conversation_mismatch",
                    message="Client conversation binding conflicts with canonical hint",
                )
            return bound_context

        if conversation_id_hint:
            context = self._resolve_explicit_conversation(
                conn,
                conversation_id_hint=conversation_id_hint,
                public_model=public_model,
                request_messages=request_messages,
            )
            if context is not None:
                return context
            raise APIError(
                status_code=409,
                error_type="validation_error",
                code="conversation_mismatch",
                message="Conversation hint does not match request transcript",
            )

        context = self._resolve_by_transcript_prefix(
            conn,
            public_model=public_model,
            request_messages=request_messages,
        )
        if context is not None:
            return context

        if client_source and client_conversation_id:
            return self._create_client_bound_conversation(
                conn,
                client_source=client_source,
                client_conversation_id=client_conversation_id,
                public_model=public_model,
                created_at=created_at,
            )

        conversation_id = self._new_id("conv")
        self._insert_conversation(
            conn,
            conversation_id=conversation_id,
            public_model=public_model,
            created_at=created_at,
        )
        return ConversationContext(
            conversation_id=conversation_id,
            existing_message_count=0,
            matched_request_message_count=0,
            conversation_created=True,
        )

    def _resolve_explicit_conversation(
        self,
        conn: psycopg.Connection,
        *,
        conversation_id_hint: str,
        public_model: str,
        request_messages: list[ChatMessage],
    ) -> ConversationContext | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM conversations
                WHERE id = %s AND public_profile = %s
                """,
                (conversation_id_hint, public_model),
            )
            row = cur.fetchone()
        if row is None:
            return None

        transcript = self._load_conversation_transcript(conn, row[0])
        prefix_length = matching_prefix_length(transcript, request_messages)
        if prefix_length is None:
            return None

        return ConversationContext(
            conversation_id=row[0],
            existing_message_count=prefix_length,
            matched_request_message_count=prefix_length,
            conversation_created=False,
        )

    def _resolve_client_conversation_binding(
        self,
        conn: psycopg.Connection,
        *,
        client_source: str,
        client_conversation_id: str,
        public_model: str,
    ) -> ConversationContext | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT conversation_id
                FROM client_conversation_bindings
                WHERE client_source = %s
                  AND client_conversation_id = %s
                  AND public_profile = %s
                """,
                (client_source, client_conversation_id, public_model),
            )
            row = cur.fetchone()
        if row is None:
            return None

        transcript = self._load_conversation_transcript(conn, row[0])
        return ConversationContext(
            conversation_id=row[0],
            existing_message_count=len(transcript),
            matched_request_message_count=0,
            conversation_created=False,
        )

    def _create_client_bound_conversation(
        self,
        conn: psycopg.Connection,
        *,
        client_source: str,
        client_conversation_id: str,
        public_model: str,
        created_at: datetime,
    ) -> ConversationContext:
        conversation_id = self._new_id("conv")
        self._insert_conversation(
            conn,
            conversation_id=conversation_id,
            public_model=public_model,
            created_at=created_at,
        )
        bound_conversation_id = self._upsert_client_conversation_binding(
            conn,
            client_source=client_source,
            client_conversation_id=client_conversation_id,
            public_model=public_model,
            conversation_id=conversation_id,
            created_at=created_at,
        )
        if bound_conversation_id != conversation_id:
            self._delete_conversation(conn, conversation_id=conversation_id)
            transcript = self._load_conversation_transcript(conn, bound_conversation_id)
            return ConversationContext(
                conversation_id=bound_conversation_id,
                existing_message_count=len(transcript),
                matched_request_message_count=0,
                conversation_created=False,
            )

        return ConversationContext(
            conversation_id=conversation_id,
            existing_message_count=0,
            matched_request_message_count=0,
            conversation_created=True,
        )

    def _upsert_client_conversation_binding(
        self,
        conn: psycopg.Connection,
        *,
        client_source: str,
        client_conversation_id: str,
        public_model: str,
        conversation_id: str,
        created_at: datetime,
    ) -> str:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO client_conversation_bindings (
                    client_source,
                    client_conversation_id,
                    public_profile,
                    conversation_id,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (client_source, client_conversation_id, public_profile)
                DO UPDATE SET updated_at = client_conversation_bindings.updated_at
                RETURNING conversation_id
                """,
                (
                    client_source,
                    client_conversation_id,
                    public_model,
                    conversation_id,
                    created_at,
                    created_at,
                ),
            )
            row = cur.fetchone()
        if row is None or not isinstance(row[0], str):
            raise APIError(
                status_code=500,
                error_type="internal_error",
                code="binding_resolution_failed",
                message="Client conversation binding resolution failed",
            )
        return row[0]

    def _resolve_by_transcript_prefix(
        self,
        conn: psycopg.Connection,
        *,
        public_model: str,
        request_messages: list[ChatMessage],
    ) -> ConversationContext | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM conversations
                WHERE public_profile = %s
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 100
                """,
                (public_model,),
            )
            candidate_ids = [row[0] for row in cur.fetchall()]

        best_match: ConversationContext | None = None
        for conversation_id in candidate_ids:
            transcript = self._load_conversation_transcript(conn, conversation_id)
            # Ignore placeholder conversations until they carry a persisted request transcript.
            if not transcript:
                continue
            prefix_length = matching_prefix_length(transcript, request_messages)
            if prefix_length is None:
                continue
            if best_match is None or prefix_length > best_match.existing_message_count:
                best_match = ConversationContext(
                    conversation_id=conversation_id,
                    existing_message_count=prefix_length,
                    matched_request_message_count=prefix_length,
                    conversation_created=False,
                )
        return best_match

    def _load_conversation_transcript(
        self,
        conn: psycopg.Connection,
        conversation_id: str,
    ) -> list[TranscriptMessage]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content
                FROM messages
                WHERE conversation_id = %s
                ORDER BY message_index ASC
                """,
                (conversation_id,),
            )
            return [
                TranscriptMessage(role=row[0], content=row[1]) for row in cur.fetchall()
            ]

    def _insert_conversation(
        self,
        conn: psycopg.Connection,
        *,
        conversation_id: str,
        public_model: str,
        created_at: datetime,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations (id, public_profile, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                (conversation_id, public_model, created_at, created_at),
            )

    def _delete_conversation(
        self,
        conn: psycopg.Connection,
        *,
        conversation_id: str,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM conversations
                WHERE id = %s
                """,
                (conversation_id,),
            )

    def _insert_request_messages(
        self,
        conn: psycopg.Connection,
        *,
        conversation_id: str,
        starting_index: int,
        matched_request_message_count: int,
        request_messages: list[ChatMessage],
        created_at: datetime,
    ) -> tuple[PersistedMessage, ...]:
        inserted_messages: list[PersistedMessage] = []
        for index, message in enumerate(
            request_messages[matched_request_message_count:],
            start=starting_index,
        ):
            inserted_messages.append(
                self._insert_message(
                    conn,
                    message_id=self._new_id("msg"),
                    conversation_id=conversation_id,
                    message_index=index,
                    role=message.role,
                    content=message.content,
                    source="request_transcript",
                    created_at=created_at,
                )
            )
        return tuple(inserted_messages)

    def _insert_message(
        self,
        conn: psycopg.Connection,
        *,
        message_id: str,
        conversation_id: str,
        message_index: int,
        role: str,
        content: str,
        source: str,
        created_at: datetime,
    ) -> PersistedMessage:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (
                    id,
                    conversation_id,
                    message_index,
                    role,
                    content,
                    source,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message_id,
                    conversation_id,
                    message_index,
                    role,
                    content,
                    source,
                    created_at,
                ),
            )
        return PersistedMessage(
            message_id=message_id,
            message_index=message_index,
            role=role,
            content=content,
            source=source,
        )

    def _insert_model_run(
        self,
        conn: psycopg.Connection,
        *,
        model_run_id: str,
        conversation_id: str,
        assistant_message_id: str | None,
        request_id: str,
        public_model: str,
        runtime_model: str,
        status: str,
        error_type: str | None,
        error_code: str | None,
        error_message: str | None,
        usage: ChatCompletionUsage | None,
        started_at: datetime,
        completed_at: datetime,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_runs (
                    id,
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
                    completed_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    model_run_id,
                    conversation_id,
                    assistant_message_id,
                    request_id,
                    public_model,
                    runtime_model,
                    status,
                    error_type,
                    error_code,
                    error_message,
                    usage.prompt_tokens if usage else None,
                    usage.completion_tokens if usage else None,
                    usage.total_tokens if usage else None,
                    started_at.astimezone(timezone.utc),
                    completed_at.astimezone(timezone.utc),
                ),
            )

    def _touch_conversation(
        self,
        conn: psycopg.Connection,
        *,
        conversation_id: str,
        updated_at: datetime,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE conversations
                SET updated_at = %s
                WHERE id = %s
                """,
                (updated_at.astimezone(timezone.utc), conversation_id),
            )

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"


def matching_prefix_length(
    stored_messages: Sequence[TranscriptMessage],
    request_messages: Sequence[ChatMessage],
) -> int | None:
    if len(stored_messages) > len(request_messages):
        return None

    for index, stored_message in enumerate(stored_messages):
        request_message = request_messages[index]
        if (
            stored_message.role != request_message.role
            or stored_message.content != request_message.content
        ):
            return None

    return len(stored_messages)
