from app.api import deps
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
