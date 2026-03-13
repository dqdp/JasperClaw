from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import Response

from app.core.config import Settings, get_settings
from app.core.errors import (
    APIError,
    api_error_handler,
    request_validation_error_handler,
)
from app.engines.base import TtsEngine
from app.engines.piper import PiperTtsEngine
from app.schemas import SpeakRequest
from app.services.readiness import ReadinessService
from app.services.speech import SpeechService
from app.voice_registry import VoiceConfig, load_voice_registry


def _build_speech_service(
    *,
    settings: Settings,
    engine: TtsEngine | None = None,
    voice_registry: dict[str, VoiceConfig] | None = None,
) -> SpeechService:
    resolved_registry = voice_registry or load_voice_registry(
        settings.tts_voice_registry_path
    )
    resolved_engine = engine or PiperTtsEngine(
        voices=resolved_registry,
        model_dir=settings.piper_model_dir,
        binary_path=settings.piper_binary_path,
        timeout_seconds=settings.piper_timeout_seconds,
    )
    return SpeechService(
        settings=settings,
        voice_registry=resolved_registry,
        engine=resolved_engine,
    )


def create_app(
    *,
    settings: Settings | None = None,
    speech_service: SpeechService | None = None,
    readiness_service: ReadinessService | None = None,
    engine: TtsEngine | None = None,
    voice_registry: dict[str, VoiceConfig] | None = None,
) -> FastAPI:
    config = settings or get_settings()
    resolved_registry = voice_registry or load_voice_registry(
        config.tts_voice_registry_path
    )
    service = speech_service or _build_speech_service(
        settings=config,
        engine=engine,
        voice_registry=resolved_registry,
    )
    readiness = readiness_service or ReadinessService(
        settings=config,
        voice_registry=resolved_registry,
    )

    app = FastAPI(title="tts-service", version="0.1.0")
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        result = readiness.check()
        if result.is_ready:
            return {"status": "ready"}

        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "checks": result.checks,
            },
        )

    @app.post("/speak")
    def speak(request: SpeakRequest) -> Response:
        audio = service.synthesize(text=request.input, voice=request.voice)
        return Response(content=audio, media_type="audio/wav")

    return app


app = create_app()
