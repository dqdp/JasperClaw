from dataclasses import dataclass
from datetime import datetime, timezone
from time import time
from uuid import uuid4

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings
from app.core.errors import APIError
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
        self, *, request_id: str, request: ChatCompletionRequest
    ) -> ChatResult:
        profile = self._resolve_profile(request.model)
        started_at = datetime.now(timezone.utc)

        try:
            runtime_result = self._ollama_client.chat(
                model=profile.runtime_model,
                messages=request.messages,
            )
        except APIError as exc:
            completed_at = datetime.now(timezone.utc)
            try:
                self._repository.record_failed_completion(
                    request_id=request_id,
                    public_model=profile.public_id,
                    runtime_model=profile.runtime_model,
                    request_messages=request.messages,
                    error_type=exc.error_type,
                    error_code=exc.code,
                    error_message=exc.message,
                    started_at=started_at,
                    completed_at=completed_at,
                )
            except APIError:
                pass
            raise

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

        self._repository.record_successful_completion(
            request_id=request_id,
            public_model=profile.public_id,
            runtime_model=profile.runtime_model,
            request_messages=request.messages,
            response_content=runtime_result.content,
            usage=usage,
            started_at=started_at,
            completed_at=completed_at,
        )

        return ChatResult(
            response_id=response_id,
            created=created,
            public_model=profile.public_id,
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
