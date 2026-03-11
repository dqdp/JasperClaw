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
from app.repositories import ChatPersistenceResult, ChatRepository, ConversationContext
from app.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionUsage,
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
        started_at = datetime.now(timezone.utc)
        runtime_started = perf_counter()

        try:
            runtime_result = self._ollama_client.chat(
                model=profile.runtime_model,
                messages=request.messages,
            )
        except APIError as exc:
            completed_at = datetime.now(timezone.utc)
            self._log_runtime_error(
                request_id=request_id,
                profile=profile,
                runtime_started=runtime_started,
                error=exc,
            )
            self._persist_failed_completion(
                request_id=request_id,
                profile=profile,
                request=request,
                conversation_id_hint=resolved_conversation_hint,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            raise

        completed_at = datetime.now(timezone.utc)
        return self._build_success_result(
            request_id=request_id,
            request=request,
            profile=profile,
            conversation_id_hint=resolved_conversation_hint,
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
        runtime_started = perf_counter()
        stream = self._ollama_client.stream_chat(
            model=profile.runtime_model,
            messages=request.messages,
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
            self._persist_failed_completion(
                request_id=request_id,
                profile=profile,
                request=request,
                conversation_id_hint=context.conversation_id,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            raise

        response_id = f"chatcmpl_{uuid4().hex[:12]}"
        created = int(time())
        events = self._stream_events(
            request_id=request_id,
            request=request,
            profile=profile,
            context=context,
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
                self._persist_successful_completion(
                    request_id=request_id,
                    profile=profile,
                    request=request,
                    conversation_id_hint=context.conversation_id,
                    response_content="".join(content_parts),
                    usage=usage,
                    started_at=started_at,
                    completed_at=completed_at,
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
            self._persist_failed_completion(
                request_id=request_id,
                profile=profile,
                request=request,
                conversation_id_hint=context.conversation_id,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
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
    ) -> None:
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
        except APIError:
            log_event(
                "chat_storage_completed",
                level=logging.ERROR,
                request_id=request_id,
                outcome="error",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
            )

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
