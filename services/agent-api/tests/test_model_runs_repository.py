from datetime import datetime, timezone

from app.schemas.chat import ChatCompletionUsage


class _FakeCursor:
    def __init__(self, connection) -> None:
        self._connection = connection

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

    def cursor(self):
        return _FakeCursor(self)


def test_model_runs_repository_persists_usage_fields() -> None:
    from app.persistence.model_runs_repo import PostgresModelRunsRepository

    connection = _FakeConnection()
    repository = PostgresModelRunsRepository()

    repository.insert_model_run(
        connection,
        model_run_id="run_1",
        conversation_id="conv_1",
        assistant_message_id="msg_assistant",
        request_id="req_1",
        public_model="assistant-v1",
        runtime_model="llama3.1",
        status="completed",
        error_type=None,
        error_code=None,
        error_message=None,
        usage=ChatCompletionUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        started_at=datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 3, 13, 10, 0, 1, tzinfo=timezone.utc),
    )

    assert connection.executed == [
        (
            "INSERT INTO model_runs ( id, conversation_id, assistant_message_id, request_id, public_profile, runtime_model, status, error_type, error_code, error_message, prompt_tokens, completion_tokens, total_tokens, started_at, completed_at ) VALUES ( %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s )",
            (
                "run_1",
                "conv_1",
                "msg_assistant",
                "req_1",
                "assistant-v1",
                "llama3.1",
                "completed",
                None,
                None,
                None,
                11,
                7,
                18,
                datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 13, 10, 0, 1, tzinfo=timezone.utc),
            ),
        )
    ]
