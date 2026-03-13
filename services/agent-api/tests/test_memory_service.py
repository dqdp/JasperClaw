from datetime import datetime, timezone

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings
from app.core.errors import APIError
from app.modules.chat.formatters import ChatPromptFormatter
from app.modules.chat.memory import MemoryContext, MemoryService
from app.repositories import ChatPersistenceResult, MemorySearchHit, PersistedMessage
from app.schemas.chat import ChatCompletionRequest, ChatMessage


class _FakeOllamaClient(OllamaChatClient):
    def __init__(
        self,
        *,
        embeddings: list[list[float]] | None = None,
        error: APIError | None = None,
    ) -> None:
        self.embeddings = embeddings or [[1.0, 0.0]]
        self.error = error
        self.calls: list[dict[str, object]] = []

    def embed(self, model: str, input_text: str | list[str]) -> list[list[float]]:
        self.calls.append({"model": model, "input_text": input_text})
        if self.error is not None:
            raise self.error
        return self.embeddings


class _FakeRepository:
    def __init__(
        self,
        *,
        hits: list[MemorySearchHit] | None = None,
        retrieval_error: APIError | None = None,
    ) -> None:
        self.hits = hits or []
        self.retrieval_error = retrieval_error
        self.retrieve_calls: list[dict[str, object]] = []
        self.record_retrieval_calls: list[dict[str, object]] = []
        self.store_memory_calls: list[dict[str, object]] = []

    def retrieve_memory(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        if self.retrieval_error is not None:
            raise self.retrieval_error
        return list(self.hits)

    def record_retrieval(self, **kwargs):
        self.record_retrieval_calls.append(kwargs)

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


def test_memory_service_augments_prompt_with_retrieved_memory() -> None:
    repository = _FakeRepository(
        hits=[
            MemorySearchHit(
                memory_item_id="mem_1",
                source_message_id="msg_1",
                content="Favorite color is blue.",
                score=0.92,
            )
        ]
    )
    service = MemoryService(
        settings=_settings(),
        ollama_client=_FakeOllamaClient(),
        repository=repository,
        prompt_formatter=ChatPromptFormatter(),
    )
    request = ChatCompletionRequest(
        model="assistant-v1",
        messages=[ChatMessage(role="user", content="Tell me about my preferences")],
    )

    context = service.prepare_context(request_id="req_1", request=request)

    assert isinstance(context, MemoryContext)
    assert context.retrieval is not None
    assert context.retrieval.status == "completed"
    assert "Relevant memory from prior conversations" in context.runtime_messages[0].content
    assert repository.retrieve_calls[0]["limit"] == 3


def test_memory_service_degrades_on_embedding_error() -> None:
    service = MemoryService(
        settings=_settings(),
        ollama_client=_FakeOllamaClient(
            error=APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_unavailable",
                message="embed failed",
            )
        ),
        repository=_FakeRepository(),
        prompt_formatter=ChatPromptFormatter(),
    )
    request = ChatCompletionRequest(
        model="assistant-v1",
        messages=[ChatMessage(role="user", content="Tell me about my preferences")],
    )

    context = service.prepare_context(request_id="req_2", request=request)

    assert context.retrieval is not None
    assert context.retrieval.status == "error"
    assert context.runtime_messages == request.messages


def test_memory_service_stores_only_candidate_messages() -> None:
    repository = _FakeRepository()
    service = MemoryService(
        settings=_settings(),
        ollama_client=_FakeOllamaClient(embeddings=[[1.0, 0.0]]),
        repository=repository,
        prompt_formatter=ChatPromptFormatter(),
    )
    persistence = ChatPersistenceResult(
        conversation_id="conv_1",
        assistant_message_id="msg_a",
        model_run_id="run_1",
        persisted_messages=(
            PersistedMessage(
                message_id="msg_short",
                message_index=0,
                role="user",
                content="short",
                source="request_transcript",
            ),
            PersistedMessage(
                message_id="msg_long",
                message_index=1,
                role="user",
                content="I prefer concise answers and live in Berlin.",
                source="request_transcript",
            ),
            PersistedMessage(
                message_id="msg_question",
                message_index=2,
                role="user",
                content="Do I like music?",
                source="request_transcript",
            ),
        ),
    )

    service.store_items(
        request_id="req_3",
        conversation_id="conv_1",
        persistence=persistence,
        created_at=datetime.now(timezone.utc),
    )

    assert len(repository.store_memory_calls) == 1
    stored_messages = repository.store_memory_calls[0]["messages"]
    assert tuple(message.message_id for message in stored_messages) == ("msg_long",)


def test_memory_service_records_retrieval_when_conversation_is_present() -> None:
    repository = _FakeRepository()
    service = MemoryService(
        settings=_settings(),
        ollama_client=_FakeOllamaClient(),
        repository=repository,
        prompt_formatter=ChatPromptFormatter(),
    )
    context = MemoryContext(
        runtime_messages=[ChatMessage(role="user", content="hello")],
        retrieval=service.prepare_context(
            request_id="req_4",
            request=ChatCompletionRequest(
                model="assistant-v1",
                messages=[ChatMessage(role="user", content="Tell me about preferences")],
            ),
        ).retrieval,
    )

    service.record_retrieval(
        request_id="req_4",
        public_model="assistant-v1",
        conversation_id="conv_1",
        memory_context=context,
        created_at=datetime.now(timezone.utc),
    )

    assert len(repository.record_retrieval_calls) == 1
    assert repository.record_retrieval_calls[0]["public_model"] == "assistant-v1"
