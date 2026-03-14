from fastapi.testclient import TestClient

from app.main import create_app


class _FakeEngine:
    def __init__(
        self, *, transcript: str = "hello world", exc: Exception | None = None
    ) -> None:
        self.transcript = transcript
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        self.calls.append(
            {
                "audio_bytes": audio_bytes,
                "filename": filename,
                "content_type": content_type,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.transcript


def test_transcribe_returns_json_text_for_valid_upload() -> None:
    engine = _FakeEngine(transcript="privet mir")
    client = TestClient(create_app(engine=engine))

    response = client.post(
        "/transcribe",
        files={"file": ("clip.wav", b"RIFFfakeWAVE", "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "privet mir"}
    assert engine.calls == [
        {
            "audio_bytes": b"RIFFfakeWAVE",
            "filename": "clip.wav",
            "content_type": "audio/wav",
        }
    ]


def test_transcribe_rejects_disabled_voice_mode(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "false")
    client = TestClient(create_app(engine=_FakeEngine()))

    response = client.post(
        "/transcribe",
        files={"file": ("clip.wav", b"RIFFfakeWAVE", "audio/wav")},
    )

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "policy_error"
    assert response.json()["error"]["code"] == "voice_not_enabled"


def test_transcribe_rejects_empty_audio_upload() -> None:
    client = TestClient(create_app(engine=_FakeEngine()))

    response = client.post(
        "/transcribe",
        files={"file": ("clip.wav", b"", "audio/wav")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "audio_required"


def test_transcribe_rejects_oversized_upload(monkeypatch) -> None:
    monkeypatch.setenv("STT_MAX_FILE_BYTES", "4")
    client = TestClient(create_app(engine=_FakeEngine()))

    response = client.post(
        "/transcribe",
        files={"file": ("clip.wav", b"RIFFfakeWAVE", "audio/wav")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "input_too_large"


def test_transcribe_returns_runtime_busy_when_service_is_busy() -> None:
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
    )

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "dependency_unavailable"
    assert response.json()["error"]["code"] == "runtime_busy"


def test_transcribe_maps_unexpected_engine_failure() -> None:
    client = TestClient(create_app(engine=_FakeEngine(exc=RuntimeError("boom"))))

    response = client.post(
        "/transcribe",
        files={"file": ("clip.wav", b"RIFFfakeWAVE", "audio/wav")},
    )

    assert response.status_code == 500
    assert response.json()["error"]["type"] == "internal_error"
    assert response.json()["error"]["code"] == "internal_failure"
