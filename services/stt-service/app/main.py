import asyncio
from contextlib import asynccontextmanager
import logging
from time import perf_counter

from fastapi import FastAPI
from fastapi import File
from fastapi import Request
from fastapi import UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse

from app.core.config import Settings
from app.core.config import get_settings
from app.core.errors import APIError
from app.core.errors import api_error_handler
from app.core.errors import request_validation_error_handler
from app.core.logging import configure_logging
from app.core.logging import log_event
from app.core.logging import new_request_id
from app.core.metrics import get_stt_metrics
from app.engines.base import SttEngine
from app.engines.faster_whisper import FasterWhisperEngine
from app.schemas import TranscriptionResponse
from app.services.readiness import ReadinessService
from app.services.transcription import TranscriptionService

configure_logging()


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
    readiness_service: ReadinessService | None = None,
) -> FastAPI:
    config = settings or get_settings()
    metrics = get_stt_metrics()
    resolved_engine = engine or FasterWhisperEngine(
        model_name=config.stt_model,
        device=config.stt_device,
        compute_type=config.stt_compute_type,
    )
    service = transcription_service or _build_transcription_service(
        settings=config,
        engine=resolved_engine,
    )
    readiness = readiness_service or ReadinessService(
        settings=config,
        engine=resolved_engine,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if config.stt_prewarm_on_startup and config.voice_enabled:
            log_event("runtime_prewarm_started", model=config.stt_model)
            try:
                readiness.prewarm()
            except Exception:
                log_event(
                    "runtime_prewarm_failed",
                    level=logging.ERROR,
                    model=config.stt_model,
                )
                raise
            log_event("runtime_prewarm_completed", model=config.stt_model)
        yield

    app = FastAPI(title="stt-service", version="0.1.0", lifespan=lifespan)
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

    @app.post("/transcribe", response_model=TranscriptionResponse)
    async def transcribe(
        request: Request,
        file: UploadFile = File(...),
    ) -> TranscriptionResponse:
        started = perf_counter()
        audio_bytes = await file.read(config.stt_max_file_bytes + 1)
        try:
            # Model inference and temp-file I/O are blocking, so keep them off the
            # event loop to preserve readiness and metrics responsiveness.
            transcript = await asyncio.to_thread(
                service.transcribe,
                audio_bytes=audio_bytes,
                filename=file.filename or "upload.bin",
                content_type=file.content_type,
            )
        except APIError as exc:
            duration_ms = round((perf_counter() - started) * 1000, 2)
            metrics.record_transcription(
                outcome="error",
                duration_seconds=duration_ms / 1000,
                error_code=exc.code,
            )
            log_event(
                "speech_transcription_failed",
                request_id=request.state.request_id,
                error_code=exc.code,
                status_code=exc.status_code,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = round((perf_counter() - started) * 1000, 2)
        metrics.record_transcription(
            outcome="success",
            duration_seconds=duration_ms / 1000,
            error_code=None,
        )
        log_event(
            "speech_transcription_completed",
            request_id=request.state.request_id,
            duration_ms=duration_ms,
            outcome="success",
        )
        return TranscriptionResponse(text=transcript)

    return app


app = create_app()
