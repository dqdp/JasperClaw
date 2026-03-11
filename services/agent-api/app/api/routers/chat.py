import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import get_chat_service
from app.core.errors import get_request_id
from app.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from app.services.chat import ChatService, ChatStreamSession

router = APIRouter()


def _stream_chat_result(result: ChatStreamSession) -> StreamingResponse:
    def sse():
        for event in result.events:
            chunk = ChatCompletionChunk(
                id=result.response_id,
                created=result.created,
                model=result.public_model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionDelta(
                            role=event.role,
                            content=event.content,
                        ),
                        finish_reason=event.finish_reason,
                    )
                ],
            )
            yield f"data: {json.dumps(chunk.model_dump(exclude_none=True))}\n\n".encode()
        yield b"data: [DONE]\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"X-Conversation-ID": result.conversation_id},
    )


@router.post("/v1/chat/completions")
def chat_completions(
    request: Request,
    payload: ChatCompletionRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
):
    if payload.stream:
        result = chat_service.create_streaming_chat_completion(
            request_id=get_request_id(request),
            request=payload,
            conversation_id_hint=request.headers.get("X-Conversation-ID"),
        )
        return _stream_chat_result(result)

    result = chat_service.create_chat_completion(
        request_id=get_request_id(request),
        request=payload,
        conversation_id_hint=request.headers.get("X-Conversation-ID"),
    )

    response = ChatCompletionResponse(
        id=result.response_id,
        created=result.created,
        model=result.public_model,
        choices=result.choices,
        usage=result.usage,
    )
    return JSONResponse(
        content=response.model_dump(exclude_none=True),
        headers={"X-Conversation-ID": result.conversation_id},
    )
