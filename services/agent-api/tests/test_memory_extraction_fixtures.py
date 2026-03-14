from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings
from app.modules.chat.formatters import ChatPromptFormatter
from app.modules.chat.memory import MemoryService
from app.persistence.models import ChatPersistenceResult, PersistedMessage


@dataclass(frozen=True, slots=True)
class _ExtractionFixture:
    name: str
    role: str
    content: str
    source: str = "request_transcript"
    expected_stored: bool = True


class _FixtureOllamaClient(OllamaChatClient):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def embed(self, model: str, input_text: str | list[str]) -> list[list[float]]:
        self.calls.append({"model": model, "input_text": input_text})
        inputs = input_text if isinstance(input_text, list) else [input_text]
        return [[1.0, 0.0] for _ in inputs]


class _FixtureMemoryRepository:
    def __init__(self) -> None:
        self.store_memory_calls: list[dict[str, object]] = []

    def retrieve_memory(self, **kwargs):
        _ = kwargs
        return []

    def record_retrieval(self, **kwargs):
        _ = kwargs

    def store_memory_items(self, **kwargs):
        self.store_memory_calls.append(kwargs)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ollama_base_url": "http://ollama:11434",
        "ollama_chat_model": "qwen3:8b",
        "ollama_fast_chat_model": "qwen3:8b",
        "ollama_timeout_seconds": 30.0,
        "database_url": "postgresql://assistant:change-me@postgres:5432/assistant",
        "internal_openai_api_key": "secret",
        "memory_enabled": True,
        "ollama_embed_model": "all-minilm",
        "memory_top_k": 3,
        "memory_min_score": 0.35,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.parametrize(
    "fixture",
    (
        _ExtractionFixture(
            name="short_identity_signal",
            role="user",
            content="Call me Alex.",
            expected_stored=True,
        ),
        _ExtractionFixture(
            name="stable_preference_signal",
            role="user",
            content="I prefer concise answers.",
            expected_stored=True,
        ),
        _ExtractionFixture(
            name="low_signal_acknowledgement",
            role="user",
            content="Thanks, that helps.",
            expected_stored=False,
        ),
        _ExtractionFixture(
            name="transient_update",
            role="user",
            content="I had lunch already today.",
            expected_stored=False,
        ),
        _ExtractionFixture(
            name="question_not_materialized",
            role="user",
            content="Do I like jazz?",
            expected_stored=False,
        ),
        _ExtractionFixture(
            name="assistant_turn_ignored",
            role="assistant",
            content="My favorite color is blue.",
            expected_stored=False,
        ),
    ),
    ids=lambda fixture: fixture.name,
)
def test_memory_extraction_fixtures_bound_candidate_growth(
    fixture: _ExtractionFixture,
) -> None:
    repository = _FixtureMemoryRepository()
    ollama_client = _FixtureOllamaClient()
    service = MemoryService(
        settings=_settings(),
        ollama_client=ollama_client,
        repository=repository,
        prompt_formatter=ChatPromptFormatter(),
    )
    persistence = ChatPersistenceResult(
        conversation_id="conv_fixture",
        assistant_message_id="msg_assistant",
        model_run_id="run_fixture",
        persisted_messages=(
            PersistedMessage(
                message_id="msg_fixture",
                message_index=0,
                role=fixture.role,
                content=fixture.content,
                source=fixture.source,
            ),
        ),
    )

    service.store_items(
        request_id=f"req_{fixture.name}",
        conversation_id="conv_fixture",
        persistence=persistence,
        created_at=datetime(2026, 3, 14, 13, 0, tzinfo=timezone.utc),
    )

    if fixture.expected_stored:
        assert len(repository.store_memory_calls) == 1
        stored_messages = repository.store_memory_calls[0]["messages"]
        assert tuple(message.message_id for message in stored_messages) == ("msg_fixture",)
        assert ollama_client.calls == [
            {"model": "all-minilm", "input_text": [fixture.content]}
        ]
    else:
        assert repository.store_memory_calls == []
        assert ollama_client.calls == []
