from app.api import deps
from app.modules.chat.facade import ChatFacade
from app.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionUsage,
    ChatMessage,
)
from app.services.chat import ChatResult, ChatStreamEvent, ChatStreamSession


class _StubChatService:
    def __init__(self) -> None:
        self.create_calls = []
        self.stream_calls = []
        self.chat_result = ChatResult(
            response_id="chat_result",
            created=111,
            public_model="assistant-v1",
            conversation_id="conv_service",
            content="service response",
            choices=[
                ChatCompletionChoice(
                    message=ChatCompletionChoiceMessage(content="service response")
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=2,
                completion_tokens=3,
                total_tokens=5,
            ),
        )
        self.stream_result = ChatStreamSession(
            response_id="stream_result",
            created=222,
            public_model="assistant-v1",
            conversation_id="conv_stream",
            events=iter(
                [ChatStreamEvent(content="chunk", role="assistant", finish_reason=None)]
            ),
        )

    def create_chat_completion(self, **kwargs) -> ChatResult:
        self.create_calls.append(kwargs)
        return self.chat_result

    def create_streaming_chat_completion(self, **kwargs) -> ChatStreamSession:
        self.stream_calls.append(kwargs)
        return self.stream_result


class _FakeChatFacade:
    def __init__(self) -> None:
        self.calls = []

    def create_chat_completion(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None = None,
    ) -> ChatResult:
        self.calls.append(
            {
                "request_id": request_id,
                "request": request,
                "conversation_id_hint": conversation_id_hint,
            }
        )
        return ChatResult(
            response_id="chat_from_facade",
            created=123,
            public_model=request.model,
            conversation_id="conv_from_facade",
            content="facade response",
            choices=[
                ChatCompletionChoice(
                    message=ChatCompletionChoiceMessage(content="facade response")
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=4,
                completion_tokens=5,
                total_tokens=9,
            ),
        )


def test_chat_facade_delegates_non_streaming_calls() -> None:
    service = _StubChatService()
    facade = ChatFacade(chat_service=service)
    request = ChatCompletionRequest(
        model="assistant-v1",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    result = facade.create_chat_completion(
        request_id="req_test",
        request=request,
        conversation_id_hint="conv_hint",
    )

    assert result is service.chat_result
    assert service.create_calls == [
        {
            "request_id": "req_test",
            "request": request,
            "conversation_id_hint": "conv_hint",
        }
    ]


def test_chat_facade_delegates_streaming_calls() -> None:
    service = _StubChatService()
    facade = ChatFacade(chat_service=service)
    request = ChatCompletionRequest(
        model="assistant-v1",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )

    result = facade.create_streaming_chat_completion(
        request_id="req_stream",
        request=request,
        conversation_id_hint="conv_hint",
    )

    assert result is service.stream_result
    assert service.stream_calls == [
        {
            "request_id": "req_stream",
            "request": request,
            "conversation_id_hint": "conv_hint",
        }
    ]


def test_chat_completions_route_uses_chat_facade_dependency(
    client, auth_headers
) -> None:
    facade = _FakeChatFacade()

    def _unexpected_service_dependency():
        raise AssertionError("router should not resolve ChatService directly")

    client.app.dependency_overrides[deps.get_chat_facade] = lambda: facade
    client.app.dependency_overrides[deps.get_chat_service] = _unexpected_service_dependency

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "assistant-v1",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        },
        headers={**auth_headers, "X-Conversation-ID": "conv_header"},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "facade response"
    assert response.headers["x-conversation-id"] == "conv_from_facade"
    assert len(facade.calls) == 1
    assert facade.calls[0]["request"].model == "assistant-v1"
    assert facade.calls[0]["conversation_id_hint"] == "conv_header"
    assert facade.calls[0]["request_id"].startswith("req_")
