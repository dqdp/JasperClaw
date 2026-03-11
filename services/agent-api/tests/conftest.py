import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core.config import get_settings
from app.main import app


@pytest.fixture(autouse=True)
def reset_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test")
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_FAST_CHAT_MODEL", "qwen3:4b")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("POSTGRES_HOST", "postgres.test")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "assistant")
    monkeypatch.setenv("POSTGRES_USER", "assistant")
    monkeypatch.setenv("POSTGRES_PASSWORD", "change-me")
    get_settings.cache_clear()
    deps.get_ollama_client.cache_clear()
    deps.get_chat_repository.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    deps.get_ollama_client.cache_clear()
    deps.get_chat_repository.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
