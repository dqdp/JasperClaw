from __future__ import annotations

import logging
import re
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
    MemoryLifecycleTransitionResult,
    MemoryRetrievalRecord,
    PersistedMessage,
)
from app.schemas.chat import ChatCompletionRequest, ChatMessage

_DURABLE_MEMORY_PATTERNS = (
    # Bias toward explicit first-person durable facts and preferences. This slice
    # prefers false negatives over noisy memory writes from generic chatter.
    re.compile(r"\bi prefer\b"),
    re.compile(r"\bmy favorite\b"),
    re.compile(r"\bi live in\b"),
    re.compile(r"\bi am based in\b"),
    re.compile(r"\bi'm based in\b"),
    re.compile(r"\bmy name is\b"),
    re.compile(r"\bcall me\b"),
    re.compile(r"\bi work at\b"),
    re.compile(r"\bi work as\b"),
    re.compile(r"\bi am allergic to\b"),
    re.compile(r"\bi'm allergic to\b"),
)


@dataclass(frozen=True, slots=True)
class MemoryContext:
    runtime_messages: list[ChatMessage]
    retrieval: MemoryRetrievalRecord | None = None


@dataclass(frozen=True, slots=True)
class _MemoryCandidateDecision:
    message: PersistedMessage
    accepted: bool
    reason: str


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
            log_event(
                "chat_memory_materialization_completed",
                request_id=request_id,
                outcome="skipped",
                conversation_id=conversation_id,
                skip_reason="memory_disabled",
            )
            get_agent_metrics().record_memory_materialization(outcome="skipped")
            return

        candidate_decisions = tuple(
            self._evaluate_memory_candidate(message)
            for message in persistence.persisted_messages
        )
        candidate_messages = tuple(
            decision.message
            for decision in candidate_decisions
            if decision.accepted
        )
        self._log_candidate_evaluation(
            request_id=request_id,
            conversation_id=conversation_id,
            candidate_decisions=candidate_decisions,
        )
        if not candidate_messages:
            log_event(
                "chat_memory_materialization_completed",
                request_id=request_id,
                outcome="skipped",
                conversation_id=conversation_id,
                skip_reason="no_candidates",
            )
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
            retrieval_hit_ids=[hit.memory_item_id for hit in retrieval.hits],
            retrieval_hit_scores=[round(hit.score, 4) for hit in retrieval.hits],
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

    def _evaluate_memory_candidate(
        self,
        message: PersistedMessage,
    ) -> _MemoryCandidateDecision:
        content = " ".join(message.content.strip().split())
        if message.role != "user" or message.source != "request_transcript":
            reason = (
                "non_user_role"
                if message.role != "user"
                else "non_request_transcript_source"
            )
            return _MemoryCandidateDecision(
                message=message,
                accepted=False,
                reason=reason,
            )
        if not content or content.endswith("?"):
            reason = "question" if content.endswith("?") else "empty_content"
            return _MemoryCandidateDecision(
                message=message,
                accepted=False,
                reason=reason,
            )
        normalized = content.lower()
        accepted = any(pattern.search(normalized) for pattern in _DURABLE_MEMORY_PATTERNS)
        return _MemoryCandidateDecision(
            message=message,
            accepted=accepted,
            reason="durable_signal" if accepted else "no_durable_signal",
        )

    def _log_candidate_evaluation(
        self,
        *,
        request_id: str,
        conversation_id: str,
        candidate_decisions: tuple[_MemoryCandidateDecision, ...],
    ) -> None:
        skip_reason_counts: dict[str, int] = {}
        accepted_message_ids: list[str] = []
        for decision in candidate_decisions:
            metric_decision = "accepted" if decision.accepted else "skipped"
            get_agent_metrics().record_memory_candidate(
                decision=metric_decision,
                reason=decision.reason,
            )
            if decision.accepted:
                accepted_message_ids.append(decision.message.message_id)
                continue
            skip_reason_counts[decision.reason] = skip_reason_counts.get(decision.reason, 0) + 1

        log_event(
            "chat_memory_candidate_evaluation_completed",
            request_id=request_id,
            conversation_id=conversation_id,
            accepted_message_ids=accepted_message_ids,
            accepted_count=len(accepted_message_ids),
            evaluated_count=len(candidate_decisions),
            skip_reason_counts=skip_reason_counts,
        )

    def _latest_user_message(self, messages: list[ChatMessage]) -> str | None:
        for message in reversed(messages):
            content = message.content.strip()
            if message.role == "user" and content:
                return content
        return None


class MemoryLifecycleService:
    """Owns explicit, deterministic memory lifecycle transitions."""

    def __init__(self, *, repository: ChatRepository) -> None:
        self._repository = repository

    def invalidate_item(
        self,
        *,
        request_id: str,
        memory_item_id: str,
        updated_at: datetime,
        reason: str | None = None,
    ) -> MemoryLifecycleTransitionResult:
        return self._transition_item(
            request_id=request_id,
            memory_item_id=memory_item_id,
            target_status="invalidated",
            updated_at=updated_at,
            reason=reason,
        )

    def delete_item(
        self,
        *,
        request_id: str,
        memory_item_id: str,
        updated_at: datetime,
        reason: str | None = None,
    ) -> MemoryLifecycleTransitionResult:
        return self._transition_item(
            request_id=request_id,
            memory_item_id=memory_item_id,
            target_status="deleted",
            updated_at=updated_at,
            reason=reason,
        )

    def _transition_item(
        self,
        *,
        request_id: str,
        memory_item_id: str,
        target_status: str,
        updated_at: datetime,
        reason: str | None,
    ) -> MemoryLifecycleTransitionResult:
        transition_started = perf_counter()
        try:
            result = self._repository.transition_memory_item_status(
                memory_item_id=memory_item_id,
                target_status=target_status,
                updated_at=updated_at,
            )
            outcome = "success" if result.changed else "noop"
            log_event(
                "chat_memory_lifecycle_completed",
                request_id=request_id,
                outcome=outcome,
                duration_ms=round((perf_counter() - transition_started) * 1000, 2),
                memory_item_id=memory_item_id,
                previous_status=result.previous_status,
                current_status=result.current_status,
                target_status=target_status,
                changed=result.changed,
                reason=reason,
            )
            get_agent_metrics().record_memory_lifecycle(
                outcome=outcome,
                target_status=target_status,
            )
            return result
        except APIError as exc:
            log_event(
                "chat_memory_lifecycle_completed",
                level=logging.WARNING,
                request_id=request_id,
                outcome="error",
                duration_ms=round((perf_counter() - transition_started) * 1000, 2),
                memory_item_id=memory_item_id,
                target_status=target_status,
                reason=reason,
                error_type=exc.error_type,
                error_code=exc.code,
            )
            get_agent_metrics().record_memory_lifecycle(
                outcome="error",
                target_status=target_status,
            )
            raise
