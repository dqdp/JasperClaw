import json
from datetime import datetime, timezone

from app.persistence.models import PendingToolConfirmationRecord


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False


class _FakeCursor:
    def __init__(self, connection) -> None:
        self._connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def execute(self, sql, params=None) -> None:
        normalized = " ".join(sql.split())
        self._connection.executed.append((normalized, params))
        if (
            normalized.startswith(
                "SELECT id, conversation_id, request_id, source_class, tool_name, status, clarification_count, request_payload_json, created_at, expires_at, resolved_at FROM pending_tool_confirmations"
            )
            or normalized.startswith(
                "UPDATE pending_tool_confirmations SET clarification_count = clarification_count + 1 WHERE id = %s AND conversation_id = %s AND status = %s RETURNING"
            )
        ):
            self._rows = list(self._connection.rows)
            return
        self._rows = []

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows.pop(0)


class _FakeConnection:
    def __init__(self) -> None:
        self.executed = []
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def transaction(self):
        return _FakeTransaction()

    def cursor(self):
        return _FakeCursor(self)


def test_pending_confirmation_repository_replaces_existing_pending(monkeypatch) -> None:
    from app.persistence.pending_confirmation_repo import (
        PostgresPendingToolConfirmationRepository,
    )

    fake_connection = _FakeConnection()
    monkeypatch.setattr(
        "app.persistence.pending_confirmation_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )
    repository = PostgresPendingToolConfirmationRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )

    created_at = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 3, 15, 10, 0, 30, tzinfo=timezone.utc)
    record = repository.replace_pending_confirmation(
        confirmation_id="confirm_123",
        conversation_id="conv_1",
        request_id="req_1",
        source_class="agent_api",
        tool_name="telegram-send",
        arguments={"alias": "wife", "text": "Running late"},
        created_at=created_at,
        expires_at=expires_at,
    )

    assert record == PendingToolConfirmationRecord(
        confirmation_id="confirm_123",
        conversation_id="conv_1",
        request_id="req_1",
        source_class="agent_api",
        tool_name="telegram-send",
        status="pending",
        clarification_count=0,
        arguments={"alias": "wife", "text": "Running late"},
        created_at=created_at,
        expires_at=expires_at,
        resolved_at=None,
    )
    assert fake_connection.executed == [
        (
            "UPDATE pending_tool_confirmations SET status = %s, resolved_at = %s WHERE conversation_id = %s AND status = %s",
            ("superseded", created_at, "conv_1", "pending"),
        ),
        (
            "INSERT INTO pending_tool_confirmations ( id, conversation_id, request_id, source_class, tool_name, status, clarification_count, request_payload_json, created_at, expires_at, resolved_at ) VALUES ( %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s )",
            (
                "confirm_123",
                "conv_1",
                "req_1",
                "agent_api",
                "telegram-send",
                "pending",
                0,
                json.dumps({"alias": "wife", "text": "Running late"}),
                created_at,
                expires_at,
                None,
            ),
        ),
    ]


def test_pending_confirmation_repository_loads_active_pending(monkeypatch) -> None:
    from app.persistence.pending_confirmation_repo import (
        PostgresPendingToolConfirmationRepository,
    )

    fake_connection = _FakeConnection()
    fake_connection.rows = [
        (
            "confirm_123",
            "conv_1",
            "req_1",
            "agent_api",
            "telegram-send",
            "pending",
            1,
            {"alias": "wife", "text": "Running late"},
            datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 15, 10, 0, 30, tzinfo=timezone.utc),
            None,
        )
    ]
    monkeypatch.setattr(
        "app.persistence.pending_confirmation_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )
    repository = PostgresPendingToolConfirmationRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )

    record = repository.get_active_confirmation(conversation_id="conv_1")

    assert record == PendingToolConfirmationRecord(
        confirmation_id="confirm_123",
        conversation_id="conv_1",
        request_id="req_1",
        source_class="agent_api",
        tool_name="telegram-send",
        status="pending",
        clarification_count=1,
        arguments={"alias": "wife", "text": "Running late"},
        created_at=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 3, 15, 10, 0, 30, tzinfo=timezone.utc),
        resolved_at=None,
    )
    assert fake_connection.executed == [
        (
            "SELECT id, conversation_id, request_id, source_class, tool_name, status, clarification_count, request_payload_json, created_at, expires_at, resolved_at FROM pending_tool_confirmations WHERE conversation_id = %s AND status = %s ORDER BY created_at DESC LIMIT 1",
            ("conv_1", "pending"),
        )
    ]


def test_pending_confirmation_repository_increments_clarification(monkeypatch) -> None:
    from app.persistence.pending_confirmation_repo import (
        PostgresPendingToolConfirmationRepository,
    )

    fake_connection = _FakeConnection()
    fake_connection.rows = [
        (
            "confirm_123",
            "conv_1",
            "req_1",
            "agent_api",
            "telegram-send",
            "pending",
            2,
            {"alias": "wife", "text": "Running late"},
            datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 15, 10, 0, 30, tzinfo=timezone.utc),
            None,
        )
    ]
    monkeypatch.setattr(
        "app.persistence.pending_confirmation_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )
    repository = PostgresPendingToolConfirmationRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )

    record = repository.increment_pending_confirmation_clarification(
        confirmation_id="confirm_123",
        conversation_id="conv_1",
    )

    assert record is not None
    assert record.clarification_count == 2
    assert fake_connection.executed == [
        (
            "UPDATE pending_tool_confirmations SET clarification_count = clarification_count + 1 WHERE id = %s AND conversation_id = %s AND status = %s RETURNING id, conversation_id, request_id, source_class, tool_name, status, clarification_count, request_payload_json, created_at, expires_at, resolved_at",
            ("confirm_123", "conv_1", "pending"),
        )
    ]
