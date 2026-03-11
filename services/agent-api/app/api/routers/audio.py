from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

router = APIRouter()


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
    _ = payload
    return Response(content=b"RIFF....WAVE", media_type="audio/wav")
