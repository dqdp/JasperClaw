from app.api import deps
from app.core.config import get_settings
from app.core.errors import APIError


class _FakeTranscriptionPersistenceResult:
    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id


class _FakeRepository:
    def __init__(self, *, conversation_id: str = "conv_audio") -> None:
        self.conversation_id = conversation_id
        self.transcription_calls: list[dict[str, object]] = []

    def record_transcription(self, **kwargs):
        self.transcription_calls.append(kwargs)
        return _FakeTranscriptionPersistenceResult(self.conversation_id)


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
    fake_repository = _FakeRepository(conversation_id="conv_audio")
    client.app.dependency_overrides[deps.get_stt_client] = lambda: fake_client
    client.app.dependency_overrides[deps.get_chat_repository] = (
        lambda: fake_repository
    )

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"text": "privet mir"}
    assert response.headers["x-conversation-id"] == "conv_audio"
    assert fake_client.calls == [
        {
            "audio_bytes": b"RIFFagentWAVE",
            "filename": "clip.wav",
            "content_type": "audio/wav",
        }
    ]
    assert len(fake_repository.transcription_calls) == 1
    assert fake_repository.transcription_calls[0]["public_model"] == "assistant-v1"
    assert fake_repository.transcription_calls[0]["conversation_id_hint"] is None
    assert fake_repository.transcription_calls[0]["transcript"] == "privet mir"


def test_audio_transcriptions_supports_text_response_format(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()
    deps.get_stt_client.cache_clear()
    fake_client = _FakeSttClient(transcript="plain text transcript")
    fake_repository = _FakeRepository(conversation_id="conv_text")
    client.app.dependency_overrides[deps.get_stt_client] = lambda: fake_client
    client.app.dependency_overrides[deps.get_chat_repository] = (
        lambda: fake_repository
    )

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1", "response_format": "text"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["x-conversation-id"] == "conv_text"
    assert response.text == "plain text transcript"


def test_audio_transcriptions_forwards_conversation_hint_to_persistence(
    client, monkeypatch, auth_headers
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    get_settings.cache_clear()
    deps.get_stt_client.cache_clear()
    fake_client = _FakeSttClient(transcript="continued transcript")
    fake_repository = _FakeRepository(conversation_id="conv_existing")
    client.app.dependency_overrides[deps.get_stt_client] = lambda: fake_client
    client.app.dependency_overrides[deps.get_chat_repository] = (
        lambda: fake_repository
    )

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1"},
        headers={**auth_headers, "X-Conversation-ID": "conv_existing"},
    )

    assert response.status_code == 200
    assert response.headers["x-conversation-id"] == "conv_existing"
    assert len(fake_repository.transcription_calls) == 1
    assert (
        fake_repository.transcription_calls[0]["conversation_id_hint"]
        == "conv_existing"
    )


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
    fake_repository = _FakeRepository()
    fake_client = _FakeSttClient(
        exc=APIError(
            status_code=504,
            error_type="dependency_unavailable",
            code="dependency_timeout",
            message="Speech-to-text service timed out",
        )
    )
    client.app.dependency_overrides[deps.get_stt_client] = lambda: fake_client
    client.app.dependency_overrides[deps.get_chat_repository] = (
        lambda: fake_repository
    )

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("clip.wav", b"RIFFagentWAVE", "audio/wav")},
        data={"model": "whisper-1"},
        headers=auth_headers,
    )

    assert response.status_code == 504
    assert response.json()["error"]["type"] == "dependency_unavailable"
    assert response.json()["error"]["code"] == "dependency_timeout"
    assert fake_repository.transcription_calls == []


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
