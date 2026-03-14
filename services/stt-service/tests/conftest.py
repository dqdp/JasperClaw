import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def reset_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("STT_MODEL", "large-v3")
    monkeypatch.setenv("STT_DEVICE", "cpu")
    monkeypatch.setenv("STT_COMPUTE_TYPE", "int8")
    monkeypatch.setenv("STT_MAX_FILE_BYTES", "1024")
    monkeypatch.setenv("STT_MAX_CONCURRENCY", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
