from __future__ import annotations

import re
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "infra" / "compose" / "compose.yml"
COMPOSE_CI_FILE = REPO_ROOT / "infra" / "compose" / "compose.ci.yml"
APP_ENV_FILE = REPO_ROOT / "infra" / "env" / "app.example.env"
TELEGRAM_ENV_FILE = REPO_ROOT / "infra" / "env" / "telegram.example.env"
VOICES_FILE = REPO_ROOT / "services" / "tts-service" / "app" / "voices.toml"


def test_open_webui_default_tts_voice_uses_registered_default_voice() -> None:
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    match = re.search(
        r"AUDIO_TTS_VOICE:\s*\$\{TTS_DEFAULT_VOICE:-([^}]+)\}",
        compose_text,
    )
    assert match is not None, "compose.yml must interpolate TTS_DEFAULT_VOICE"

    default_voice = match.group(1)
    voices = tomllib.loads(VOICES_FILE.read_text(encoding="utf-8"))

    assert default_voice == "assistant-default"
    assert default_voice in voices["voices"]


def test_app_example_env_enables_default_voice_startup() -> None:
    env_text = APP_ENV_FILE.read_text(encoding="utf-8")

    assert "VOICE_ENABLED=true" in env_text
    assert "STT_BASE_URL=http://stt-service:8080" in env_text
    assert "TTS_BASE_URL=http://tts-service:8080" in env_text
    assert "SPOTIFY_DEMO_ENABLED=true" in env_text
    assert "DEMO_HOUSEHOLD_CONFIG_PATH=/app/config/household.demo.toml" in env_text


def test_compose_voice_services_are_no_longer_gated_by_special_profile() -> None:
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert 'profiles: ["voice"]' not in compose_text


def test_compose_mounts_demo_household_config_for_default_baseline_services() -> None:
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "../config/household.demo.toml:/app/config/household.demo.toml:ro" in compose_text
    assert compose_text.count("/app/config/household.demo.toml:ro") >= 2


def test_telegram_example_env_matches_v1_command_surface() -> None:
    env_text = TELEGRAM_ENV_FILE.read_text(encoding="utf-8")

    assert "TELEGRAM_ALLOWED_COMMANDS=/help,/status,/ask,/aliases,/send" in env_text
    assert "DEMO_HOUSEHOLD_CONFIG_PATH=/app/config/household.demo.toml" in env_text


def test_ci_compose_mounts_demo_household_config_for_baseline_services() -> None:
    compose_text = COMPOSE_CI_FILE.read_text(encoding="utf-8")

    assert "../config/household.ci-smoke.toml:/app/config/household.ci-smoke.toml:ro" in compose_text
    assert compose_text.count("/app/config/household.ci-smoke.toml:ro") >= 2
