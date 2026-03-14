from fastapi import FastAPI
from fastapi import File
from fastapi import Request
from fastapi import UploadFile
from fastapi.exceptions import RequestValidationError

from app.core.config import Settings
from app.core.config import get_settings
from app.core.errors import APIError
from app.core.errors import api_error_handler
from app.core.errors import request_validation_error_handler
from app.engines.base import SttEngine
from app.engines.faster_whisper import FasterWhisperEngine
from app.schemas import TranscriptionResponse
from app.services.transcription import TranscriptionService


def _build_transcription_service(
    *,
    settings: Settings,
    engine: SttEngine | None = None,
) -> TranscriptionService:
    resolved_engine = engine or FasterWhisperEngine(
        model_name=settings.stt_model,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
    )
    return TranscriptionService(settings=settings, engine=resolved_engine)


def create_app(
    *,
    settings: Settings | None = None,
    engine: SttEngine | None = None,
    transcription_service: TranscriptionService | None = None,
) -> FastAPI:
    config = settings or get_settings()
    service = transcription_service or _build_transcription_service(
        settings=config,
        engine=engine,
    )

    app = FastAPI(title="stt-service", version="0.1.0")
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/transcribe", response_model=TranscriptionResponse)
    async def transcribe(
        request: Request,
        file: UploadFile = File(...),
    ) -> TranscriptionResponse:
        _ = request
        audio_bytes = await file.read(config.stt_max_file_bytes + 1)
        transcript = service.transcribe(
            audio_bytes=audio_bytes,
            filename=file.filename or "upload.bin",
            content_type=file.content_type,
        )
        return TranscriptionResponse(text=transcript)

    return app


app = create_app()
