from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class _FakeEngine:
    def __init__(
        self, *, audio: bytes = b"RIFFfakeWAVE", exc: Exception | None = None
    ) -> None:
        self.audio = audio
        self.exc = exc

    def synthesize(self, *, text: str, voice_id: str) -> bytes:
        _ = (text, voice_id)
        if self.exc is not None:
            raise self.exc
        return self.audio


def _events(caplog) -> list[dict]:
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "tts_service"
    ]


def _write_registry(tmp_path: Path) -> Path:
    registry_path = tmp_path / "voices.toml"
    registry_path.write_text(
        """
[voices.assistant-default]
engine = "piper"
model = "ru_RU-irina-medium"

[voices.assistant-fast]
engine = "piper"
model = "ru_RU-irina-medium"
""".strip()
    )
    return registry_path


def _write_model_artifacts(tmp_path: Path) -> Path:
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "ru_RU-irina-medium.onnx").write_bytes(b"model")
    (model_dir / "ru_RU-irina-medium.onnx.json").write_text("{}")
    return model_dir


def test_speak_request_emits_structured_events(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    client = TestClient(create_app(engine=_FakeEngine(audio=b"RIFFvalidWAVE")))

    with caplog.at_level(logging.INFO, logger="tts_service"):
        response = client.post(
            "/speak",
            json={"input": "hello world", "voice": "assistant-fast"},
            headers={"X-Request-ID": "req_tts_obs"},
        )

    assert response.status_code == 200
    events = _events(caplog)
    names = [event["event"] for event in events]
    assert "request_started" in names
    assert "speech_synthesis_completed" in names
    assert "request_completed" in names

    synthesis_event = next(
        event for event in events if event["event"] == "speech_synthesis_completed"
    )
    assert synthesis_event["request_id"] == "req_tts_obs"
    assert synthesis_event["voice_id"] == "assistant-fast"
    assert synthesis_event["outcome"] == "success"
    assert synthesis_event["duration_ms"] >= 0


def test_metrics_endpoint_exports_request_synthesis_and_readiness_metrics(
    monkeypatch, tmp_path: Path
) -> None:
    registry_path = _write_registry(tmp_path)
    model_dir = _write_model_artifacts(tmp_path)
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("PIPER_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("PIPER_BINARY_PATH", sys.executable)
    client = TestClient(create_app(engine=_FakeEngine(audio=b"RIFFvalidWAVE")))

    speak_response = client.post(
        "/speak",
        json={"input": "hello world", "voice": "assistant-fast"},
        headers={"X-Request-ID": "req_tts_metrics_speak"},
    )
    ready_response = client.get(
        "/readyz",
        headers={"X-Request-ID": "req_tts_metrics_ready"},
    )
    metrics_response = client.get("/metrics")

    assert speak_response.status_code == 200
    assert ready_response.status_code == 200
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain")
    assert (
        'tts_service_http_request_total{method="POST",path_group="speak",status_class="2xx"} 1'
        in metrics_response.text
    )
    assert (
        'tts_service_synthesis_total{error_code="none",outcome="success",voice_id="assistant-fast"} 1'
        in metrics_response.text
    )
    assert 'tts_service_readiness_total{status="ready"} 1' in metrics_response.text


def test_failure_metrics_capture_runtime_busy(monkeypatch, tmp_path: Path) -> None:
    from app.core.errors import APIError

    class _BusySpeechService:
        def synthesize(self, *, text: str, voice: str | None) -> bytes:
            _ = (text, voice)
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_busy",
                message="Speech runtime is busy",
            )

    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    client = TestClient(create_app(speech_service=_BusySpeechService()))

    response = client.post(
        "/speak",
        json={"input": "hello world"},
        headers={"X-Request-ID": "req_tts_busy"},
    )
    metrics_response = client.get("/metrics")

    assert response.status_code == 503
    assert (
        'tts_service_synthesis_total{error_code="runtime_busy",outcome="error",voice_id="assistant-default"} 1'
        in metrics_response.text
    )
    assert (
        'tts_service_http_request_total{method="POST",path_group="speak",status_class="5xx"} 1'
        in metrics_response.text
    )


def test_readyz_emits_structured_readiness_event(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    registry_path = _write_registry(tmp_path)
    model_dir = _write_model_artifacts(tmp_path)
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("PIPER_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("PIPER_BINARY_PATH", sys.executable)
    client = TestClient(create_app(engine=_FakeEngine()))

    with caplog.at_level(logging.INFO, logger="tts_service"):
        response = client.get("/readyz", headers={"X-Request-ID": "req_tts_ready"})

    assert response.status_code == 200
    events = _events(caplog)
    readiness_event = next(
        event for event in events if event["event"] == "readiness_check_completed"
    )
    assert readiness_event["request_id"] == "req_tts_ready"
    assert readiness_event["status"] == "ready"
    assert readiness_event["checks"] == {
        "models": "ok",
        "registry": "ok",
        "runtime": "ok",
        "voice_enabled": "ok",
    }
