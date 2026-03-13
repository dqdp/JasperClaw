import json
from datetime import timezone

import psycopg

from app.core.errors import APIError
from app.persistence.models import ToolExecutionRecord


class PostgresToolExecutionRepository:
    """Owns tool execution audit writes."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

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
