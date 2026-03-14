from dataclasses import dataclass

import pytest

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings
from app.modules.chat.formatters import ChatPromptFormatter
from app.modules.chat.memory import MemoryService
from app.persistence.models import MemorySearchHit
from app.schemas.chat import ChatCompletionRequest, ChatMessage


@dataclass(frozen=True, slots=True)
class _FixtureMemoryItem:
    memory_item_id: str
    source_message_id: str
    content: str
    embedding: tuple[float, float]
    status: str = "active"


@dataclass(frozen=True, slots=True)
class _RetrievalFixture:
    name: str
    query_text: str
    query_embedding: tuple[float, float]
    memory_items: tuple[_FixtureMemoryItem, ...]
    expected_hit_ids: tuple[str, ...]
    expected_present_snippets: tuple[str, ...]
    expected_absent_snippets: tuple[str, ...] = ()


class _FixtureOllamaClient(OllamaChatClient):
    def __init__(self, *, query_embedding: tuple[float, float]) -> None:
        self._query_embedding = list(query_embedding)

    def embed(self, model: str, input_text: str | list[str]) -> list[list[float]]:
        _ = model, input_text
        return [list(self._query_embedding)]


class _FixtureMemoryRepository:
    def __init__(self, *, memory_items: tuple[_FixtureMemoryItem, ...]) -> None:
        self._memory_items = memory_items

    def retrieve_memory(self, **kwargs) -> list[MemorySearchHit]:
        query_embedding = kwargs["query_embedding"]
        limit = kwargs["limit"]
        min_score = kwargs["min_score"]

        hits: list[MemorySearchHit] = []
        for item in self._memory_items:
            if item.status != "active":
                continue
            score = _dot(query_embedding, item.embedding)
            if score < min_score:
                continue
            hits.append(
                MemorySearchHit(
                    memory_item_id=item.memory_item_id,
                    source_message_id=item.source_message_id,
                    content=item.content,
                    score=score,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.memory_item_id))
        return hits[:limit]

    def record_retrieval(self, **kwargs) -> None:
        _ = kwargs

    def store_memory_items(self, **kwargs) -> None:
        _ = kwargs


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


def _dot(left: list[float] | tuple[float, float], right: tuple[float, float]) -> float:
    return round(sum(a * b for a, b in zip(left, right, strict=True)), 4)


@pytest.mark.parametrize(
    "fixture",
    (
        _RetrievalFixture(
            name="positive_preference_recall",
            query_text="What do you remember about my preferences?",
            query_embedding=(1.0, 0.0),
            memory_items=(
                _FixtureMemoryItem(
                    memory_item_id="mem_blue",
                    source_message_id="msg_1",
                    content="Favorite color is blue.",
                    embedding=(0.93, 0.07),
                ),
                _FixtureMemoryItem(
                    memory_item_id="mem_noise",
                    source_message_id="msg_2",
                    content="Lives near a train station.",
                    embedding=(0.22, 0.78),
                ),
            ),
            expected_hit_ids=("mem_blue",),
            expected_present_snippets=("Favorite color is blue.",),
        ),
        _RetrievalFixture(
            name="false_positive_control",
            query_text="What do you remember about my preferences?",
            query_embedding=(1.0, 0.0),
            memory_items=(
                _FixtureMemoryItem(
                    memory_item_id="mem_noise",
                    source_message_id="msg_2",
                    content="Lives near a train station.",
                    embedding=(0.22, 0.78),
                ),
                _FixtureMemoryItem(
                    memory_item_id="mem_travel",
                    source_message_id="msg_3",
                    content="Booked a train to Kazan last week.",
                    embedding=(0.18, 0.82),
                ),
            ),
            expected_hit_ids=(),
            expected_present_snippets=(),
            expected_absent_snippets=(
                "Lives near a train station.",
                "Booked a train to Kazan last week.",
            ),
        ),
        _RetrievalFixture(
            name="stale_memory_excluded",
            query_text="What do you remember about my preferences?",
            query_embedding=(1.0, 0.0),
            memory_items=(
                _FixtureMemoryItem(
                    memory_item_id="mem_stale",
                    source_message_id="msg_old",
                    content="Favorite color is red.",
                    embedding=(0.99, 0.01),
                    status="invalidated",
                ),
                _FixtureMemoryItem(
                    memory_item_id="mem_deleted",
                    source_message_id="msg_deleted",
                    content="Favorite color is yellow.",
                    embedding=(0.97, 0.03),
                    status="deleted",
                ),
                _FixtureMemoryItem(
                    memory_item_id="mem_current",
                    source_message_id="msg_new",
                    content="Favorite color is blue.",
                    embedding=(0.81, 0.19),
                ),
            ),
            expected_hit_ids=("mem_current",),
            expected_present_snippets=("Favorite color is blue.",),
            expected_absent_snippets=(
                "Favorite color is red.",
                "Favorite color is yellow.",
            ),
        ),
    ),
    ids=lambda fixture: fixture.name,
)
def test_memory_retrieval_fixtures_capture_expected_relevance_behavior(
    fixture: _RetrievalFixture,
) -> None:
    service = MemoryService(
        settings=_settings(),
        ollama_client=_FixtureOllamaClient(query_embedding=fixture.query_embedding),
        repository=_FixtureMemoryRepository(memory_items=fixture.memory_items),
        prompt_formatter=ChatPromptFormatter(),
    )
    request = ChatCompletionRequest(
        model="assistant-v1",
        messages=[ChatMessage(role="user", content=fixture.query_text)],
    )

    context = service.prepare_context(request_id=f"req_{fixture.name}", request=request)

    assert context.retrieval is not None
    assert context.retrieval.status == "completed"
    assert tuple(hit.memory_item_id for hit in context.retrieval.hits) == fixture.expected_hit_ids

    if fixture.expected_hit_ids:
        assert context.runtime_messages[0].role == "system"
        for snippet in fixture.expected_present_snippets:
            assert snippet in context.runtime_messages[0].content
    else:
        assert context.runtime_messages == request.messages

    rendered_messages = "\n".join(message.content for message in context.runtime_messages)
    for snippet in fixture.expected_absent_snippets:
        assert snippet not in rendered_messages
