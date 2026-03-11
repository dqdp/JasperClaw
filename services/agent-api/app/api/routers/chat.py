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
from app.services.chat import ChatResult, ChatService

router = APIRouter()


def _stream_chat_result(result: ChatResult) -> StreamingResponse:
    initial_chunk = ChatCompletionChunk(
        id=result.response_id,
        created=result.created,
        model=result.public_model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionDelta(role="assistant", content=result.content),
                finish_reason=None,
            )
        ],
    )
    terminal_chunk = ChatCompletionChunk(
        id=result.response_id,
        created=result.created,
        model=result.public_model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionDelta(),
                finish_reason="stop",
            )
        ],
    )

    def sse():
        # Compatibility wrapper for clients that expect SSE before true token streaming lands.
        yield f"data: {json.dumps(initial_chunk.model_dump(exclude_none=True))}\n\n".encode()
        yield f"data: {json.dumps(terminal_chunk.model_dump(exclude_none=True))}\n\n".encode()
        yield b"data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


@router.post("/v1/chat/completions")
def chat_completions(
    request: Request,
    payload: ChatCompletionRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
):
    result = chat_service.create_chat_completion(
        request_id=get_request_id(request),
        request=payload,
    )
    if payload.stream:
        return _stream_chat_result(result)

    response = ChatCompletionResponse(
        id=result.response_id,
        created=result.created,
        model=result.public_model,
        choices=result.choices,
        usage=result.usage,
    )
    return JSONResponse(content=response.model_dump(exclude_none=True))
