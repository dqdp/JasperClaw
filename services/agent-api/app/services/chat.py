from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from time import perf_counter, time
from uuid import uuid4

from app.clients.ollama import (
    OllamaChatClient,
    OllamaChatResult,
    OllamaChatStreamChunk,
)
from app.core.config import Settings
from app.core.errors import APIError
from app.core.logging import log_event
from app.repositories import (
    ChatPersistenceResult,
    ChatRepository,
    ConversationContext,
    MemoryRetrievalRecord,
    MemorySearchHit,
    PersistedMessage,
)
from app.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionUsage,
    ChatMessage,
)


@dataclass(slots=True)
class RuntimeProfile:
    public_id: str
    runtime_model: str


@dataclass(slots=True)
class ChatResult:
    response_id: str
    created: int
    public_model: str
    conversation_id: str
    content: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage | None


@dataclass(slots=True)
class ChatStreamEvent:
    content: str | None
    role: str | None
    finish_reason: str | None


@dataclass(slots=True)
class ChatStreamSession:
    response_id: str
    created: int
    public_model: str
    conversation_id: str
    events: Iterator[ChatStreamEvent]


@dataclass(frozen=True, slots=True)
class MemoryContext:
    runtime_messages: list[ChatMessage]
    retrieval: MemoryRetrievalRecord | None = None


class ChatService:
    def __init__(
        self,
        settings: Settings,
        ollama_client: OllamaChatClient,
        repository: ChatRepository,
    ) -> None:
        self._settings = settings
        self._ollama_client = ollama_client
        self._repository = repository

    def create_chat_completion(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None = None,
    ) -> ChatResult:
        profile = self._resolve_profile(request.model)
        resolved_conversation_hint = (
            conversation_id_hint or self._extract_conversation_hint(request)
        )
        memory_context = self._prepare_memory_context(
            request_id=request_id,
            request=request,
        )
        started_at = datetime.now(timezone.utc)
        runtime_started = perf_counter()

        try:
            runtime_result = self._ollama_client.chat(
                model=profile.runtime_model,
                messages=memory_context.runtime_messages,
            )
        except APIError as exc:
            completed_at = datetime.now(timezone.utc)
            self._log_runtime_error(
                request_id=request_id,
                profile=profile,
                runtime_started=runtime_started,
                error=exc,
            )
            persistence = self._persist_failed_completion(
                request_id=request_id,
                profile=profile,
                request=request,
                conversation_id_hint=resolved_conversation_hint,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            self._record_memory_retrieval(
                request_id=request_id,
                profile=profile,
                conversation_id=(
                    persistence.conversation_id if persistence is not None else None
                ),
                memory_context=memory_context,
                created_at=completed_at,
            )
            raise

        completed_at = datetime.now(timezone.utc)
        return self._build_success_result(
            request_id=request_id,
            request=request,
            profile=profile,
            conversation_id_hint=resolved_conversation_hint,
            memory_context=memory_context,
            runtime_result=runtime_result,
            started_at=started_at,
            completed_at=completed_at,
            runtime_started=runtime_started,
        )

    def create_streaming_chat_completion(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None = None,
    ) -> ChatStreamSession:
        profile = self._resolve_profile(request.model)
        resolved_conversation_hint = (
            conversation_id_hint or self._extract_conversation_hint(request)
        )
        started_at = datetime.now(timezone.utc)
        context = self._repository.prepare_conversation(
            public_model=profile.public_id,
            request_messages=request.messages,
            conversation_id_hint=resolved_conversation_hint,
            created_at=started_at,
        )
        memory_context = self._prepare_memory_context(
            request_id=request_id,
            request=request,
        )
        runtime_started = perf_counter()
        stream = self._ollama_client.stream_chat(
            model=profile.runtime_model,
            messages=memory_context.runtime_messages,
        )

        try:
            first_chunk = next(stream)
        except StopIteration as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned an unexpected empty stream",
            ) from exc
        except APIError as exc:
            completed_at = datetime.now(timezone.utc)
            self._log_runtime_error(
                request_id=request_id,
                profile=profile,
                runtime_started=runtime_started,
                error=exc,
            )
            persistence = self._persist_failed_completion(
                request_id=request_id,
                profile=profile,
                request=request,
                conversation_id_hint=context.conversation_id,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            self._record_memory_retrieval(
                request_id=request_id,
                profile=profile,
                conversation_id=(
                    persistence.conversation_id if persistence is not None else None
                ),
                memory_context=memory_context,
                created_at=completed_at,
            )
            raise

        response_id = f"chatcmpl_{uuid4().hex[:12]}"
        created = int(time())
        events = self._stream_events(
            request_id=request_id,
            request=request,
            profile=profile,
            context=context,
            memory_context=memory_context,
            started_at=started_at,
            runtime_started=runtime_started,
            first_chunk=first_chunk,
            remaining_chunks=stream,
        )
        return ChatStreamSession(
            response_id=response_id,
            created=created,
            public_model=profile.public_id,
            conversation_id=context.conversation_id,
            events=events,
        )

    def _stream_events(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        profile: RuntimeProfile,
        context: ConversationContext,
        memory_context: MemoryContext,
        started_at: datetime,
        runtime_started: float,
        first_chunk: OllamaChatStreamChunk,
        remaining_chunks: Iterator[OllamaChatStreamChunk],
    ) -> Iterator[ChatStreamEvent]:
        chunks = self._iter_stream_chunks(first_chunk, remaining_chunks)
        content_parts: list[str] = []
        sent_any_content = False

        try:
            for chunk in chunks:
                if chunk.content:
                    content_parts.append(chunk.content)
                    yield ChatStreamEvent(
                        content=chunk.content,
                        role="assistant" if not sent_any_content else None,
                        finish_reason=None,
                    )
                    sent_any_content = True

                if not chunk.done:
                    continue

                completed_at = datetime.now(timezone.utc)
                usage = self._build_usage(
                    prompt_tokens=chunk.prompt_tokens,
                    completion_tokens=chunk.completion_tokens,
                    total_tokens=chunk.total_tokens,
                )
                self._log_runtime_success(
                    request_id=request_id,
                    profile=profile,
                    runtime_started=runtime_started,
                    usage=usage,
                )
                persistence = self._persist_successful_completion(
                    request_id=request_id,
                    profile=profile,
                    request=request,
                    conversation_id_hint=context.conversation_id,
                    response_content="".join(content_parts),
                    usage=usage,
                    started_at=started_at,
                    completed_at=completed_at,
                )
                self._record_memory_retrieval(
                    request_id=request_id,
                    profile=profile,
                    conversation_id=persistence.conversation_id,
                    memory_context=memory_context,
                    created_at=completed_at,
                )
                self._store_memory_items(
                    request_id=request_id,
                    conversation_id=persistence.conversation_id,
                    persistence=persistence,
                    created_at=completed_at,
                )
                yield ChatStreamEvent(
                    content=None,
                    role=None,
                    finish_reason="stop",
                )
                return

            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned an incomplete stream",
            )
        except APIError as exc:
            completed_at = datetime.now(timezone.utc)
            self._log_runtime_error(
                request_id=request_id,
                profile=profile,
                runtime_started=runtime_started,
                error=exc,
            )
            persistence = self._persist_failed_completion(
                request_id=request_id,
                profile=profile,
                request=request,
                conversation_id_hint=context.conversation_id,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            self._record_memory_retrieval(
                request_id=request_id,
                profile=profile,
                conversation_id=(
                    persistence.conversation_id if persistence is not None else None
                ),
                memory_context=memory_context,
                created_at=completed_at,
            )
            raise

    def _iter_stream_chunks(
        self,
        first_chunk: OllamaChatStreamChunk,
        remaining_chunks: Iterator[OllamaChatStreamChunk],
    ) -> Iterator[OllamaChatStreamChunk]:
        yield first_chunk
        yield from remaining_chunks

    def _build_success_result(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        profile: RuntimeProfile,
        conversation_id_hint: str | None,
        memory_context: MemoryContext,
        runtime_result: OllamaChatResult,
        started_at: datetime,
        completed_at: datetime,
        runtime_started: float,
    ) -> ChatResult:
        response_id = f"chatcmpl_{uuid4().hex[:12]}"
        created = int(time())
        usage = self._build_usage(
            prompt_tokens=runtime_result.prompt_tokens,
            completion_tokens=runtime_result.completion_tokens,
            total_tokens=runtime_result.total_tokens,
        )

        self._log_runtime_success(
            request_id=request_id,
            profile=profile,
            runtime_started=runtime_started,
            usage=usage,
        )
        persistence = self._persist_successful_completion(
            request_id=request_id,
            profile=profile,
            request=request,
            conversation_id_hint=conversation_id_hint,
            response_content=runtime_result.content,
            usage=usage,
            started_at=started_at,
            completed_at=completed_at,
        )
        self._record_memory_retrieval(
            request_id=request_id,
            profile=profile,
            conversation_id=persistence.conversation_id,
            memory_context=memory_context,
            created_at=completed_at,
        )
        self._store_memory_items(
            request_id=request_id,
            conversation_id=persistence.conversation_id,
            persistence=persistence,
            created_at=completed_at,
        )

        return ChatResult(
            response_id=response_id,
            created=created,
            public_model=profile.public_id,
            conversation_id=persistence.conversation_id,
            content=runtime_result.content,
            choices=[
                ChatCompletionChoice(
                    message=ChatCompletionChoiceMessage(content=runtime_result.content)
                )
            ],
            usage=usage,
        )

    def _persist_successful_completion(
        self,
        *,
        request_id: str,
        profile: RuntimeProfile,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None,
        response_content: str,
        usage: ChatCompletionUsage | None,
        started_at: datetime,
        completed_at: datetime,
    ) -> ChatPersistenceResult:
        storage_started = perf_counter()
        persistence = self._repository.record_successful_completion(
            request_id=request_id,
            public_model=profile.public_id,
            runtime_model=profile.runtime_model,
            request_messages=request.messages,
            conversation_id_hint=conversation_id_hint,
            response_content=response_content,
            usage=usage,
            started_at=started_at,
            completed_at=completed_at,
        )
        log_event(
            "chat_storage_completed",
            request_id=request_id,
            outcome="success",
            duration_ms=round((perf_counter() - storage_started) * 1000, 2),
            conversation_id=persistence.conversation_id,
            model_run_id=persistence.model_run_id,
            assistant_message_id=persistence.assistant_message_id,
        )
        return persistence

    def _persist_failed_completion(
        self,
        *,
        request_id: str,
        profile: RuntimeProfile,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None,
        started_at: datetime,
        completed_at: datetime,
        error: APIError,
    ) -> ChatPersistenceResult | None:
        storage_started = perf_counter()
        try:
            persistence = self._repository.record_failed_completion(
                request_id=request_id,
                public_model=profile.public_id,
                runtime_model=profile.runtime_model,
                request_messages=request.messages,
                conversation_id_hint=conversation_id_hint,
                error_type=error.error_type,
                error_code=error.code,
                error_message=error.message,
                started_at=started_at,
                completed_at=completed_at,
            )
            log_event(
                "chat_storage_completed",
                level=logging.WARNING,
                request_id=request_id,
                outcome="persisted_failure",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=persistence.conversation_id,
                model_run_id=persistence.model_run_id,
            )
            return persistence
        except APIError:
            log_event(
                "chat_storage_completed",
                level=logging.ERROR,
                request_id=request_id,
                outcome="error",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
            )
            return None

    def _prepare_memory_context(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
    ) -> MemoryContext:
        if not self._settings.memory_enabled or not self._settings.ollama_embed_model:
            return MemoryContext(runtime_messages=list(request.messages))

        query_text = self._latest_user_message(request.messages)
        if not query_text:
            return MemoryContext(runtime_messages=list(request.messages))

        retrieval_started = perf_counter()
        try:
            embeddings = self._ollama_client.embed(
                model=self._settings.ollama_embed_model,
                input_text=query_text,
            )
            query_embedding = self._require_single_embedding(embeddings)
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
            if not hits:
                return MemoryContext(
                    runtime_messages=list(request.messages),
                    retrieval=retrieval,
                )
            return MemoryContext(
                runtime_messages=self._augment_messages_with_memory(
                    request.messages,
                    hits,
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
            self._log_memory_retrieval(
                request_id=request_id,
                outcome="error",
                retrieval=retrieval,
            )
            return MemoryContext(
                runtime_messages=list(request.messages),
                retrieval=retrieval,
            )

    def _record_memory_retrieval(
        self,
        *,
        request_id: str,
        profile: RuntimeProfile,
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
                public_model=profile.public_id,
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

    def _store_memory_items(
        self,
        *,
        request_id: str,
        conversation_id: str,
        persistence: ChatPersistenceResult,
        created_at: datetime,
    ) -> None:
        if not self._settings.memory_enabled or not self._settings.ollama_embed_model:
            return

        candidate_messages = tuple(
            message
            for message in persistence.persisted_messages
            if self._is_memory_candidate(message)
        )
        if not candidate_messages:
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

    def _augment_messages_with_memory(
        self,
        messages: list[ChatMessage],
        hits: tuple[MemorySearchHit, ...],
    ) -> list[ChatMessage]:
        memory_lines = "\n".join(f"- {hit.content}" for hit in hits)
        memory_message = ChatMessage(
            role="system",
            content=(
                "Relevant memory from prior conversations:\n"
                f"{memory_lines}\n"
                "Use it only when helpful and do not treat it as authoritative "
                "if the current conversation conflicts with it."
            ),
        )
        insert_at = 0
        while insert_at < len(messages) and messages[insert_at].role == "system":
            insert_at += 1
        return [
            *messages[:insert_at],
            memory_message,
            *messages[insert_at:],
        ]

    def _latest_user_message(self, messages: list[ChatMessage]) -> str | None:
        for message in reversed(messages):
            content = message.content.strip()
            if message.role == "user" and content:
                return content
        return None

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

    def _log_runtime_success(
        self,
        *,
        request_id: str,
        profile: RuntimeProfile,
        runtime_started: float,
        usage: ChatCompletionUsage | None,
    ) -> None:
        log_event(
            "chat_runtime_completed",
            request_id=request_id,
            public_model=profile.public_id,
            runtime_model=profile.runtime_model,
            dependency="ollama",
            outcome="success",
            duration_ms=round((perf_counter() - runtime_started) * 1000, 2),
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
        )

    def _log_runtime_error(
        self,
        *,
        request_id: str,
        profile: RuntimeProfile,
        runtime_started: float,
        error: APIError,
    ) -> None:
        log_event(
            "chat_runtime_completed",
            level=logging.WARNING,
            request_id=request_id,
            public_model=profile.public_id,
            runtime_model=profile.runtime_model,
            dependency="ollama",
            outcome="error",
            duration_ms=round((perf_counter() - runtime_started) * 1000, 2),
            error_type=error.error_type,
            error_code=error.code,
        )

    def _build_usage(
        self,
        *,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
    ) -> ChatCompletionUsage | None:
        usage = ChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        if (
            usage.prompt_tokens is None
            and usage.completion_tokens is None
            and usage.total_tokens is None
        ):
            return None
        return usage

    def _resolve_profile(self, public_model: str) -> RuntimeProfile:
        if public_model == "assistant-v1":
            return RuntimeProfile(
                public_id=public_model,
                runtime_model=self._settings.ollama_chat_model,
            )
        if public_model == "assistant-fast":
            return RuntimeProfile(
                public_id=public_model,
                runtime_model=self._settings.ollama_fast_chat_model,
            )

        raise APIError(
            status_code=422,
            error_type="validation_error",
            code="unknown_profile",
            message="Unknown assistant profile",
        )

    def _extract_conversation_hint(
        self, request: ChatCompletionRequest
    ) -> str | None:
        if not request.metadata:
            return None

        for key in ("conversation_id", "chat_id", "session_id"):
            value = request.metadata.get(key)
            if value:
                return value
        return None
