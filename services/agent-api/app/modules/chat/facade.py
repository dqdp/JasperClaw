from app.schemas.chat import ChatCompletionRequest
from app.services.chat import ChatResult, ChatService, ChatStreamSession


class ChatFacade:
    # Phase 1 seam: keep the current chat behavior in ChatService while the
    # transport layer depends on a stable application entrypoint.
    def __init__(self, chat_service: ChatService) -> None:
        self._chat_service = chat_service

    def create_chat_completion(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None = None,
    ) -> ChatResult:
        return self._chat_service.create_chat_completion(
            request_id=request_id,
            request=request,
            conversation_id_hint=conversation_id_hint,
        )

    def create_streaming_chat_completion(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None = None,
    ) -> ChatStreamSession:
        return self._chat_service.create_streaming_chat_completion(
            request_id=request_id,
            request=request,
            conversation_id_hint=conversation_id_hint,
        )
