from dataclasses import dataclass

from app.clients.ollama import OllamaChatClient
from app.clients.stt import SttClient
from app.clients.tts import TtsClient
from app.core.config import Settings, is_configured_required_secret
from app.core.errors import APIError
from app.core.logging import log_event
from app.core.metrics import get_agent_metrics
from app.migrations import MigrationRunner


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
        settings: Settings,
        ollama_client: OllamaChatClient,
        migration_runner: MigrationRunner,
        stt_client: SttClient | None = None,
        tts_client: TtsClient | None = None,
    ) -> None:
        self._settings = settings
        self._ollama_client = ollama_client
        self._migration_runner = migration_runner
        self._stt_client = stt_client
        self._tts_client = tts_client

    def check(self) -> ReadinessResult:
        checks = {
            "config": self._check_config(),
            "postgres": self._check_postgres(),
            "ollama": self._check_ollama(),
        }
        if self._settings.voice_enabled:
            checks["stt"] = self._check_stt()
            checks["tts"] = self._check_tts()
        status = "ready" if all(value == "ok" for value in checks.values()) else "not_ready"
        get_agent_metrics().record_readiness(status=status)
        log_event("readiness_check_completed", status=status, checks=checks)
        return ReadinessResult(status=status, checks=checks)

    def _check_config(self) -> str:
        required = (
            self._settings.ollama_base_url,
            self._settings.ollama_chat_model,
            self._settings.ollama_fast_chat_model,
            self._settings.database_url,
        )
        if not all(value.strip() for value in required):
            return "fail"
        return (
            "ok"
            if is_configured_required_secret(self._settings.internal_openai_api_key)
            else "fail"
        )

    def _check_postgres(self) -> str:
        try:
            migration_status = self._migration_runner.status()
        except APIError:
            return "fail"
        return "ok" if migration_status.is_current else "fail"

    def _check_ollama(self) -> str:
        try:
            self._ollama_client.check_ready(
                models=(
                    self._settings.ollama_chat_model,
                    self._settings.ollama_fast_chat_model,
                )
            )
        except APIError:
            return "fail"
        return "ok"

    def _check_stt(self) -> str:
        if self._stt_client is None:
            return "fail"
        try:
            self._stt_client.check_ready()
        except APIError:
            return "fail"
        return "ok"

    def _check_tts(self) -> str:
        if self._tts_client is None:
            return "fail"
        try:
            self._tts_client.check_ready()
        except APIError:
            return "fail"
        return "ok"
