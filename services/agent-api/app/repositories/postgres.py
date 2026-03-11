from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, Sequence
from uuid import uuid4

import psycopg

from app.core.errors import APIError
from app.schemas.chat import ChatCompletionUsage, ChatMessage


@dataclass(frozen=True, slots=True)
class ChatPersistenceResult:
    conversation_id: str
    assistant_message_id: str | None
    model_run_id: str


@dataclass(frozen=True, slots=True)
class TranscriptMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ConversationContext:
    conversation_id: str
    existing_message_count: int
    conversation_created: bool


class ChatRepository(Protocol):
    def prepare_conversation(
        self,
        *,
        public_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
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
        error_type: str,
        error_code: str,
        error_message: str,
        started_at: datetime,
        completed_at: datetime,
    ) -> ChatPersistenceResult: ...


class PostgresChatRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def prepare_conversation(
        self,
        *,
        public_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
        created_at: datetime,
    ) -> ConversationContext:
        def write(conn: psycopg.Connection) -> ConversationContext:
            return self._resolve_conversation(
                conn,
                public_model=public_model,
                request_messages=request_messages,
                conversation_id_hint=conversation_id_hint,
                created_at=created_at.astimezone(timezone.utc),
            )

        return self._execute_write(write)

    def record_successful_completion(
        self,
        *,
        request_id: str,
        public_model: str,
        runtime_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
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
                created_at=created_at,
            )
            model_run_id = self._new_id("run")
            self._insert_request_messages(
                conn,
                conversation_id=context.conversation_id,
                starting_index=context.existing_message_count,
                request_messages=request_messages,
                created_at=created_at,
            )
            self._insert_message(
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
            )

        return self._execute_write(write)

    def record_failed_completion(
        self,
        *,
        request_id: str,
        public_model: str,
        runtime_model: str,
        request_messages: list[ChatMessage],
        conversation_id_hint: str | None,
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
                created_at=created_at,
            )
            model_run_id = self._new_id("run")
            self._insert_request_messages(
                conn,
                conversation_id=context.conversation_id,
                starting_index=context.existing_message_count,
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
            )

        return self._execute_write(write)

    def _execute_write(self, operation) -> ChatPersistenceResult:
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
        created_at: datetime,
    ) -> ConversationContext:
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
            conversation_created=False,
        )

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

    def _insert_request_messages(
        self,
        conn: psycopg.Connection,
        *,
        conversation_id: str,
        starting_index: int,
        request_messages: list[ChatMessage],
        created_at: datetime,
    ) -> None:
        for index, message in enumerate(request_messages[starting_index:], start=starting_index):
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
    ) -> None:
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
