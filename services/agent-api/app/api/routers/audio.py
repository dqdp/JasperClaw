from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.deps import get_app_settings, get_tts_client
from app.clients.tts import TtsClient
from app.core.config import Settings
from app.core.errors import APIError

router = APIRouter()


class SpeechRequest(BaseModel):
    model: str
    input: str
    voice: str | None = None


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
def audio_speech(
    payload: SpeechRequest,
    settings: Annotated[Settings, Depends(get_app_settings)],
    tts_client: Annotated[TtsClient | None, Depends(get_tts_client)],
):
    if not settings.voice_enabled:
        raise APIError(
            status_code=403,
            error_type="policy_error",
            code="voice_not_enabled",
            message="Voice synthesis is not enabled",
        )
    if tts_client is None:
        raise APIError(
            status_code=503,
            error_type="dependency_unavailable",
            code="speech_service_unavailable",
            message="Speech service unavailable",
        )

    audio = tts_client.synthesize(
        text=payload.input,
        voice=payload.voice or settings.tts_default_voice,
    )
    return Response(content=audio, media_type="audio/wav")
