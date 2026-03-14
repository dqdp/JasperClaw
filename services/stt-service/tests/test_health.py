from fastapi.testclient import TestClient
import pytest

from app.main import create_app


def test_healthz() -> None:
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200


def test_readyz_reports_ready_when_runtime_is_usable() -> None:
    client = TestClient(create_app(engine=_ReadyEngine()))

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_reports_not_ready_when_voice_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "false")
    client = TestClient(create_app(engine=_ReadyEngine()))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["voice_enabled"] == "fail"


def test_readyz_reports_not_ready_when_model_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("STT_MODEL", "")
    client = TestClient(create_app(engine=_ReadyEngine()))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["config"] == "fail"


def test_readyz_reports_not_ready_when_runtime_validation_fails() -> None:
    client = TestClient(create_app(engine=_ReadyEngine(exc=RuntimeError("boom"))))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["runtime"] == "fail"


def test_startup_prewarms_runtime_before_first_request() -> None:
    engine = _ReadyEngine()

    with TestClient(create_app(engine=engine)) as client:
        assert engine.validate_calls == 1

        response = client.get("/readyz")

    assert response.status_code == 200
    assert engine.validate_calls == 2


def test_startup_prewarm_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("STT_PREWARM_ON_STARTUP", "false")
    engine = _ReadyEngine()

    with TestClient(create_app(engine=engine)) as client:
        assert engine.validate_calls == 0

        response = client.get("/readyz")

    assert response.status_code == 200
    assert engine.validate_calls == 1


def test_startup_prewarm_fails_fast_when_runtime_is_unusable() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        with TestClient(create_app(engine=_ReadyEngine(exc=RuntimeError("boom")))):
            pass


class _ReadyEngine:
    def __init__(self, *, exc: Exception | None = None) -> None:
        self.exc = exc
        self.validate_calls = 0

    def validate_runtime(self) -> None:
        self.validate_calls += 1
        if self.exc is not None:
            raise self.exc

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        _ = (audio_bytes, filename, content_type)
        return "ok"
