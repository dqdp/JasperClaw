from time import perf_counter

from fastapi import FastAPI
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import Response

from app.core.config import Settings, get_settings
from app.core.errors import (
    APIError,
    api_error_handler,
    request_validation_error_handler,
)
from app.core.logging import configure_logging, log_event, new_request_id
from app.core.metrics import get_tts_metrics
from app.engines.base import TtsEngine
from app.engines.piper import PiperTtsEngine
from app.schemas import SpeakRequest
from app.services.readiness import ReadinessService
from app.services.speech import SpeechService
from app.voice_registry import VoiceConfig, load_voice_registry

configure_logging()


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
    metrics = get_tts_metrics()
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

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = (
            request.headers.get("X-Request-ID") or new_request_id()
        )
        started = perf_counter()
        log_event(
            "request_started",
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        except APIError as exc:
            response = await api_error_handler(request, exc)

        response.headers["X-Request-ID"] = request.state.request_id
        duration_ms = round((perf_counter() - started) * 1000, 2)
        metrics.record_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_seconds=duration_ms / 1000,
        )
        event = "request_completed" if response.status_code < 400 else "request_failed"
        log_event(
            event,
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(
            metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/readyz")
    def readyz(request: Request):
        result = readiness.check()
        metrics.record_readiness(status=result.status)
        log_event(
            "readiness_check_completed",
            request_id=request.state.request_id,
            status=result.status,
            checks=result.checks,
        )
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
    def speak(request: SpeakRequest, http_request: Request) -> Response:
        resolved_voice = (request.voice or config.tts_default_voice).strip()
        started = perf_counter()
        try:
            audio = service.synthesize(text=request.input, voice=request.voice)
        except APIError as exc:
            duration_ms = round((perf_counter() - started) * 1000, 2)
            metrics.record_synthesis(
                outcome="error",
                voice_id=resolved_voice,
                duration_seconds=duration_ms / 1000,
                error_code=exc.code,
            )
            log_event(
                "speech_synthesis_failed",
                request_id=http_request.state.request_id,
                voice_id=resolved_voice,
                error_code=exc.code,
                status_code=exc.status_code,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = round((perf_counter() - started) * 1000, 2)
        metrics.record_synthesis(
            outcome="success",
            voice_id=resolved_voice,
            duration_seconds=duration_ms / 1000,
            error_code=None,
        )
        log_event(
            "speech_synthesis_completed",
            request_id=http_request.state.request_id,
            voice_id=resolved_voice,
            duration_ms=duration_ms,
            outcome="success",
        )
        return Response(content=audio, media_type="audio/wav")

    return app


app = create_app()
