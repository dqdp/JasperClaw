from app.api import deps
from app.core.config import get_settings
from app.migrations.runner import MigrationStatus
from fastapi.testclient import TestClient

from app.main import app
from app.services.readiness import ReadinessResult


class _FakeReadinessService:
    def __init__(self, result: ReadinessResult) -> None:
        self._result = result

    def check(self) -> ReadinessResult:
        return self._result


def test_healthz() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz() -> None:
    client = TestClient(app)
    client.app.dependency_overrides[deps.get_readiness_service] = lambda: _FakeReadinessService(
        ReadinessResult(status="ready", checks={"config": "ok", "postgres": "ok", "ollama": "ok"})
    )
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readyz_not_ready() -> None:
    client = TestClient(app)
    client.app.dependency_overrides[deps.get_readiness_service] = lambda: _FakeReadinessService(
        ReadinessResult(
            status="not_ready",
            checks={"config": "ok", "postgres": "fail", "ollama": "ok"},
        )
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"config": "ok", "postgres": "fail", "ollama": "ok"},
    }


def test_readyz_reports_placeholder_internal_api_key_as_not_ready(monkeypatch) -> None:
    class _OkMigrationRunner:
        def status(self) -> MigrationStatus:
            return MigrationStatus(
                applied_versions=("0001_initial_schema",),
                pending_versions=(),
            )

    class _OkOllamaClient:
        def check_ready(self, models) -> None:
            _ = models

    monkeypatch.setenv("INTERNAL_OPENAI_API_KEY", "change-me")
    get_settings.cache_clear()
    deps.get_ollama_client.cache_clear()
    deps.get_migration_runner.cache_clear()

    client = TestClient(app)
    client.app.dependency_overrides[deps.get_ollama_client] = lambda: _OkOllamaClient()
    client.app.dependency_overrides[deps.get_migration_runner] = lambda: _OkMigrationRunner()

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"config": "fail", "postgres": "ok", "ollama": "ok"},
    }
