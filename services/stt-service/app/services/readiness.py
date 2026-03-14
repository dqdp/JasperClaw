from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.engines.base import SttEngine


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    status: str
    checks: dict[str, str]

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"


class ReadinessService:
    def __init__(
        self,
        *,
        settings: Settings,
        engine: SttEngine,
    ) -> None:
        self._settings = settings
        self._engine = engine

    def check(self) -> ReadinessResult:
        voice_enabled = self._check_voice_enabled()
        config = self._check_config()
        runtime = self._check_runtime(
            voice_enabled=voice_enabled,
            config=config,
        )
        checks = {
            "voice_enabled": voice_enabled,
            "config": config,
            "runtime": runtime,
        }
        status = (
            "ready" if all(value == "ok" for value in checks.values()) else "not_ready"
        )
        return ReadinessResult(status=status, checks=checks)

    def prewarm(self) -> None:
        if not self._settings.voice_enabled or not self._settings.stt_prewarm_on_startup:
            return
        if self._check_config() != "ok":
            raise RuntimeError("STT runtime prewarm configuration is invalid")
        self._engine.validate_runtime()

    def _check_voice_enabled(self) -> str:
        return "ok" if self._settings.voice_enabled else "fail"

    def _check_config(self) -> str:
        if not self._settings.stt_model:
            return "fail"
        if not self._settings.stt_device:
            return "fail"
        if not self._settings.stt_compute_type:
            return "fail"
        return "ok"

    def _check_runtime(self, *, voice_enabled: str, config: str) -> str:
        if voice_enabled != "ok" or config != "ok":
            return "fail"
        try:
            self._engine.validate_runtime()
        except Exception:
            return "fail"
        return "ok"
