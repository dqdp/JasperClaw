from datetime import datetime
from typing import Sequence
from uuid import uuid4

import psycopg

from app.core.errors import APIError
from app.persistence.models import ConversationContext, TranscriptMessage
from app.persistence.transcript_repo import PostgresTranscriptRepository
from app.schemas.chat import ChatMessage


class PostgresConversationRepository:
    """Owns conversation identity, bindings, and transcript-based matching."""

    def __init__(
        self,
        *,
        transcript_repository: PostgresTranscriptRepository,
    ) -> None:
        self._transcript_repository = transcript_repository

    def resolve_conversation(
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

    def resolve_append_target(
        self,
        conn: psycopg.Connection,
        *,
        public_model: str,
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
            context = self._resolve_explicit_append_conversation(
                conn,
                conversation_id_hint=conversation_id_hint,
                public_model=public_model,
            )
            if context is not None:
                return context
            raise APIError(
                status_code=409,
                error_type="validation_error",
                code="conversation_mismatch",
                message="Conversation hint does not match the persisted conversation",
            )

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

    def touch_conversation(
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
                (updated_at, conversation_id),
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

        transcript = self._transcript_repository.load_transcript(conn, row[0])
        prefix_length = matching_prefix_length(transcript, request_messages)
        if prefix_length is None:
            return None

        return ConversationContext(
            conversation_id=row[0],
            existing_message_count=prefix_length,
            matched_request_message_count=prefix_length,
            conversation_created=False,
        )

    def _resolve_explicit_append_conversation(
        self,
        conn: psycopg.Connection,
        *,
        conversation_id_hint: str,
        public_model: str,
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

        transcript = self._transcript_repository.load_transcript(conn, row[0])
        return ConversationContext(
            conversation_id=row[0],
            existing_message_count=len(transcript),
            matched_request_message_count=0,
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

        transcript = self._transcript_repository.load_transcript(conn, row[0])
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
            transcript = self._transcript_repository.load_transcript(
                conn,
                bound_conversation_id,
            )
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
            transcript = self._transcript_repository.load_transcript(conn, conversation_id)
            # Placeholder conversations are ignored until they carry transcript state.
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
