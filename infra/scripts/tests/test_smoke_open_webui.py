from __future__ import annotations

import io
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _load_smoke_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "smoke-open-webui.py"
    spec = spec_from_file_location("smoke_open_webui", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env_dump(*, voice: str = "assistant-default", api_key: str = "smoke-key") -> str:
    return "\n".join(
        [
            "ENABLE_OPENAI_API=True",
            "ENABLE_OLLAMA_API=False",
            "OPENAI_API_BASE_URL=http://agent-api:8080/v1",
            f"OPENAI_API_KEY={api_key}",
            "AUDIO_STT_ENGINE=openai",
            "AUDIO_STT_MODEL=whisper-1",
            "AUDIO_STT_OPENAI_API_BASE_URL=http://agent-api:8080/v1",
            f"AUDIO_STT_OPENAI_API_KEY={api_key}",
            "AUDIO_TTS_ENGINE=openai",
            "AUDIO_TTS_MODEL=tts-1",
            f"AUDIO_TTS_VOICE={voice}",
            "AUDIO_TTS_OPENAI_API_BASE_URL=http://agent-api:8080/v1",
            f"AUDIO_TTS_OPENAI_API_KEY={api_key}",
            "",
        ]
    )


def test_main_accepts_expected_voice_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_smoke_module()
    monkeypatch.setenv("SMOKE_INTERNAL_OPENAI_API_KEY", "smoke-key")
    monkeypatch.setenv("SMOKE_TTS_VOICE", "assistant-fast")
    monkeypatch.setattr(sys, "stdin", io.StringIO(_env_dump(voice="assistant-fast")))

    assert module.main() == 0


def test_main_rejects_mismatched_openai_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_smoke_module()
    monkeypatch.setenv("SMOKE_INTERNAL_OPENAI_API_KEY", "smoke-key")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            _env_dump().replace(
                "OPENAI_API_BASE_URL=http://agent-api:8080/v1",
                "OPENAI_API_BASE_URL=http://ollama:11434/v1",
            )
        ),
    )

    with pytest.raises(SystemExit, match="OPENAI_API_BASE_URL"):
        module.main()
