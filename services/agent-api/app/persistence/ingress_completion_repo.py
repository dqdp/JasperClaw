from datetime import datetime, timezone

import psycopg

from app.core.errors import APIError
from app.persistence.models import IngressCompletionRecord
from app.schemas.chat import ChatCompletionUsage


class PostgresIngressCompletionRepository:
    """Caches completed Telegram ingress responses by a stable replay key."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def get_completion(
        self,
        *,
        idempotency_key: str,
    ) -> IngressCompletionRecord | None:
        def write(conn: psycopg.Connection) -> IngressCompletionRecord | None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        idempotency_key,
                        source,
                        public_model,
                        conversation_id,
                        response_content,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens
                    FROM ingress_completion_cache
                    WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

        return self._execute(write)

    def store_completion(
        self,
        *,
        idempotency_key: str,
        source: str,
        public_model: str,
        conversation_id: str,
        content: str,
        usage: ChatCompletionUsage | None,
        stored_at: datetime,
    ) -> IngressCompletionRecord:
        stored_at_utc = stored_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> IngressCompletionRecord:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ingress_completion_cache (
                        idempotency_key,
                        source,
                        public_model,
                        conversation_id,
                        response_content,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING
                        idempotency_key,
                        source,
                        public_model,
                        conversation_id,
                        response_content,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens
                    """,
                    (
                        idempotency_key,
                        source,
                        public_model,
                        conversation_id,
                        content,
                        usage.prompt_tokens if usage is not None else None,
                        usage.completion_tokens if usage is not None else None,
                        usage.total_tokens if usage is not None else None,
                        stored_at_utc,
                        stored_at_utc,
                    ),
                )
                row = cur.fetchone()
            if row is not None:
                return self._row_to_record(row)
            existing = self.get_completion(idempotency_key=idempotency_key)
            if existing is None:
                raise APIError(
                    status_code=503,
                    error_type="dependency_unavailable",
                    code="storage_unavailable",
                    message="Persistent storage unavailable",
                )
            return existing

        return self._execute(write)

    def _row_to_record(self, row) -> IngressCompletionRecord:
        prompt_tokens = row[5]
        completion_tokens = row[6]
        total_tokens = row[7]
        usage = None
        if any(value is not None for value in (prompt_tokens, completion_tokens, total_tokens)):
            usage = ChatCompletionUsage(
                prompt_tokens=int(prompt_tokens or 0),
                completion_tokens=int(completion_tokens or 0),
                total_tokens=int(total_tokens or 0),
            )
        return IngressCompletionRecord(
            idempotency_key=row[0],
            source=row[1],
            public_model=row[2],
            conversation_id=row[3],
            content=row[4],
            usage=usage,
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
