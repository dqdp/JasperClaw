import json
from datetime import timezone

import psycopg

from app.core.errors import APIError
from app.persistence.models import PendingToolConfirmationRecord


class PostgresPendingToolConfirmationRepository:
    """Owns durable pending confirmation state for side-effectful chat actions."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def get_active_confirmation(
        self,
        *,
        conversation_id: str,
    ) -> PendingToolConfirmationRecord | None:
        def write(conn: psycopg.Connection) -> PendingToolConfirmationRecord | None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        conversation_id,
                        request_id,
                        source_class,
                        tool_name,
                        status,
                        clarification_count,
                        request_payload_json,
                        created_at,
                        expires_at,
                        resolved_at
                    FROM pending_tool_confirmations
                    WHERE conversation_id = %s AND status = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (conversation_id, "pending"),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

        return self._execute(write)

    def replace_pending_confirmation(
        self,
        *,
        confirmation_id: str,
        conversation_id: str,
        request_id: str,
        source_class: str,
        tool_name: str,
        arguments: dict[str, object],
        created_at,
        expires_at,
    ) -> PendingToolConfirmationRecord:
        payload_json = json.dumps(arguments)

        def write(conn: psycopg.Connection) -> PendingToolConfirmationRecord:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pending_tool_confirmations
                    SET status = %s, resolved_at = %s
                    WHERE conversation_id = %s AND status = %s
                    """,
                    (
                        "superseded",
                        created_at.astimezone(timezone.utc),
                        conversation_id,
                        "pending",
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO pending_tool_confirmations (
                        id,
                        conversation_id,
                        request_id,
                        source_class,
                        tool_name,
                        status,
                        clarification_count,
                        request_payload_json,
                        created_at,
                        expires_at,
                        resolved_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s
                    )
                    """,
                    (
                        confirmation_id,
                        conversation_id,
                        request_id,
                        source_class,
                        tool_name,
                        "pending",
                        0,
                        payload_json,
                        created_at.astimezone(timezone.utc),
                        expires_at.astimezone(timezone.utc),
                        None,
                    ),
                )
            return PendingToolConfirmationRecord(
                confirmation_id=confirmation_id,
                conversation_id=conversation_id,
                request_id=request_id,
                source_class=source_class,
                tool_name=tool_name,
                status="pending",
                clarification_count=0,
                arguments=dict(arguments),
                created_at=created_at.astimezone(timezone.utc),
                expires_at=expires_at.astimezone(timezone.utc),
                resolved_at=None,
            )

        return self._execute(write)

    def resolve_pending_confirmation(
        self,
        *,
        confirmation_id: str,
        conversation_id: str,
        status: str,
        resolved_at,
        expected_status: str | None = None,
    ) -> PendingToolConfirmationRecord | None:
        def write(conn: psycopg.Connection) -> PendingToolConfirmationRecord | None:
            with conn.cursor() as cur:
                if expected_status is None:
                    cur.execute(
                        """
                        UPDATE pending_tool_confirmations
                        SET status = %s, resolved_at = %s
                        WHERE id = %s AND conversation_id = %s
                        RETURNING
                            id,
                            conversation_id,
                            request_id,
                            source_class,
                            tool_name,
                            status,
                            clarification_count,
                            request_payload_json,
                            created_at,
                            expires_at,
                            resolved_at
                        """,
                        (
                            status,
                            resolved_at.astimezone(timezone.utc),
                            confirmation_id,
                            conversation_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE pending_tool_confirmations
                        SET status = %s, resolved_at = %s
                        WHERE id = %s AND conversation_id = %s AND status = %s
                        RETURNING
                            id,
                            conversation_id,
                            request_id,
                            source_class,
                            tool_name,
                            status,
                            clarification_count,
                            request_payload_json,
                            created_at,
                            expires_at,
                            resolved_at
                        """,
                        (
                            status,
                            resolved_at.astimezone(timezone.utc),
                            confirmation_id,
                            conversation_id,
                            expected_status,
                        ),
                    )
                row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

        return self._execute(write)

    def increment_pending_confirmation_clarification(
        self,
        *,
        confirmation_id: str,
        conversation_id: str,
    ) -> PendingToolConfirmationRecord | None:
        def write(conn: psycopg.Connection) -> PendingToolConfirmationRecord | None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pending_tool_confirmations
                    SET clarification_count = clarification_count + 1
                    WHERE id = %s AND conversation_id = %s AND status = %s
                    RETURNING
                        id,
                        conversation_id,
                        request_id,
                        source_class,
                        tool_name,
                        status,
                        clarification_count,
                        request_payload_json,
                        created_at,
                        expires_at,
                        resolved_at
                    """,
                    (
                        confirmation_id,
                        conversation_id,
                        "pending",
                    ),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

        return self._execute(write)

    def _row_to_record(self, row) -> PendingToolConfirmationRecord:
        payload = row[7]
        if not isinstance(payload, dict):
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="storage_unavailable",
                message="Persistent storage unavailable",
            )
        return PendingToolConfirmationRecord(
            confirmation_id=row[0],
            conversation_id=row[1],
            request_id=row[2],
            source_class=row[3],
            tool_name=row[4],
            status=row[5],
            clarification_count=int(row[6]),
            arguments=payload,
            created_at=row[8],
            expires_at=row[9],
            resolved_at=row[10],
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
