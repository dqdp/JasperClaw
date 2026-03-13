from app.persistence.conversations_repo import (
    PostgresConversationRepository,
    matching_prefix_length,
)
from app.persistence.models import TranscriptMessage
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
    class _FakeTranscriptRepository:
        def __init__(self) -> None:
            self.transcripts = {"conv_empty": []}

        def load_transcript(self, conn, conversation_id: str):
            _ = conn
            return self.transcripts[conversation_id]

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
            raise AssertionError(f"Unexpected SQL: {normalized}")

        def fetchall(self):
            return list(self._rows)

    class _FakeConnection:
        def cursor(self):
            return _FakeCursor(self)

    repository = PostgresConversationRepository(
        transcript_repository=_FakeTranscriptRepository(),
    )
    request_messages = [ChatMessage(role="user", content="Hello")]

    context = repository._resolve_by_transcript_prefix(
        _FakeConnection(),
        public_model="assistant-v1",
        request_messages=request_messages,
    )

    assert context is None
