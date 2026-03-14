from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.deps import get_app_settings, get_stt_client, get_tts_client
from app.clients.stt import SttClient
from app.clients.tts import TtsClient
from app.core.config import Settings
from app.core.errors import APIError

router = APIRouter()
_SUPPORTED_TRANSCRIPTION_RESPONSE_FORMATS = frozenset({"json", "text"})
_SUPPORTED_TRANSCRIPTION_MODEL = "whisper-1"


class SpeechRequest(BaseModel):
    model: str
    input: str
    voice: str | None = None


@router.post("/v1/audio/transcriptions")
async def audio_transcriptions(
    file: UploadFile = File(...),
    model: str = Form(_SUPPORTED_TRANSCRIPTION_MODEL),
    response_format: str = Form("json"),
    settings: Annotated[Settings, Depends(get_app_settings)] = None,
    stt_client: Annotated[SttClient | None, Depends(get_stt_client)] = None,
):
    if not settings.voice_enabled:
        raise APIError(
            status_code=403,
            error_type="policy_error",
            code="voice_not_enabled",
            message="Voice transcription is not enabled",
        )
    if stt_client is None:
        raise APIError(
            status_code=503,
            error_type="dependency_unavailable",
            code="transcription_service_unavailable",
            message="Speech-to-text service unavailable",
        )

    normalized_model = model.strip()
    if normalized_model != _SUPPORTED_TRANSCRIPTION_MODEL:
        raise APIError(
            status_code=422,
            error_type="validation_error",
            code="unsupported_model",
            message="Requested transcription model is not supported",
        )

    normalized_response_format = response_format.strip().lower()
    if normalized_response_format not in _SUPPORTED_TRANSCRIPTION_RESPONSE_FORMATS:
        raise APIError(
            status_code=422,
            error_type="validation_error",
            code="invalid_response_format",
            message="Requested transcription response format is not supported",
        )

    audio_bytes = await file.read(settings.stt_max_file_bytes + 1)
    if not audio_bytes:
        raise APIError(
            status_code=422,
            error_type="validation_error",
            code="audio_required",
            message="Audio upload is required",
        )
    if len(audio_bytes) > settings.stt_max_file_bytes:
        raise APIError(
            status_code=422,
            error_type="validation_error",
            code="input_too_large",
            message="Audio upload exceeds the configured limit",
        )

    transcript = stt_client.transcribe(
        audio_bytes=audio_bytes,
        filename=file.filename or "upload.bin",
        content_type=file.content_type,
    )
    if normalized_response_format == "text":
        return Response(content=transcript, media_type="text/plain")
    return {"text": transcript}


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
