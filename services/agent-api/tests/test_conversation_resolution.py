from app.repositories.postgres import TranscriptMessage, matching_prefix_length
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
