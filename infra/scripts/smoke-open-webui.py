#!/usr/bin/env python3
from __future__ import annotations

import os
import sys


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _resolve_api_key() -> str:
    value = (
        os.getenv("SMOKE_INTERNAL_OPENAI_API_KEY", "").strip()
        or os.getenv("INTERNAL_OPENAI_API_KEY", "").strip()
    )
    if not value:
        raise SystemExit(
            "Missing required environment variable: SMOKE_INTERNAL_OPENAI_API_KEY"
        )
    return value


def _load_env_dump() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in sys.stdin.read().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _require_exact(values: dict[str, str], key: str, expected: str) -> None:
    actual = values.get(key)
    if actual != expected:
        raise SystemExit(
            f"Open WebUI voice wiring mismatch for {key}: expected {expected!r}, got {actual!r}"
        )


def main() -> int:
    values = _load_env_dump()
    expected_base_url = os.getenv("SMOKE_OPENAI_API_BASE_URL", "http://agent-api:8080/v1")
    expected_voice = os.getenv("SMOKE_TTS_VOICE", "assistant-default").strip()
    expected_api_key = _resolve_api_key()

    _require_exact(values, "ENABLE_OPENAI_API", "True")
    _require_exact(values, "ENABLE_OLLAMA_API", "False")
    _require_exact(values, "OPENAI_API_BASE_URL", expected_base_url)
    _require_exact(values, "OPENAI_API_KEY", expected_api_key)
    _require_exact(values, "AUDIO_STT_ENGINE", "openai")
    _require_exact(values, "AUDIO_STT_MODEL", "whisper-1")
    _require_exact(values, "AUDIO_STT_OPENAI_API_BASE_URL", expected_base_url)
    _require_exact(values, "AUDIO_STT_OPENAI_API_KEY", expected_api_key)
    _require_exact(values, "AUDIO_TTS_ENGINE", "openai")
    _require_exact(values, "AUDIO_TTS_MODEL", "tts-1")
    _require_exact(values, "AUDIO_TTS_VOICE", expected_voice)
    _require_exact(values, "AUDIO_TTS_OPENAI_API_BASE_URL", expected_base_url)
    _require_exact(values, "AUDIO_TTS_OPENAI_API_KEY", expected_api_key)

    print("Open WebUI voice wiring checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
