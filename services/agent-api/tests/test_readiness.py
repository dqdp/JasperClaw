from app.migrations.runner import MigrationStatus
from app.core.config import Settings
from app.core.errors import APIError
from app.services.readiness import ReadinessService


class _FakeMigrationRunner:
    def __init__(self, error: APIError | None = None) -> None:
        self.error = error
        self.calls = 0

    def status(self) -> MigrationStatus:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return MigrationStatus(
            applied_versions=("0001_initial_schema",),
            pending_versions=(),
        )


class _FakeOllamaClient:
    def __init__(self, error: APIError | None = None) -> None:
        self.error = error
        self.models = None

    def check_ready(self, models: tuple[str, ...]) -> None:
        self.models = models
        if self.error is not None:
            raise self.error


def _settings(internal_openai_api_key: str = "test-internal-key") -> Settings:
    return Settings(
        ollama_base_url="http://ollama.test",
        ollama_chat_model="qwen3:8b",
        ollama_fast_chat_model="qwen3:4b",
        ollama_timeout_seconds=5.0,
        database_url="postgresql://assistant:change-me@postgres:5432/assistant",
        internal_openai_api_key=internal_openai_api_key,
    )


def test_readiness_service_reports_ready() -> None:
    ollama = _FakeOllamaClient()
    migrations = _FakeMigrationRunner()
    service = ReadinessService(
        settings=_settings(),
        ollama_client=ollama,
        migration_runner=migrations,
    )

    result = service.check()

    assert result.status == "ready"
    assert result.checks == {"config": "ok", "postgres": "ok", "ollama": "ok"}
    assert migrations.calls == 1
    assert ollama.models == ("qwen3:8b", "qwen3:4b")


def test_readiness_service_reports_dependency_failure() -> None:
    ollama = _FakeOllamaClient(
        error=APIError(
            status_code=503,
            error_type="dependency_unavailable",
            code="runtime_unavailable",
            message="Model runtime unavailable",
        )
    )
    migrations = _FakeMigrationRunner(
        error=APIError(
            status_code=503,
            error_type="dependency_unavailable",
            code="storage_unavailable",
            message="Persistent storage unavailable",
        )
    )
    service = ReadinessService(
        settings=_settings(),
        ollama_client=ollama,
        migration_runner=migrations,
    )

    result = service.check()

    assert result.status == "not_ready"
    assert result.checks == {"config": "ok", "postgres": "fail", "ollama": "fail"}


def test_readiness_service_reports_pending_migrations_as_not_ready() -> None:
    class _PendingMigrationRunner:
        def __init__(self) -> None:
            self.calls = 0

        def status(self) -> MigrationStatus:
            self.calls += 1
            return MigrationStatus(
                applied_versions=("0001_initial_schema",),
                pending_versions=("0002_conversation_updates",),
            )

    ollama = _FakeOllamaClient()
    migrations = _PendingMigrationRunner()
    service = ReadinessService(
        settings=_settings(),
        ollama_client=ollama,
        migration_runner=migrations,
    )

    result = service.check()

    assert result.status == "not_ready"
    assert result.checks == {"config": "ok", "postgres": "fail", "ollama": "ok"}
    assert migrations.calls == 1


def test_readiness_service_reports_missing_internal_api_key_as_not_ready() -> None:
    ollama = _FakeOllamaClient()
    migrations = _FakeMigrationRunner()
    service = ReadinessService(
        settings=_settings(internal_openai_api_key=""),
        ollama_client=ollama,
        migration_runner=migrations,
    )

    result = service.check()

    assert result.status == "not_ready"
    assert result.checks == {"config": "fail", "postgres": "ok", "ollama": "ok"}


def test_readiness_service_reports_placeholder_internal_api_key_as_not_ready() -> None:
    ollama = _FakeOllamaClient()
    migrations = _FakeMigrationRunner()
    service = ReadinessService(
        settings=_settings(internal_openai_api_key="change-me"),
        ollama_client=ollama,
        migration_runner=migrations,
    )

    result = service.check()

    assert result.status == "not_ready"
    assert result.checks == {"config": "fail", "postgres": "ok", "ollama": "ok"}
