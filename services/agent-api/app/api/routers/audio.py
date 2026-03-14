from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.api.deps import (
    get_app_settings,
    get_chat_repository,
    get_memory_service,
    get_stt_client,
    get_tts_client,
)
from app.clients.stt import SttClient
from app.clients.tts import TtsClient
from app.core.config import Settings
from app.core.errors import APIError, get_request_id
from app.modules.chat.memory import MemoryService
from app.repositories import ChatRepository

router = APIRouter()
_SUPPORTED_TRANSCRIPTION_RESPONSE_FORMATS = frozenset({"json", "text"})
_SUPPORTED_TRANSCRIPTION_MODEL = "whisper-1"
_SUPPORTED_SPEECH_MODEL = "tts-1"


class SpeechRequest(BaseModel):
    model: str
    input: str
    voice: str | None = None


@router.post("/v1/audio/transcriptions")
def audio_transcriptions(
    request: Request,
    file: UploadFile = File(...),
    model: str = Form(_SUPPORTED_TRANSCRIPTION_MODEL),
    response_format: str = Form("json"),
    settings: Annotated[Settings, Depends(get_app_settings)] = None,
    stt_client: Annotated[SttClient | None, Depends(get_stt_client)] = None,
    repository: Annotated[ChatRepository, Depends(get_chat_repository)] = None,
    memory_service: Annotated[MemoryService, Depends(get_memory_service)] = None,
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

    public_model_hint = None
    public_model_header = request.headers.get("X-Public-Model")
    if public_model_header is not None:
        normalized_public_model = public_model_header.strip()
        if normalized_public_model:
            if normalized_public_model not in settings.public_profiles:
                raise APIError(
                    status_code=422,
                    error_type="validation_error",
                    code="unsupported_public_model",
                    message="Requested public model is not supported",
                )
            public_model_hint = normalized_public_model

    # Keep the whole voice path on FastAPI's sync threadpool until the collaborators
    # move off their current blocking HTTP/Postgres implementations.
    audio_bytes = file.file.read(settings.stt_max_file_bytes + 1)
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

    created_at = datetime.now(timezone.utc)
    transcript = stt_client.transcribe(
        audio_bytes=audio_bytes,
        filename=file.filename or "upload.bin",
        content_type=file.content_type,
    )
    persistence = repository.record_transcription(
        public_model_hint=public_model_hint,
        conversation_id_hint=request.headers.get("X-Conversation-ID"),
        transcript=transcript,
        created_at=created_at,
    )
    memory_service.store_persisted_messages(
        request_id=get_request_id(request),
        conversation_id=persistence.conversation_id,
        persisted_messages=(persistence.persisted_message,),
        created_at=created_at,
    )
    headers = {"X-Conversation-ID": persistence.conversation_id}
    if normalized_response_format == "text":
        return Response(content=transcript, media_type="text/plain", headers=headers)
    return JSONResponse(content={"text": transcript}, headers=headers)


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
    if payload.model.strip() != _SUPPORTED_SPEECH_MODEL:
        raise APIError(
            status_code=422,
            error_type="validation_error",
            code="unsupported_model",
            message="Requested speech model is not supported",
        )

    audio = tts_client.synthesize(
        text=payload.input,
        voice=payload.voice or settings.tts_default_voice,
    )
    return Response(content=audio, media_type="audio/wav")
