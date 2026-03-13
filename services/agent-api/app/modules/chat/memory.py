from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings
from app.core.errors import APIError
from app.core.logging import log_event
from app.core.metrics import get_agent_metrics
from app.modules.chat.formatters import ChatPromptFormatter
from app.repositories import (
    ChatPersistenceResult,
    ChatRepository,
    MemoryRetrievalRecord,
    PersistedMessage,
)
from app.schemas.chat import ChatCompletionRequest, ChatMessage


@dataclass(frozen=True, slots=True)
class MemoryContext:
    runtime_messages: list[ChatMessage]
    retrieval: MemoryRetrievalRecord | None = None


class MemoryService:
    """Owns memory retrieval, audit recording, and materialization."""

    def __init__(
        self,
        *,
        settings: Settings,
        ollama_client: OllamaChatClient,
        repository: ChatRepository,
        prompt_formatter: ChatPromptFormatter,
    ) -> None:
        self._settings = settings
        self._ollama_client = ollama_client
        self._repository = repository
        self._prompt_formatter = prompt_formatter

    def prepare_context(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
    ) -> MemoryContext:
        if not self._settings.memory_enabled or not self._settings.ollama_embed_model:
            get_agent_metrics().record_memory_retrieval(
                outcome="skipped",
                duration_seconds=0.0,
            )
            return MemoryContext(runtime_messages=list(request.messages))

        query_text = self._latest_user_message(request.messages)
        if not query_text:
            get_agent_metrics().record_memory_retrieval(
                outcome="skipped",
                duration_seconds=0.0,
            )
            return MemoryContext(runtime_messages=list(request.messages))

        retrieval_started = perf_counter()
        try:
            embeddings = self._ollama_client.embed(
                model=self._settings.ollama_embed_model,
                input_text=query_text,
            )
            query_embedding = self._require_single_embedding(embeddings)
            get_agent_metrics().record_memory_embedding(
                phase="retrieve",
                outcome="success",
            )
            hits = tuple(
                self._repository.retrieve_memory(
                    query_embedding=query_embedding,
                    limit=self._settings.memory_top_k,
                    min_score=self._settings.memory_min_score,
                )
            )
            retrieval = MemoryRetrievalRecord(
                query_text=query_text,
                status="completed",
                top_k=self._settings.memory_top_k,
                latency_ms=round((perf_counter() - retrieval_started) * 1000, 2),
                hits=hits,
            )
            self._log_memory_retrieval(
                request_id=request_id,
                outcome="success",
                retrieval=retrieval,
            )
            retrieval_outcome = "success" if hits else "empty"
            get_agent_metrics().record_memory_retrieval(
                outcome=retrieval_outcome,
                duration_seconds=retrieval.latency_ms / 1000,
                hit_count=len(hits),
            )
            if not hits:
                return MemoryContext(
                    runtime_messages=list(request.messages),
                    retrieval=retrieval,
                )
            return MemoryContext(
                runtime_messages=self._prompt_formatter.augment_with_memory(
                    request.messages,
                    tuple(hit.content for hit in hits),
                ),
                retrieval=retrieval,
            )
        except APIError as exc:
            retrieval = MemoryRetrievalRecord(
                query_text=query_text,
                status="error",
                top_k=self._settings.memory_top_k,
                latency_ms=round((perf_counter() - retrieval_started) * 1000, 2),
                error_type=exc.error_type,
                error_code=exc.code,
            )
            get_agent_metrics().record_memory_embedding(
                phase="retrieve",
                outcome="error",
            )
            self._log_memory_retrieval(
                request_id=request_id,
                outcome="error",
                retrieval=retrieval,
            )
            get_agent_metrics().record_memory_retrieval(
                outcome="error",
                duration_seconds=retrieval.latency_ms / 1000,
            )
            return MemoryContext(
                runtime_messages=list(request.messages),
                retrieval=retrieval,
            )

    def record_retrieval(
        self,
        *,
        request_id: str,
        public_model: str,
        conversation_id: str | None,
        memory_context: MemoryContext,
        created_at: datetime,
    ) -> None:
        if memory_context.retrieval is None or conversation_id is None:
            return

        storage_started = perf_counter()
        try:
            self._repository.record_retrieval(
                conversation_id=conversation_id,
                request_id=request_id,
                public_model=public_model,
                retrieval=memory_context.retrieval,
                created_at=created_at,
            )
            log_event(
                "chat_memory_audit_completed",
                request_id=request_id,
                outcome="success",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=conversation_id,
                retrieval_status=memory_context.retrieval.status,
                retrieval_hit_count=len(memory_context.retrieval.hits),
            )
            get_agent_metrics().record_memory_audit(outcome="success")
        except APIError as exc:
            log_event(
                "chat_memory_audit_completed",
                level=logging.WARNING,
                request_id=request_id,
                outcome="error",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=conversation_id,
                error_type=exc.error_type,
                error_code=exc.code,
            )
            get_agent_metrics().record_memory_audit(outcome="error")

    def store_items(
        self,
        *,
        request_id: str,
        conversation_id: str,
        persistence: ChatPersistenceResult,
        created_at: datetime,
    ) -> None:
        if not self._settings.memory_enabled or not self._settings.ollama_embed_model:
            get_agent_metrics().record_memory_materialization(outcome="skipped")
            return

        candidate_messages = tuple(
            message
            for message in persistence.persisted_messages
            if self._is_memory_candidate(message)
        )
        if not candidate_messages:
            get_agent_metrics().record_memory_materialization(outcome="skipped")
            return

        try:
            embeddings = self._ollama_client.embed(
                model=self._settings.ollama_embed_model,
                input_text=[message.content for message in candidate_messages],
            )
            if len(embeddings) != len(candidate_messages) or any(
                not embedding for embedding in embeddings
            ):
                raise APIError(
                    status_code=502,
                    error_type="upstream_error",
                    code="dependency_bad_response",
                    message="Model runtime returned an unexpected embedding payload",
                )
            get_agent_metrics().record_memory_embedding(
                phase="store",
                outcome="success",
            )
        except APIError as exc:
            log_event(
                "chat_memory_materialization_completed",
                level=logging.WARNING,
                request_id=request_id,
                outcome="error",
                conversation_id=conversation_id,
                error_type=exc.error_type,
                error_code=exc.code,
            )
            get_agent_metrics().record_memory_embedding(
                phase="store",
                outcome="error",
            )
            get_agent_metrics().record_memory_materialization(outcome="error")
            return

        storage_started = perf_counter()
        try:
            self._repository.store_memory_items(
                conversation_id=conversation_id,
                messages=candidate_messages,
                embeddings=embeddings,
                embedding_model=self._settings.ollama_embed_model,
                created_at=created_at,
            )
            log_event(
                "chat_memory_materialization_completed",
                request_id=request_id,
                outcome="success",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=conversation_id,
                memory_item_count=len(candidate_messages),
            )
            get_agent_metrics().record_memory_materialization(
                outcome="success",
                duration_seconds=round((perf_counter() - storage_started) * 1000, 2)
                / 1000,
            )
        except APIError as exc:
            log_event(
                "chat_memory_materialization_completed",
                level=logging.WARNING,
                request_id=request_id,
                outcome="error",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=conversation_id,
                error_type=exc.error_type,
                error_code=exc.code,
            )
            get_agent_metrics().record_memory_materialization(
                outcome="error",
                duration_seconds=round((perf_counter() - storage_started) * 1000, 2)
                / 1000,
            )

    def _log_memory_retrieval(
        self,
        *,
        request_id: str,
        outcome: str,
        retrieval: MemoryRetrievalRecord,
    ) -> None:
        level = logging.INFO if outcome == "success" else logging.WARNING
        log_event(
            "chat_memory_retrieval_completed",
            level=level,
            request_id=request_id,
            outcome=outcome,
            retrieval_status=retrieval.status,
            duration_ms=retrieval.latency_ms,
            retrieval_hit_count=len(retrieval.hits),
            error_type=retrieval.error_type,
            error_code=retrieval.error_code,
        )

    def _require_single_embedding(
        self,
        embeddings: list[list[float]],
    ) -> list[float]:
        if len(embeddings) != 1 or not embeddings[0]:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned an unexpected embedding payload",
            )
        return embeddings[0]

    def _is_memory_candidate(self, message: PersistedMessage) -> bool:
        content = message.content.strip()
        if message.role != "user" or message.source != "request_transcript":
            return False
        if len(content) < 15:
            return False
        if content.endswith("?"):
            return False
        return True

    def _latest_user_message(self, messages: list[ChatMessage]) -> str | None:
        for message in reversed(messages):
            content = message.content.strip()
            if message.role == "user" and content:
                return content
        return None
