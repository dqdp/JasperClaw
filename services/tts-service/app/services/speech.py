from __future__ import annotations

from threading import BoundedSemaphore

from app.core.config import Settings
from app.core.errors import APIError
from app.engines.base import (
    TtsEngine,
    TtsEngineBadResponseError,
    TtsEngineTimeoutError,
    TtsEngineUnavailableError,
)
from app.voice_registry import VoiceConfig


class SpeechService:
    def __init__(
        self,
        *,
        settings: Settings,
        voice_registry: dict[str, VoiceConfig],
        engine: TtsEngine,
    ) -> None:
        self._settings = settings
        self._voice_registry = voice_registry
        self._engine = engine
        self._semaphore = BoundedSemaphore(settings.tts_max_concurrency)

    def synthesize(self, *, text: str, voice: str | None) -> bytes:
        if not self._settings.voice_enabled:
            raise APIError(
                status_code=403,
                error_type="policy_error",
                code="voice_not_enabled",
                message="Voice synthesis is not enabled",
            )

        normalized_text = text.strip()
        if not normalized_text:
            raise APIError(
                status_code=422,
                error_type="validation_error",
                code="missing_required_field",
                message="Input text is required",
            )
        if len(normalized_text) > self._settings.tts_max_input_chars:
            raise APIError(
                status_code=422,
                error_type="validation_error",
                code="input_too_large",
                message="Input text exceeds the configured limit",
            )

        voice_id = (voice or self._settings.tts_default_voice).strip()
        voice_config = self._voice_registry.get(voice_id)
        if voice_config is None:
            raise APIError(
                status_code=422,
                error_type="validation_error",
                code="unsupported_voice",
                message="Requested voice is not configured",
            )
        if voice_config.engine != self._settings.tts_engine:
            raise APIError(
                status_code=500,
                error_type="internal_error",
                code="unexpected_state",
                message="Voice registry does not match the active engine",
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
            return self._engine.synthesize(text=normalized_text, voice_id=voice_id)
        except TtsEngineTimeoutError as exc:
            raise APIError(
                status_code=504,
                error_type="dependency_unavailable",
                code="dependency_timeout",
                message="Speech runtime timed out",
            ) from exc
        except TtsEngineUnavailableError as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_unavailable",
                message="Speech runtime unavailable",
            ) from exc
        except TtsEngineBadResponseError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Speech runtime returned an invalid response",
            ) from exc
        except Exception as exc:
            raise APIError(
                status_code=500,
                error_type="internal_error",
                code="internal_failure",
                message="Speech synthesis failed unexpectedly",
            ) from exc
        finally:
            self._semaphore.release()
