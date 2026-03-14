import json
import logging
from datetime import datetime, timezone

import pytest

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings
from app.core.errors import APIError
from app.core.metrics import get_agent_metrics
from app.modules.chat.formatters import ChatPromptFormatter
from app.modules.chat.memory import MemoryContext, MemoryLifecycleService, MemoryService
from app.repositories import (
    ChatPersistenceResult,
    MemoryLifecycleTransitionResult,
    MemorySearchHit,
    PersistedMessage,
)
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
        transition_result: MemoryLifecycleTransitionResult | None = None,
        transition_error: APIError | None = None,
    ) -> None:
        self.hits = hits or []
        self.retrieval_error = retrieval_error
        self.transition_result = transition_result
        self.transition_error = transition_error
        self.retrieve_calls: list[dict[str, object]] = []
        self.record_retrieval_calls: list[dict[str, object]] = []
        self.store_memory_calls: list[dict[str, object]] = []
        self.transition_calls: list[dict[str, object]] = []

    def retrieve_memory(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        if self.retrieval_error is not None:
            raise self.retrieval_error
        return list(self.hits)

    def record_retrieval(self, **kwargs):
        self.record_retrieval_calls.append(kwargs)

    def store_memory_items(self, **kwargs):
        self.store_memory_calls.append(kwargs)

    def transition_memory_item_status(self, **kwargs):
        self.transition_calls.append(kwargs)
        if self.transition_error is not None:
            raise self.transition_error
        if self.transition_result is not None:
            return self.transition_result
        return MemoryLifecycleTransitionResult(
            memory_item_id=kwargs["memory_item_id"],
            previous_status="active",
            current_status=kwargs["target_status"],
            changed=True,
        )


def _events(caplog) -> list[dict]:
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "agent_api"
    ]


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


def test_memory_service_augments_prompt_with_retrieved_memory(caplog) -> None:
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

    with caplog.at_level(logging.INFO, logger="agent_api"):
        context = service.prepare_context(request_id="req_1", request=request)

    assert isinstance(context, MemoryContext)
    assert context.retrieval is not None
    assert context.retrieval.status == "completed"
    assert "Relevant memory from prior conversations" in context.runtime_messages[0].content
    assert repository.retrieve_calls[0]["limit"] == 3
    event = next(
        event for event in _events(caplog) if event["event"] == "chat_memory_retrieval_completed"
    )
    assert event["retrieval_hit_ids"] == ["mem_1"]
    assert event["retrieval_hit_scores"] == [0.92]
    exported = get_agent_metrics().render_prometheus()
    assert 'agent_api_memory_retrieval_total{outcome="success"} 1' in exported
    assert "agent_api_memory_retrieval_hits_total 1" in exported
    assert (
        'agent_api_memory_embedding_total{outcome="success",phase="retrieve"} 1'
        in exported
    )


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
    exported = get_agent_metrics().render_prometheus()
    assert 'agent_api_memory_retrieval_total{outcome="error"} 1' in exported
    assert (
        'agent_api_memory_embedding_total{outcome="error",phase="retrieve"} 1'
        in exported
    )


def test_memory_service_marks_retrieval_as_skipped_when_memory_is_disabled() -> None:
    service = MemoryService(
        settings=_settings(memory_enabled=False, ollama_embed_model=""),
        ollama_client=_FakeOllamaClient(),
        repository=_FakeRepository(),
        prompt_formatter=ChatPromptFormatter(),
    )
    request = ChatCompletionRequest(
        model="assistant-v1",
        messages=[ChatMessage(role="user", content="Tell me about my preferences")],
    )

    context = service.prepare_context(request_id="req_skip", request=request)

    assert context.retrieval is None
    exported = get_agent_metrics().render_prometheus()
    assert 'agent_api_memory_retrieval_total{outcome="skipped"} 1' in exported


def test_memory_service_stores_only_candidate_messages(caplog) -> None:
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

    with caplog.at_level(logging.INFO, logger="agent_api"):
        service.store_items(
            request_id="req_3",
            conversation_id="conv_1",
            persistence=persistence,
            created_at=datetime.now(timezone.utc),
        )

    assert len(repository.store_memory_calls) == 1
    stored_messages = repository.store_memory_calls[0]["messages"]
    assert tuple(message.message_id for message in stored_messages) == ("msg_long",)
    candidate_event = next(
        event
        for event in _events(caplog)
        if event["event"] == "chat_memory_candidate_evaluation_completed"
    )
    assert candidate_event["accepted_message_ids"] == ["msg_long"]
    assert candidate_event["skip_reason_counts"] == {
        "no_durable_signal": 1,
        "question": 1,
    }
    exported = get_agent_metrics().render_prometheus()
    assert (
        'agent_api_memory_candidate_total{decision="accepted",reason="durable_signal"} 1'
        in exported
    )
    assert (
        'agent_api_memory_candidate_total{decision="skipped",reason="no_durable_signal"} 1'
        in exported
    )
    assert (
        'agent_api_memory_candidate_total{decision="skipped",reason="question"} 1'
        in exported
    )
    assert 'agent_api_memory_materialization_total{outcome="success"} 1' in exported
    assert (
        'agent_api_memory_embedding_total{outcome="success",phase="store"} 1'
        in exported
    )


def test_memory_service_materializes_audio_transcription_messages(caplog) -> None:
    repository = _FakeRepository()
    service = MemoryService(
        settings=_settings(),
        ollama_client=_FakeOllamaClient(embeddings=[[1.0, 0.0]]),
        repository=repository,
        prompt_formatter=ChatPromptFormatter(),
    )
    persisted_message = PersistedMessage(
        message_id="msg_audio",
        message_index=0,
        role="user",
        content="I live in Berlin and prefer concise answers.",
        source="audio_transcription",
    )

    with caplog.at_level(logging.INFO, logger="agent_api"):
        service.store_persisted_messages(
            request_id="req_audio_memory",
            conversation_id="conv_audio",
            persisted_messages=(persisted_message,),
            created_at=datetime.now(timezone.utc),
        )

    assert len(repository.store_memory_calls) == 1
    stored_messages = repository.store_memory_calls[0]["messages"]
    assert tuple(message.message_id for message in stored_messages) == ("msg_audio",)
    candidate_event = next(
        event
        for event in _events(caplog)
        if event["event"] == "chat_memory_candidate_evaluation_completed"
    )
    assert candidate_event["accepted_message_ids"] == ["msg_audio"]
    exported = get_agent_metrics().render_prometheus()
    assert (
        'agent_api_memory_candidate_total{decision="accepted",reason="durable_signal"} 1'
        in exported
    )
    assert 'agent_api_memory_materialization_total{outcome="success"} 1' in exported

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
    exported = get_agent_metrics().render_prometheus()
    assert 'agent_api_memory_audit_total{outcome="success"} 1' in exported


def test_memory_service_skips_materialization_without_candidates(caplog) -> None:
    repository = _FakeRepository()
    service = MemoryService(
        settings=_settings(),
        ollama_client=_FakeOllamaClient(),
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
                message_id="msg_question",
                message_index=1,
                role="user",
                content="Do I like music?",
                source="request_transcript",
            ),
        ),
    )

    with caplog.at_level(logging.INFO, logger="agent_api"):
        service.store_items(
            request_id="req_skip_store",
            conversation_id="conv_1",
            persistence=persistence,
            created_at=datetime.now(timezone.utc),
        )

    assert repository.store_memory_calls == []
    events = _events(caplog)
    candidate_event = next(
        event
        for event in events
        if event["event"] == "chat_memory_candidate_evaluation_completed"
    )
    assert candidate_event["accepted_message_ids"] == []
    assert candidate_event["skip_reason_counts"] == {
        "no_durable_signal": 1,
        "question": 1,
    }
    materialization_event = next(
        event
        for event in events
        if event["event"] == "chat_memory_materialization_completed"
    )
    assert materialization_event["outcome"] == "skipped"
    assert materialization_event["skip_reason"] == "no_candidates"
    exported = get_agent_metrics().render_prometheus()
    assert (
        'agent_api_memory_candidate_total{decision="skipped",reason="no_durable_signal"} 1'
        in exported
    )
    assert (
        'agent_api_memory_candidate_total{decision="skipped",reason="question"} 1'
        in exported
    )
    assert 'agent_api_memory_materialization_total{outcome="skipped"} 1' in exported


def test_memory_lifecycle_service_records_successful_invalidation(
    caplog,
) -> None:
    repository = _FakeRepository(
        transition_result=MemoryLifecycleTransitionResult(
            memory_item_id="mem_1",
            previous_status="active",
            current_status="invalidated",
            changed=True,
        )
    )
    service = MemoryLifecycleService(repository=repository)

    with caplog.at_level(logging.INFO, logger="agent_api"):
        result = service.invalidate_item(
            request_id="req_memory_invalidate",
            memory_item_id="mem_1",
            updated_at=datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc),
            reason="user_forget",
        )

    assert result.changed is True
    assert repository.transition_calls == [
        {
            "memory_item_id": "mem_1",
            "target_status": "invalidated",
            "updated_at": datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc),
        }
    ]
    event = next(
        event for event in _events(caplog) if event["event"] == "chat_memory_lifecycle_completed"
    )
    assert event["request_id"] == "req_memory_invalidate"
    assert event["outcome"] == "success"
    assert event["memory_item_id"] == "mem_1"
    assert event["target_status"] == "invalidated"
    assert event["reason"] == "user_forget"
    exported = get_agent_metrics().render_prometheus()
    assert (
        'agent_api_memory_lifecycle_total{outcome="success",target_status="invalidated"} 1'
        in exported
    )


def test_memory_lifecycle_service_records_noop_transition(caplog) -> None:
    repository = _FakeRepository(
        transition_result=MemoryLifecycleTransitionResult(
            memory_item_id="mem_1",
            previous_status="invalidated",
            current_status="invalidated",
            changed=False,
        )
    )
    service = MemoryLifecycleService(repository=repository)

    with caplog.at_level(logging.INFO, logger="agent_api"):
        result = service.invalidate_item(
            request_id="req_memory_noop",
            memory_item_id="mem_1",
            updated_at=datetime(2026, 3, 14, 12, 5, tzinfo=timezone.utc),
        )

    assert result.changed is False
    event = next(
        event for event in _events(caplog) if event["event"] == "chat_memory_lifecycle_completed"
    )
    assert event["outcome"] == "noop"
    exported = get_agent_metrics().render_prometheus()
    assert (
        'agent_api_memory_lifecycle_total{outcome="noop",target_status="invalidated"} 1'
        in exported
    )


def test_memory_lifecycle_service_records_errors_and_reraises(caplog) -> None:
    repository = _FakeRepository(
        transition_error=APIError(
            status_code=404,
            error_type="not_found",
            code="memory_item_not_found",
            message="Memory item not found",
        )
    )
    service = MemoryLifecycleService(repository=repository)

    with caplog.at_level(logging.INFO, logger="agent_api"), pytest.raises(APIError) as exc_info:
        service.delete_item(
            request_id="req_memory_delete",
            memory_item_id="mem_missing",
            updated_at=datetime(2026, 3, 14, 12, 10, tzinfo=timezone.utc),
        )

    assert exc_info.value.code == "memory_item_not_found"
    event = next(
        event for event in _events(caplog) if event["event"] == "chat_memory_lifecycle_completed"
    )
    assert event["outcome"] == "error"
    assert event["target_status"] == "deleted"
    assert event["error_code"] == "memory_item_not_found"
    exported = get_agent_metrics().render_prometheus()
    assert (
        'agent_api_memory_lifecycle_total{outcome="error",target_status="deleted"} 1'
        in exported
    )
