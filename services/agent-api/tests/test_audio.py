from app.api import deps
from app.core.config import get_settings
from app.core.errors import APIError


class _FakeTtsClient:
    def __init__(
        self, *, audio: bytes = b"RIFFagentWAVE", exc: Exception | None = None
    ) -> None:
        self.audio = audio
        self.exc = exc
        self.calls: list[dict[str, str]] = []

    def synthesize(self, *, text: str, voice: str) -> bytes:
        self.calls.append({"text": text, "voice": voice})
        if self.exc is not None:
            raise self.exc
        return self.audio


def test_audio_speech_returns_voice_not_enabled_by_default(
    client, auth_headers
) -> None:
    response = client.post(
        "/v1/audio/speech",
        json={"input": "hello", "model": "tts-1"},
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "policy_error"
    assert response.json()["error"]["code"] == "voice_not_enabled"


def test_audio_speech_proxies_to_tts_service(client, monkeypatch, auth_headers) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "assistant-default")
    get_settings.cache_clear()
    deps.get_tts_client.cache_clear()
    fake_client = _FakeTtsClient(audio=b"RIFFagentWAVE")
    client.app.dependency_overrides[deps.get_tts_client] = lambda: fake_client

    response = client.post(
        "/v1/audio/speech",
        json={"input": "hello", "model": "tts-1", "voice": "assistant-fast"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content == b"RIFFagentWAVE"
    assert fake_client.calls == [{"text": "hello", "voice": "assistant-fast"}]


def test_audio_speech_uses_default_voice_when_omitted(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "assistant-default")
    get_settings.cache_clear()
    deps.get_tts_client.cache_clear()
    fake_client = _FakeTtsClient()
    client.app.dependency_overrides[deps.get_tts_client] = lambda: fake_client

    response = client.post(
        "/v1/audio/speech",
        json={"input": "hello", "model": "tts-1"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert fake_client.calls == [{"text": "hello", "voice": "assistant-default"}]


def test_audio_speech_maps_unsupported_voice_error(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()
    deps.get_tts_client.cache_clear()
    fake_client = _FakeTtsClient(
        exc=APIError(
            status_code=422,
            error_type="validation_error",
            code="unsupported_voice",
            message="Requested voice is not configured",
        )
    )
    client.app.dependency_overrides[deps.get_tts_client] = lambda: fake_client

    response = client.post(
        "/v1/audio/speech",
        json={"input": "hello", "model": "tts-1", "voice": "missing"},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "unsupported_voice"


def test_audio_speech_maps_dependency_timeout(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()
    deps.get_tts_client.cache_clear()
    fake_client = _FakeTtsClient(
        exc=APIError(
            status_code=504,
            error_type="dependency_unavailable",
            code="dependency_timeout",
            message="Speech service timed out",
        )
    )
    client.app.dependency_overrides[deps.get_tts_client] = lambda: fake_client

    response = client.post(
        "/v1/audio/speech",
        json={"input": "hello", "model": "tts-1", "voice": "assistant-default"},
        headers=auth_headers,
    )

    assert response.status_code == 504
    assert response.json()["error"]["type"] == "dependency_unavailable"
    assert response.json()["error"]["code"] == "dependency_timeout"
