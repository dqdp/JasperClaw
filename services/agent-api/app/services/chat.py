from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from time import perf_counter, time
from uuid import uuid4

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings
from app.core.errors import APIError
from app.core.logging import log_event
from app.repositories import ChatRepository
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
            log_event(
                "chat_runtime_completed",
                level=logging.WARNING,
                request_id=request_id,
                public_model=profile.public_id,
                runtime_model=profile.runtime_model,
                dependency="ollama",
                outcome="error",
                duration_ms=round((perf_counter() - runtime_started) * 1000, 2),
                error_type=exc.error_type,
                error_code=exc.code,
            )
            storage_started = perf_counter()
            try:
                persistence = self._repository.record_failed_completion(
                    request_id=request_id,
                    public_model=profile.public_id,
                    runtime_model=profile.runtime_model,
                    request_messages=request.messages,
                    conversation_id_hint=resolved_conversation_hint,
                    error_type=exc.error_type,
                    error_code=exc.code,
                    error_message=exc.message,
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
                pass
            raise

        runtime_duration_ms = round((perf_counter() - runtime_started) * 1000, 2)
        completed_at = datetime.now(timezone.utc)
        created = int(time())
        response_id = f"chatcmpl_{uuid4().hex[:12]}"
        usage = ChatCompletionUsage(
            prompt_tokens=runtime_result.prompt_tokens,
            completion_tokens=runtime_result.completion_tokens,
            total_tokens=runtime_result.total_tokens,
        )
        if (
            usage.prompt_tokens is None
            and usage.completion_tokens is None
            and usage.total_tokens is None
        ):
            usage = None

        log_event(
            "chat_runtime_completed",
            request_id=request_id,
            public_model=profile.public_id,
            runtime_model=profile.runtime_model,
            dependency="ollama",
            outcome="success",
            duration_ms=runtime_duration_ms,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
        )

        storage_started = perf_counter()
        persistence = self._repository.record_successful_completion(
            request_id=request_id,
            public_model=profile.public_id,
            runtime_model=profile.runtime_model,
            request_messages=request.messages,
            conversation_id_hint=resolved_conversation_hint,
            response_content=runtime_result.content,
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
