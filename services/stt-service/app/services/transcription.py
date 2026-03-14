from __future__ import annotations

from threading import BoundedSemaphore

from app.core.config import Settings
from app.core.errors import APIError
from app.engines.base import (
    SttEngine,
    SttEngineBadResponseError,
    SttEngineUnavailableError,
)


class TranscriptionService:
    def __init__(
        self,
        *,
        settings: Settings,
        engine: SttEngine,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._semaphore = BoundedSemaphore(settings.stt_max_concurrency)

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        if not self._settings.voice_enabled:
            raise APIError(
                status_code=403,
                error_type="policy_error",
                code="voice_not_enabled",
                message="Voice transcription is not enabled",
            )

        if not audio_bytes:
            raise APIError(
                status_code=422,
                error_type="validation_error",
                code="audio_required",
                message="Audio upload is required",
            )

        if len(audio_bytes) > self._settings.stt_max_file_bytes:
            raise APIError(
                status_code=422,
                error_type="validation_error",
                code="input_too_large",
                message="Audio upload exceeds the configured limit",
            )

        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_busy",
                message="Speech runtime is busy",
            )

        try:
            return self._engine.transcribe(
                audio_bytes=audio_bytes,
                filename=filename,
                content_type=content_type,
            )
        except SttEngineUnavailableError as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_unavailable",
                message="Speech runtime unavailable",
            ) from exc
        except SttEngineBadResponseError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Speech runtime returned an invalid transcript",
            ) from exc
        except Exception as exc:
            raise APIError(
                status_code=500,
                error_type="internal_error",
                code="internal_failure",
                message="Speech transcription failed unexpectedly",
            ) from exc
        finally:
            self._semaphore.release()
