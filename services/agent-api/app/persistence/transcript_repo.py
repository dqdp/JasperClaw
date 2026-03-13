from datetime import datetime
from uuid import uuid4

import psycopg

from app.persistence.models import PersistedMessage, TranscriptMessage
from app.schemas.chat import ChatMessage


class PostgresTranscriptRepository:
    """Owns transcript reads and message writes within an existing transaction."""

    def load_transcript(
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

    def insert_request_messages(
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
                self.insert_message(
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

    def insert_message(
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

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"
