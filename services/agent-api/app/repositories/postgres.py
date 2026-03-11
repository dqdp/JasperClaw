from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

import psycopg

from app.core.errors import APIError
from app.migrations import MigrationRunner
from app.schemas.chat import ChatCompletionUsage, ChatMessage


@dataclass(frozen=True, slots=True)
class ChatPersistenceResult:
    conversation_id: str
    assistant_message_id: str | None
    model_run_id: str


class ChatRepository(Protocol):
    def record_successful_completion(
        self,
        *,
        request_id: str,
        public_model: str,
        runtime_model: str,
        request_messages: list[ChatMessage],
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
        error_type: str,
        error_code: str,
        error_message: str,
        started_at: datetime,
        completed_at: datetime,
    ) -> ChatPersistenceResult: ...


class PostgresChatRepository:
    def __init__(self, database_url: str, migration_runner: MigrationRunner) -> None:
        self._database_url = database_url
        self._migration_runner = migration_runner

    def record_successful_completion(
        self,
        *,
        request_id: str,
        public_model: str,
        runtime_model: str,
        request_messages: list[ChatMessage],
        response_content: str,
        usage: ChatCompletionUsage | None,
        started_at: datetime,
        completed_at: datetime,
    ) -> ChatPersistenceResult:
        conversation_id = self._new_id("conv")
        assistant_message_id = self._new_id("msg")
        model_run_id = self._new_id("run")
        created_at = completed_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> None:
            self._insert_conversation(
                conn,
                conversation_id=conversation_id,
                public_model=public_model,
                created_at=created_at,
            )
            self._insert_request_messages(
                conn,
                conversation_id=conversation_id,
                request_messages=request_messages,
                created_at=created_at,
            )
            self._insert_message(
                conn,
                message_id=assistant_message_id,
                conversation_id=conversation_id,
                message_index=len(request_messages),
                role="assistant",
                content=response_content,
                source="assistant_response",
                created_at=created_at,
            )
            self._insert_model_run(
                conn,
                model_run_id=model_run_id,
                conversation_id=conversation_id,
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

        self._execute_write(write)
        return ChatPersistenceResult(
            conversation_id=conversation_id,
            assistant_message_id=assistant_message_id,
            model_run_id=model_run_id,
        )

    def record_failed_completion(
        self,
        *,
        request_id: str,
        public_model: str,
        runtime_model: str,
        request_messages: list[ChatMessage],
        error_type: str,
        error_code: str,
        error_message: str,
        started_at: datetime,
        completed_at: datetime,
    ) -> ChatPersistenceResult:
        conversation_id = self._new_id("conv")
        model_run_id = self._new_id("run")
        created_at = completed_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> None:
            self._insert_conversation(
                conn,
                conversation_id=conversation_id,
                public_model=public_model,
                created_at=created_at,
            )
            self._insert_request_messages(
                conn,
                conversation_id=conversation_id,
                request_messages=request_messages,
                created_at=created_at,
            )
            self._insert_model_run(
                conn,
                model_run_id=model_run_id,
                conversation_id=conversation_id,
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

        self._execute_write(write)
        return ChatPersistenceResult(
            conversation_id=conversation_id,
            assistant_message_id=None,
            model_run_id=model_run_id,
        )

    def _execute_write(self, operation) -> None:
        try:
            self._migration_runner.ensure_current()
            with psycopg.connect(self._database_url) as conn:
                with conn.transaction():
                    operation(conn)
        except psycopg.Error as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="storage_unavailable",
                message="Persistent storage unavailable",
            ) from exc

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
                INSERT INTO conversations (id, public_profile, created_at)
                VALUES (%s, %s, %s)
                """,
                (conversation_id, public_model, created_at),
            )

    def _insert_request_messages(
        self,
        conn: psycopg.Connection,
        *,
        conversation_id: str,
        request_messages: list[ChatMessage],
        created_at: datetime,
    ) -> None:
        for index, message in enumerate(request_messages):
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

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"
