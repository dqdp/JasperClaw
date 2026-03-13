from datetime import datetime, timezone

from app.schemas.chat import ChatMessage


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
        if normalized.startswith(
            "SELECT role, content FROM messages WHERE conversation_id = %s"
        ):
            conversation_id = params[0]
            self._rows = list(self._connection.transcripts[conversation_id])
            return
        self._rows = []

    def fetchall(self):
        return list(self._rows)


class _FakeConnection:
    def __init__(self) -> None:
        self.executed = []
        self.transcripts = {
            "conv_1": [("user", "Hello"), ("assistant", "Hi")],
        }

    def cursor(self):
        return _FakeCursor(self)


def test_transcript_repository_loads_ordered_messages() -> None:
    from app.persistence.models import TranscriptMessage
    from app.persistence.transcript_repo import PostgresTranscriptRepository

    repository = PostgresTranscriptRepository()
    transcript = repository.load_transcript(_FakeConnection(), "conv_1")

    assert transcript == [
        TranscriptMessage(role="user", content="Hello"),
        TranscriptMessage(role="assistant", content="Hi"),
    ]


def test_transcript_repository_inserts_only_unmatched_request_messages(monkeypatch) -> None:
    from app.persistence.models import PersistedMessage
    from app.persistence.transcript_repo import PostgresTranscriptRepository

    connection = _FakeConnection()
    repository = PostgresTranscriptRepository()
    generated_ids = iter(("msg_1", "msg_2"))
    monkeypatch.setattr(repository, "_new_id", lambda prefix: next(generated_ids))

    persisted = repository.insert_request_messages(
        connection,
        conversation_id="conv_1",
        starting_index=3,
        matched_request_message_count=1,
        request_messages=[
            ChatMessage(role="user", content="Already persisted"),
            ChatMessage(role="assistant", content="New answer"),
            ChatMessage(role="user", content="Follow-up"),
        ],
        created_at=datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc),
    )

    assert persisted == (
        PersistedMessage(
            message_id="msg_1",
            message_index=3,
            role="assistant",
            content="New answer",
            source="request_transcript",
        ),
        PersistedMessage(
            message_id="msg_2",
            message_index=4,
            role="user",
            content="Follow-up",
            source="request_transcript",
        ),
    )
    assert len(connection.executed) == 2
    assert connection.executed[0][1][0:4] == ("msg_1", "conv_1", 3, "assistant")
    assert connection.executed[1][1][0:4] == ("msg_2", "conv_1", 4, "user")
