from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@router.get("/v1/models")
def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {"id": "assistant-v1", "object": "model", "owned_by": "local-assistant"},
            {"id": "assistant-fast", "object": "model", "owned_by": "local-assistant"},
        ],
    }


@router.post("/v1/chat/completions")
def chat_completions(payload: dict):
    stream = bool(payload.get("stream", False))
    content = {
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "created": 0,
        "model": payload.get("model", "assistant-v1"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Stub response from agent-api. Replace with orchestration pipeline.",
                },
                "finish_reason": "stop",
            }
        ],
    }
    if not stream:
        return JSONResponse(content=content)

    def sse():
        chunk = (
            'data: {"id":"chatcmpl-local","object":"chat.completion.chunk",'
            '"choices":[{"index":0,"delta":{"role":"assistant","content":"Stub response from agent-api."},'
            '"finish_reason":null}]}\n\n'
        )
        yield chunk.encode()
        yield b"data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


@router.post("/v1/audio/transcriptions")
async def audio_transcriptions(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    response_format: str = Form("json"),
):
    _ = await file.read()
    if response_format == "text":
        return Response(content="stub transcription", media_type="text/plain")
    return {"text": "stub transcription", "model": model}


@router.post("/v1/audio/speech")
def audio_speech(payload: dict):
    return Response(content=b"RIFF....WAVE", media_type="audio/wav")
