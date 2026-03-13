from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class _FakeEngine:
    def __init__(
        self, *, audio: bytes = b"RIFFfakeWAVE", exc: Exception | None = None
    ) -> None:
        self.audio = audio
        self.exc = exc
        self.calls: list[dict[str, str]] = []

    def synthesize(self, *, text: str, voice_id: str) -> bytes:
        self.calls.append({"text": text, "voice_id": voice_id})
        if self.exc is not None:
            raise self.exc
        return self.audio


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


def test_speak_returns_wav_bytes_for_valid_request(monkeypatch, tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    engine = _FakeEngine(audio=b"RIFFvalidWAVE")
    client = TestClient(create_app(engine=engine))

    response = client.post(
        "/speak", json={"input": "hello world", "voice": "assistant-fast"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content == b"RIFFvalidWAVE"
    assert engine.calls == [{"text": "hello world", "voice_id": "assistant-fast"}]


def test_speak_uses_default_voice_when_omitted(monkeypatch, tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    engine = _FakeEngine()
    client = TestClient(create_app(engine=engine))

    response = client.post("/speak", json={"input": "hello world"})

    assert response.status_code == 200
    assert engine.calls == [{"text": "hello world", "voice_id": "assistant-default"}]


def test_speak_rejects_unknown_voice(monkeypatch, tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    client = TestClient(create_app(engine=_FakeEngine()))

    response = client.post("/speak", json={"input": "hello world", "voice": "missing"})

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "unsupported_voice"


def test_speak_rejects_disabled_voice_mode(monkeypatch, tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("VOICE_ENABLED", "false")
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    client = TestClient(create_app(engine=_FakeEngine()))

    response = client.post("/speak", json={"input": "hello world"})

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "policy_error"
    assert response.json()["error"]["code"] == "voice_not_enabled"


def test_speak_rejects_too_large_input(monkeypatch, tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("TTS_MAX_INPUT_CHARS", "5")
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    client = TestClient(create_app(engine=_FakeEngine()))

    response = client.post("/speak", json={"input": "hello world"})

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "input_too_large"


def test_speak_returns_runtime_busy_when_service_is_busy(
    monkeypatch, tmp_path: Path
) -> None:
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

    response = client.post("/speak", json={"input": "hello world"})

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "dependency_unavailable"
    assert response.json()["error"]["code"] == "runtime_busy"


def test_speak_maps_unexpected_engine_failure(monkeypatch, tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path)
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    client = TestClient(create_app(engine=_FakeEngine(exc=RuntimeError("boom"))))

    response = client.post("/speak", json={"input": "hello world"})

    assert response.status_code == 500
    assert response.json()["error"]["type"] == "internal_error"
    assert response.json()["error"]["code"] == "internal_failure"
