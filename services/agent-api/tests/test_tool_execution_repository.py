import json
from datetime import datetime, timezone

from app.repositories.postgres import PostgresChatRepository


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


class _FakeConnection:
    def __init__(self) -> None:
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def transaction(self):
        return _FakeTransaction()

    def cursor(self):
        return _FakeCursor(self)


def test_tool_execution_repository_records_json_payloads(monkeypatch) -> None:
    from app.persistence.models import ToolExecutionRecord
    from app.persistence.tool_exec_repo import PostgresToolExecutionRepository

    fake_connection = _FakeConnection()
    monkeypatch.setattr(
        "app.persistence.tool_exec_repo.psycopg.connect",
        lambda database_url: fake_connection,
    )

    repository = PostgresToolExecutionRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    execution = ToolExecutionRecord(
        invocation_id="tool_123",
        tool_name="web-search",
        status="completed",
        arguments={"query": "latest release", "limit": 3},
        output={"results": [{"url": "https://example.test/changelog"}]},
        latency_ms=11.4,
        started_at=datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 3, 13, 10, 0, 1, tzinfo=timezone.utc),
        adapter_name="web_search",
        provider="serpapi",
        policy_decision="allowed",
    )

    repository.record_tool_execution(
        conversation_id="conv_1",
        request_id="req_1",
        model_run_id="run_1",
        tool_execution=execution,
    )

    assert fake_connection.executed == [
        (
            "INSERT INTO tool_executions ( id, conversation_id, model_run_id, request_id, tool_name, status, started_at, finished_at, latency_ms, error_type, error_code, request_payload_json, response_payload_json, policy_decision, adapter_name, provider, created_at ) VALUES ( %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s )",
            (
                "tool_123",
                "conv_1",
                "run_1",
                "req_1",
                "web-search",
                "completed",
                datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 13, 10, 0, 1, tzinfo=timezone.utc),
                11.4,
                None,
                None,
                json.dumps({"query": "latest release", "limit": 3}),
                json.dumps({"results": [{"url": "https://example.test/changelog"}]}),
                "allowed",
                "web_search",
                "serpapi",
                datetime(2026, 3, 13, 10, 0, 1, tzinfo=timezone.utc),
            ),
        )
    ]


def test_chat_repository_delegates_tool_execution_calls() -> None:
    from app.persistence.models import ToolExecutionRecord

    class _FakeToolExecutionRepository:
        def __init__(self) -> None:
            self.calls = []

        def record_tool_execution(self, **kwargs):
            self.calls.append(kwargs)

    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    fake_repository = _FakeToolExecutionRepository()
    repository._tool_execution_repository = fake_repository

    repository.record_tool_execution(
        conversation_id="conv_1",
        request_id="req_1",
        model_run_id="run_1",
        tool_execution=ToolExecutionRecord(
            invocation_id="tool_123",
            tool_name="web-search",
            status="completed",
            arguments={"query": "latest release"},
            output={"results": []},
            latency_ms=11.4,
            started_at=datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 3, 13, 10, 0, 1, tzinfo=timezone.utc),
            adapter_name="web_search",
            provider="serpapi",
            policy_decision="allowed",
        ),
    )

    assert len(fake_repository.calls) == 1
    assert fake_repository.calls[0]["conversation_id"] == "conv_1"
    assert fake_repository.calls[0]["model_run_id"] == "run_1"
