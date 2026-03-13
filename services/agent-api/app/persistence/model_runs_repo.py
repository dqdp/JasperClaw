from datetime import datetime, timezone

import psycopg

from app.schemas.chat import ChatCompletionUsage


class PostgresModelRunsRepository:
    """Owns model run audit writes within an existing transaction."""

    def insert_model_run(
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
