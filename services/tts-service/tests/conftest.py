import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def reset_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("TTS_ENGINE", "piper")
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "assistant-default")
    monkeypatch.setenv("TTS_MAX_INPUT_CHARS", "1000")
    monkeypatch.setenv("TTS_MAX_CONCURRENCY", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
