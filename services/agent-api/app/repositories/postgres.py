from datetime import datetime, timezone
from typing import Protocol, Sequence
from uuid import uuid4

import psycopg

from app.core.errors import APIError
from app.persistence.conversations_repo import (
    PostgresConversationRepository,
    matching_prefix_length,
)
from app.persistence.memory_repo import PostgresMemoryRepository
from app.persistence.model_runs_repo import PostgresModelRunsRepository
from app.persistence.models import (
    ChatPersistenceResult,
    ConversationContext,
    MemoryRetrievalRecord,
    MemorySearchHit,
    PersistedMessage,
    TranscriptionPersistenceResult,
    ToolExecutionRecord,
    TranscriptMessage,
)
from app.persistence.transcript_repo import PostgresTranscriptRepository
from app.persistence.tool_exec_repo import PostgresToolExecutionRepository
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

    def record_transcription(
        self,
        *,
        public_model: str,
        conversation_id_hint: str | None,
        transcript: str,
        created_at: datetime,
    ) -> TranscriptionPersistenceResult: ...

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
        self._transcript_repository = PostgresTranscriptRepository()
        self._conversation_repository = PostgresConversationRepository(
            transcript_repository=self._transcript_repository
        )
        self._model_runs_repository = PostgresModelRunsRepository()
        self._memory_repository = PostgresMemoryRepository(database_url)
        self._tool_execution_repository = PostgresToolExecutionRepository(database_url)

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
            return self._conversation_repository.resolve_conversation(
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
            context = self._conversation_repository.resolve_conversation(
                conn,
                public_model=public_model,
                request_messages=request_messages,
                conversation_id_hint=conversation_id_hint,
                client_source=client_source,
                client_conversation_id=client_conversation_id,
                created_at=created_at,
            )
            model_run_id = self._new_id("run")
            request_persisted_messages = self._transcript_repository.insert_request_messages(
                conn,
                conversation_id=context.conversation_id,
                starting_index=context.existing_message_count,
                matched_request_message_count=context.matched_request_message_count,
                request_messages=request_messages,
                created_at=created_at,
            )
            assistant_persisted_message = self._transcript_repository.insert_message(
                conn,
                message_id=assistant_message_id,
                conversation_id=context.conversation_id,
                message_index=len(request_messages),
                role="assistant",
                content=response_content,
                source="assistant_response",
                created_at=created_at,
            )
            self._model_runs_repository.insert_model_run(
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
            self._conversation_repository.touch_conversation(
                conn,
                conversation_id=context.conversation_id,
                updated_at=completed_at.astimezone(timezone.utc),
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
            context = self._conversation_repository.resolve_conversation(
                conn,
                public_model=public_model,
                request_messages=request_messages,
                conversation_id_hint=conversation_id_hint,
                client_source=client_source,
                client_conversation_id=client_conversation_id,
                created_at=created_at,
            )
            model_run_id = self._new_id("run")
            request_persisted_messages = self._transcript_repository.insert_request_messages(
                conn,
                conversation_id=context.conversation_id,
                starting_index=context.existing_message_count,
                matched_request_message_count=context.matched_request_message_count,
                request_messages=request_messages,
                created_at=created_at,
            )
            self._model_runs_repository.insert_model_run(
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
            self._conversation_repository.touch_conversation(
                conn,
                conversation_id=context.conversation_id,
                updated_at=completed_at.astimezone(timezone.utc),
            )
            return ChatPersistenceResult(
                conversation_id=context.conversation_id,
                assistant_message_id=None,
                model_run_id=model_run_id,
                persisted_messages=tuple(request_persisted_messages),
            )

        return self._execute(write)

    def record_transcription(
        self,
        *,
        public_model: str,
        conversation_id_hint: str | None,
        transcript: str,
        created_at: datetime,
    ) -> TranscriptionPersistenceResult:
        persisted_at = created_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> TranscriptionPersistenceResult:
            context = self._conversation_repository.resolve_append_target(
                conn,
                public_model=public_model,
                conversation_id_hint=conversation_id_hint,
                client_source=None,
                client_conversation_id=None,
                created_at=persisted_at,
            )
            persisted_message = self._transcript_repository.insert_message(
                conn,
                message_id=self._new_id("msg"),
                conversation_id=context.conversation_id,
                message_index=context.existing_message_count,
                role="user",
                content=transcript,
                source="audio_transcription",
                created_at=persisted_at,
            )
            self._conversation_repository.touch_conversation(
                conn,
                conversation_id=context.conversation_id,
                updated_at=persisted_at,
            )
            return TranscriptionPersistenceResult(
                conversation_id=context.conversation_id,
                persisted_message=persisted_message,
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
        self._tool_execution_repository.record_tool_execution(
            conversation_id=conversation_id,
            request_id=request_id,
            model_run_id=model_run_id,
            tool_execution=tool_execution,
        )

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

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"
