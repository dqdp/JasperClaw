from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from app.main import create_app


class _FakeEngine:
    def __init__(
        self, *, transcript: str = "hello world", exc: Exception | None = None
    ) -> None:
        self.transcript = transcript
        self.exc = exc

    def validate_runtime(self) -> None:
        return None

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        _ = (audio_bytes, filename, content_type)
        if self.exc is not None:
            raise self.exc
        return self.transcript


def _events(caplog) -> list[dict]:
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "stt_service"
    ]


def test_transcribe_request_emits_structured_events(caplog) -> None:
    client = TestClient(create_app(engine=_FakeEngine(transcript="privet mir")))

    with caplog.at_level(logging.INFO, logger="stt_service"):
        response = client.post(
            "/transcribe",
            files={"file": ("clip.wav", b"RIFFfakeWAVE", "audio/wav")},
            headers={"X-Request-ID": "req_stt_obs"},
        )

    assert response.status_code == 200
    events = _events(caplog)
    names = [event["event"] for event in events]
    assert "request_started" in names
    assert "speech_transcription_completed" in names
    assert "request_completed" in names

    transcription_event = next(
        event for event in events if event["event"] == "speech_transcription_completed"
    )
    assert transcription_event["request_id"] == "req_stt_obs"
    assert transcription_event["duration_ms"] >= 0
    assert transcription_event["outcome"] == "success"


def test_metrics_endpoint_exports_request_transcription_and_readiness_metrics() -> None:
    client = TestClient(create_app(engine=_FakeEngine(transcript="privet mir")))

    transcribe_response = client.post(
        "/transcribe",
        files={"file": ("clip.wav", b"RIFFfakeWAVE", "audio/wav")},
        headers={"X-Request-ID": "req_stt_metrics_transcribe"},
    )
    ready_response = client.get(
        "/readyz",
        headers={"X-Request-ID": "req_stt_metrics_ready"},
    )
    metrics_response = client.get("/metrics")

    assert transcribe_response.status_code == 200
    assert ready_response.status_code == 200
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain")
    assert (
        'stt_service_http_request_total{method="POST",path_group="transcribe",status_class="2xx"} 1'
        in metrics_response.text
    )
    assert (
        'stt_service_transcription_total{error_code="none",outcome="success"} 1'
        in metrics_response.text
    )
    assert 'stt_service_readiness_total{status="ready"} 1' in metrics_response.text


def test_failure_metrics_capture_runtime_busy() -> None:
    from app.core.errors import APIError

    class _BusyTranscriptionService:
        def transcribe(
            self,
            *,
            audio_bytes: bytes,
            filename: str,
            content_type: str | None,
        ) -> str:
            _ = (audio_bytes, filename, content_type)
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_busy",
                message="Speech runtime is busy",
            )

    client = TestClient(create_app(transcription_service=_BusyTranscriptionService()))

    response = client.post(
        "/transcribe",
        files={"file": ("clip.wav", b"RIFFfakeWAVE", "audio/wav")},
        headers={"X-Request-ID": "req_stt_busy"},
    )
    metrics_response = client.get("/metrics")

    assert response.status_code == 503
    assert (
        'stt_service_transcription_total{error_code="runtime_busy",outcome="error"} 1'
        in metrics_response.text
    )
    assert (
        'stt_service_http_request_total{method="POST",path_group="transcribe",status_class="5xx"} 1'
        in metrics_response.text
    )


def test_readyz_emits_structured_readiness_event(caplog) -> None:
    client = TestClient(create_app(engine=_FakeEngine()))

    with caplog.at_level(logging.INFO, logger="stt_service"):
        response = client.get("/readyz", headers={"X-Request-ID": "req_stt_ready"})

    assert response.status_code == 200
    events = _events(caplog)
    readiness_event = next(
        event for event in events if event["event"] == "readiness_check_completed"
    )
    assert readiness_event["request_id"] == "req_stt_ready"
    assert readiness_event["status"] == "ready"
    assert readiness_event["checks"] == {
        "config": "ok",
        "runtime": "ok",
        "voice_enabled": "ok",
    }
