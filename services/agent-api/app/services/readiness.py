from dataclasses import dataclass

from app.clients.ollama import OllamaChatClient
from app.core.config import Settings
from app.core.errors import APIError
from app.core.logging import log_event
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
    ) -> None:
        self._settings = settings
        self._ollama_client = ollama_client
        self._migration_runner = migration_runner

    def check(self) -> ReadinessResult:
        checks = {
            "config": self._check_config(),
            "postgres": self._check_postgres(),
            "ollama": self._check_ollama(),
        }
        status = "ready" if all(value == "ok" for value in checks.values()) else "not_ready"
        log_event("readiness_check_completed", status=status, checks=checks)
        return ReadinessResult(status=status, checks=checks)

    def _check_config(self) -> str:
        required = (
            self._settings.ollama_base_url,
            self._settings.ollama_chat_model,
            self._settings.ollama_fast_chat_model,
            self._settings.database_url,
            self._settings.internal_openai_api_key,
        )
        return "ok" if all(value.strip() for value in required) else "fail"

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
