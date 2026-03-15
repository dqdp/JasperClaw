from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _load_smoke_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "smoke-agent-api.py"
    spec = spec_from_file_location("smoke_agent_api", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _discovery_payload() -> tuple[int, dict]:
    return (
        200,
        {
            "capabilities": [
                {"id": "voice", "label": "Voice conversation", "state": "real"},
                {
                    "id": "spotify_playback",
                    "label": "Spotify playback",
                    "state": "demo",
                },
                {
                    "id": "spotify_station",
                    "label": "Spotify station",
                    "state": "demo",
                },
                {
                    "id": "telegram_send",
                    "label": "Telegram send",
                    "state": "unconfigured",
                },
            ],
            "commands": ["/help", "/status", "/ask <message>"],
            "help_text": "Spotify playback is demo. Telegram send is not configured.",
            "status_text": (
                "Voice conversation: connected\n"
                "Spotify playback: demo\n"
                "Spotify station: demo\n"
                "Telegram send: not configured"
            ),
        },
    )


def test_main_passes_without_voice_check(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_smoke_module()
    monkeypatch.setenv("SMOKE_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("SMOKE_INTERNAL_OPENAI_API_KEY", "smoke-key")
    monkeypatch.delenv("SMOKE_CHECK_VOICE", raising=False)
    monkeypatch.delenv("SMOKE_CHECK_STT", raising=False)

    wait_payloads = iter(
        [
            (
                200,
                {
                    "data": [
                        {"id": "assistant-v1"},
                        {"id": "assistant-fast"},
                    ]
                },
            ),
            _discovery_payload(),
            (
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "ok",
                            }
                        }
                    ]
                },
            ),
        ]
    )

    def fake_request_json(url: str, **kwargs):
        _ = kwargs
        if url.endswith("/readyz"):
            return 200, {"status": "ready"}
        raise AssertionError(f"unexpected direct JSON request: {url}")

    def fake_wait_for_success(**kwargs):
        _ = kwargs
        return next(wait_payloads)

    def unexpected_request_bytes(*args, **kwargs):
        _ = (args, kwargs)
        raise AssertionError("voice check should not run in text-only smoke")

    def unexpected_request_multipart_bytes(*args, **kwargs):
        _ = (args, kwargs)
        raise AssertionError("stt check should not run in text-only smoke")

    monkeypatch.setattr(module, "_request_json", fake_request_json)
    monkeypatch.setattr(module, "_wait_for_success", fake_wait_for_success)
    monkeypatch.setattr(module, "_request_bytes", unexpected_request_bytes)
    monkeypatch.setattr(
        module, "_request_multipart_bytes", unexpected_request_multipart_bytes
    )

    assert module.main() == 0


def test_main_checks_voice_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_smoke_module()
    monkeypatch.setenv("SMOKE_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("SMOKE_INTERNAL_OPENAI_API_KEY", "smoke-key")
    monkeypatch.setenv("SMOKE_CHECK_VOICE", "true")
    monkeypatch.delenv("SMOKE_CHECK_STT", raising=False)
    monkeypatch.setenv("SMOKE_TTS_VOICE", "assistant-fast")

    wait_payloads = iter(
        [
            (
                200,
                {
                    "data": [
                        {"id": "assistant-v1"},
                        {"id": "assistant-fast"},
                    ]
                },
            ),
            _discovery_payload(),
            (
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "ok",
                            }
                        }
                    ]
                },
            ),
        ]
    )
    byte_calls: list[dict[str, object]] = []

    def fake_request_json(url: str, **kwargs):
        _ = kwargs
        if url.endswith("/readyz"):
            return 200, {"status": "ready"}
        raise AssertionError(f"unexpected direct JSON request: {url}")

    def fake_wait_for_success(**kwargs):
        _ = kwargs
        return next(wait_payloads)

    def fake_request_bytes(url: str, **kwargs):
        byte_calls.append({"url": url, "kwargs": kwargs})
        return 200, b"RIFFfakeWAVEpayload", "audio/wav"

    monkeypatch.setattr(module, "_request_json", fake_request_json)
    monkeypatch.setattr(module, "_wait_for_success", fake_wait_for_success)
    monkeypatch.setattr(module, "_request_bytes", fake_request_bytes)

    assert module.main() == 0
    assert byte_calls == [
        {
            "url": "http://127.0.0.1:18080/v1/audio/speech",
            "kwargs": {
                "headers": {"Authorization": "Bearer smoke-key"},
                "body": {
                    "model": "tts-1",
                    "input": "Скажи привет.",
                    "voice": "assistant-fast",
                },
            },
        }
    ]


def test_main_retries_voice_until_it_stabilizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_smoke_module()
    monkeypatch.setenv("SMOKE_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("SMOKE_INTERNAL_OPENAI_API_KEY", "smoke-key")
    monkeypatch.setenv("SMOKE_CHECK_VOICE", "true")
    monkeypatch.delenv("SMOKE_CHECK_STT", raising=False)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    wait_payloads = iter(
        [
            (
                200,
                {
                    "data": [
                        {"id": "assistant-v1"},
                        {"id": "assistant-fast"},
                    ]
                },
            ),
            _discovery_payload(),
            (
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "ok",
                            }
                        }
                    ]
                },
            ),
        ]
    )
    request_attempts = {"count": 0}

    def fake_request_json(url: str, **kwargs):
        _ = kwargs
        if url.endswith("/readyz"):
            return 200, {"status": "ready"}
        raise AssertionError(f"unexpected direct JSON request: {url}")

    def fake_wait_for_success(**kwargs):
        _ = kwargs
        return next(wait_payloads)

    def fake_request_bytes(url: str, **kwargs):
        _ = (url, kwargs)
        request_attempts["count"] += 1
        if request_attempts["count"] == 1:
            return 503, b'{"error":{"type":"dependency_unavailable"}}', "application/json"
        return 200, b"RIFFfakeWAVEpayload", "audio/wav"

    monkeypatch.setattr(module, "_request_json", fake_request_json)
    monkeypatch.setattr(module, "_wait_for_success", fake_wait_for_success)
    monkeypatch.setattr(module, "_request_bytes", fake_request_bytes)

    assert module.main() == 0
    assert request_attempts["count"] == 2


def test_main_checks_stt_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_smoke_module()
    monkeypatch.setenv("SMOKE_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("SMOKE_INTERNAL_OPENAI_API_KEY", "smoke-key")
    monkeypatch.delenv("SMOKE_CHECK_VOICE", raising=False)
    monkeypatch.setenv("SMOKE_CHECK_STT", "true")

    wait_payloads = iter(
        [
            (
                200,
                {
                    "data": [
                        {"id": "assistant-v1"},
                        {"id": "assistant-fast"},
                    ]
                },
            ),
            _discovery_payload(),
            (
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "ok",
                            }
                        }
                    ]
                },
            ),
        ]
    )
    multipart_calls: list[dict[str, object]] = []

    def fake_request_json(url: str, **kwargs):
        _ = kwargs
        if url.endswith("/readyz"):
            return 200, {"status": "ready"}
        raise AssertionError(f"unexpected direct JSON request: {url}")

    def fake_wait_for_success(**kwargs):
        _ = kwargs
        return next(wait_payloads)

    def unexpected_request_bytes(*args, **kwargs):
        _ = (args, kwargs)
        raise AssertionError("voice synthesis check should not run")

    def fake_request_multipart_bytes(url: str, **kwargs):
        multipart_calls.append({"url": url, "kwargs": kwargs})
        return 200, b'{"text":"Hello."}', "application/json"

    monkeypatch.setattr(module, "_request_json", fake_request_json)
    monkeypatch.setattr(module, "_wait_for_success", fake_wait_for_success)
    monkeypatch.setattr(module, "_request_bytes", unexpected_request_bytes)
    monkeypatch.setattr(
        module, "_request_multipart_bytes", fake_request_multipart_bytes
    )

    assert module.main() == 0
    assert len(multipart_calls) == 1
    call = multipart_calls[0]
    assert call["url"] == "http://127.0.0.1:18080/v1/audio/transcriptions"
    assert call["kwargs"]["headers"] == {"Authorization": "Bearer smoke-key"}
    assert call["kwargs"]["fields"] == {"model": "whisper-1"}
    assert call["kwargs"]["file_field_name"] == "file"
    assert call["kwargs"]["file_name"] == "smoke-hello.wav"
    assert call["kwargs"]["file_content_type"] == "audio/wav"
    file_bytes = call["kwargs"]["file_bytes"]
    assert isinstance(file_bytes, bytes)
    assert file_bytes.startswith(b"RIFF")
    assert len(file_bytes) > 16000


def test_main_retries_stt_until_it_stabilizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_smoke_module()
    monkeypatch.setenv("SMOKE_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("SMOKE_INTERNAL_OPENAI_API_KEY", "smoke-key")
    monkeypatch.delenv("SMOKE_CHECK_VOICE", raising=False)
    monkeypatch.setenv("SMOKE_CHECK_STT", "true")
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    wait_payloads = iter(
        [
            (
                200,
                {
                    "data": [
                        {"id": "assistant-v1"},
                        {"id": "assistant-fast"},
                    ]
                },
            ),
            _discovery_payload(),
            (
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "ok",
                            }
                        }
                    ]
                },
            ),
        ]
    )
    request_attempts = {"count": 0}

    def fake_request_json(url: str, **kwargs):
        _ = kwargs
        if url.endswith("/readyz"):
            return 200, {"status": "ready"}
        raise AssertionError(f"unexpected direct JSON request: {url}")

    def fake_wait_for_success(**kwargs):
        _ = kwargs
        return next(wait_payloads)

    def fake_request_multipart_bytes(url: str, **kwargs):
        _ = (url, kwargs)
        request_attempts["count"] += 1
        if request_attempts["count"] == 1:
            return 503, b'{"error":{"type":"dependency_unavailable"}}', "application/json"
        return 200, b'{"text":"Hello."}', "application/json"

    monkeypatch.setattr(module, "_request_json", fake_request_json)
    monkeypatch.setattr(module, "_wait_for_success", fake_wait_for_success)
    monkeypatch.setattr(module, "_request_multipart_bytes", fake_request_multipart_bytes)

    assert module.main() == 0
    assert request_attempts["count"] == 2


def test_main_rejects_missing_public_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_smoke_module()
    monkeypatch.setenv("SMOKE_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("SMOKE_INTERNAL_OPENAI_API_KEY", "smoke-key")
    monkeypatch.delenv("SMOKE_CHECK_VOICE", raising=False)

    def fake_request_json(url: str, **kwargs):
        _ = kwargs
        if url.endswith("/readyz"):
            return 200, {"status": "ready"}
        raise AssertionError(f"unexpected direct JSON request: {url}")

    def fake_wait_for_success(**kwargs):
        _ = kwargs
        return 200, {"data": [{"id": "assistant-fast"}]}

    monkeypatch.setattr(module, "_request_json", fake_request_json)
    monkeypatch.setattr(module, "_wait_for_success", fake_wait_for_success)

    with pytest.raises(SystemExit, match="Required public model IDs missing"):
        module.main()


def test_main_rejects_invalid_capability_discovery_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_smoke_module()
    monkeypatch.setenv("SMOKE_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("SMOKE_INTERNAL_OPENAI_API_KEY", "smoke-key")
    monkeypatch.delenv("SMOKE_CHECK_VOICE", raising=False)

    wait_payloads = iter(
        [
            (
                200,
                {
                    "data": [
                        {"id": "assistant-v1"},
                        {"id": "assistant-fast"},
                    ]
                },
            ),
            (
                200,
                {
                    "capabilities": [{"id": "voice", "label": "Voice conversation"}],
                    "commands": ["/help"],
                    "help_text": "Voice conversation is connected.",
                    "status_text": "Voice conversation: connected",
                },
            ),
        ]
    )

    def fake_request_json(url: str, **kwargs):
        _ = kwargs
        if url.endswith("/readyz"):
            return 200, {"status": "ready"}
        raise AssertionError(f"unexpected direct JSON request: {url}")

    def fake_wait_for_success(**kwargs):
        _ = kwargs
        return next(wait_payloads)

    monkeypatch.setattr(module, "_request_json", fake_request_json)
    monkeypatch.setattr(module, "_wait_for_success", fake_wait_for_success)

    with pytest.raises(SystemExit, match="Capability discovery payload was invalid"):
        module.main()
