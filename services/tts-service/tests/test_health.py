import sys

from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz() -> None:
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200


def test_readyz_reports_ready_when_voice_runtime_is_usable(
    monkeypatch, tmp_path
) -> None:
    registry_path = tmp_path / "voices.toml"
    registry_path.write_text(
        """
[voices.assistant-default]
engine = "piper"
model = "ru_RU-irina-medium"
""".strip()
    )
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "ru_RU-irina-medium.onnx").write_bytes(b"model")
    (model_dir / "ru_RU-irina-medium.onnx.json").write_text("{}")
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "assistant-default")
    monkeypatch.setenv("PIPER_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("PIPER_BINARY_PATH", sys.executable)

    client = TestClient(create_app())
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_reports_not_ready_when_voice_is_disabled(monkeypatch, tmp_path) -> None:
    registry_path = tmp_path / "voices.toml"
    registry_path.write_text(
        """
[voices.assistant-default]
engine = "piper"
model = "ru_RU-irina-medium"
""".strip()
    )
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "ru_RU-irina-medium.onnx").write_bytes(b"model")
    (model_dir / "ru_RU-irina-medium.onnx.json").write_text("{}")
    monkeypatch.setenv("VOICE_ENABLED", "false")
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "assistant-default")
    monkeypatch.setenv("PIPER_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("PIPER_BINARY_PATH", sys.executable)

    client = TestClient(create_app())
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["voice_enabled"] == "fail"


def test_readyz_reports_not_ready_when_default_voice_is_missing(
    monkeypatch, tmp_path
) -> None:
    registry_path = tmp_path / "voices.toml"
    registry_path.write_text(
        """
[voices.assistant-fast]
engine = "piper"
model = "ru_RU-irina-medium"
""".strip()
    )
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "ru_RU-irina-medium.onnx").write_bytes(b"model")
    (model_dir / "ru_RU-irina-medium.onnx.json").write_text("{}")
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "assistant-default")
    monkeypatch.setenv("PIPER_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("PIPER_BINARY_PATH", sys.executable)

    client = TestClient(create_app())
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["registry"] == "fail"


def test_readyz_reports_not_ready_when_model_config_is_missing(
    monkeypatch, tmp_path
) -> None:
    registry_path = tmp_path / "voices.toml"
    registry_path.write_text(
        """
[voices.assistant-default]
engine = "piper"
model = "ru_RU-irina-medium"
""".strip()
    )
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "ru_RU-irina-medium.onnx").write_bytes(b"model")
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "assistant-default")
    monkeypatch.setenv("PIPER_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("PIPER_BINARY_PATH", sys.executable)

    client = TestClient(create_app())
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["models"] == "fail"


def test_readyz_reports_not_ready_when_runtime_binary_is_missing(
    monkeypatch, tmp_path
) -> None:
    registry_path = tmp_path / "voices.toml"
    registry_path.write_text(
        """
[voices.assistant-default]
engine = "piper"
model = "ru_RU-irina-medium"
""".strip()
    )
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "ru_RU-irina-medium.onnx").write_bytes(b"model")
    (model_dir / "ru_RU-irina-medium.onnx.json").write_text("{}")
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("TTS_VOICE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "assistant-default")
    monkeypatch.setenv("PIPER_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("PIPER_BINARY_PATH", "missing-piper-binary")

    client = TestClient(create_app())
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["runtime"] == "fail"
