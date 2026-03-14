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


class _FakeSttClient:
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


def test_audio_transcriptions_returns_voice_not_enabled_by_default(
    client, auth_headers
) -> None:
    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1"},
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "policy_error"
    assert response.json()["error"]["code"] == "voice_not_enabled"


def test_audio_transcriptions_proxies_to_stt_service_as_json(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()
    deps.get_stt_client.cache_clear()
    fake_client = _FakeSttClient(transcript="privet mir")
    client.app.dependency_overrides[deps.get_stt_client] = lambda: fake_client

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"text": "privet mir"}
    assert fake_client.calls == [
        {
            "audio_bytes": b"RIFFagentWAVE",
            "filename": "clip.wav",
            "content_type": "audio/wav",
        }
    ]


def test_audio_transcriptions_supports_text_response_format(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()
    deps.get_stt_client.cache_clear()
    fake_client = _FakeSttClient(transcript="plain text transcript")
    client.app.dependency_overrides[deps.get_stt_client] = lambda: fake_client

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1", "response_format": "text"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "plain text transcript"


def test_audio_transcriptions_rejects_unsupported_public_model(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "large-v3"},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "unsupported_model"


def test_audio_transcriptions_rejects_invalid_response_format(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1", "response_format": "verbose_json"},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
    assert response.json()["error"]["code"] == "invalid_response_format"


def test_audio_transcriptions_maps_dependency_timeout(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()
    deps.get_stt_client.cache_clear()
    fake_client = _FakeSttClient(
        exc=APIError(
            status_code=504,
            error_type="dependency_unavailable",
            code="dependency_timeout",
            message="Speech-to-text service timed out",
        )
    )
    client.app.dependency_overrides[deps.get_stt_client] = lambda: fake_client

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1"},
        headers=auth_headers,
    )

    assert response.status_code == 504
    assert response.json()["error"]["type"] == "dependency_unavailable"
    assert response.json()["error"]["code"] == "dependency_timeout"


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
