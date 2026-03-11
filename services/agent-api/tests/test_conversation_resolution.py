from app.repositories.postgres import (
    PostgresChatRepository,
    TranscriptMessage,
    matching_prefix_length,
)
from app.schemas.chat import ChatMessage


def test_matching_prefix_length_returns_full_prefix_match() -> None:
    stored_messages = [
        TranscriptMessage(role="user", content="Hello"),
        TranscriptMessage(role="assistant", content="Hi"),
    ]
    request_messages = [
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="Hi"),
        ChatMessage(role="user", content="How are you?"),
    ]

    assert matching_prefix_length(stored_messages, request_messages) == 2


def test_matching_prefix_length_rejects_mismatched_transcript() -> None:
    stored_messages = [
        TranscriptMessage(role="user", content="Hello"),
        TranscriptMessage(role="assistant", content="Different"),
    ]
    request_messages = [
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="Hi"),
    ]

    assert matching_prefix_length(stored_messages, request_messages) is None


def test_matching_prefix_length_rejects_longer_stored_transcript() -> None:
    stored_messages = [
        TranscriptMessage(role="user", content="Hello"),
        TranscriptMessage(role="assistant", content="Hi"),
        TranscriptMessage(role="user", content="Question"),
    ]
    request_messages = [
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="Hi"),
    ]

    assert matching_prefix_length(stored_messages, request_messages) is None


def test_resolve_by_transcript_prefix_ignores_empty_transcripts() -> None:
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
            if normalized.startswith("SELECT id FROM conversations"):
                self._rows = [("conv_empty",)]
                return
            if normalized.startswith("SELECT role, content FROM messages"):
                conversation_id = params[0]
                self._rows = self._connection.transcripts[conversation_id]
                return
            raise AssertionError(f"Unexpected SQL: {normalized}")

        def fetchall(self):
            return list(self._rows)

    class _FakeConnection:
        def __init__(self) -> None:
            self.transcripts = {"conv_empty": []}

        def cursor(self):
            return _FakeCursor(self)

    repository = PostgresChatRepository(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant"
    )
    request_messages = [ChatMessage(role="user", content="Hello")]

    context = repository._resolve_by_transcript_prefix(
        _FakeConnection(),
        public_model="assistant-v1",
        request_messages=request_messages,
    )

    assert context is None
