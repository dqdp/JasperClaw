from dataclasses import dataclass
from time import time
from uuid import uuid4

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings
from app.core.errors import APIError
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
    def __init__(self, settings: Settings, ollama_client: OllamaChatClient) -> None:
        self._settings = settings
        self._ollama_client = ollama_client

    def create_chat_completion(self, request: ChatCompletionRequest) -> ChatResult:
        profile = self._resolve_profile(request.model)
        runtime_result = self._ollama_client.chat(
            model=profile.runtime_model,
            messages=request.messages,
        )
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
