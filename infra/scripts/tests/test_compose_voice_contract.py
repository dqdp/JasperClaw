from __future__ import annotations

import re
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "infra" / "compose" / "compose.yml"
COMPOSE_CI_FILE = REPO_ROOT / "infra" / "compose" / "compose.ci.yml"
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


def test_ci_compose_mounts_demo_household_config_for_baseline_services() -> None:
    compose_text = COMPOSE_CI_FILE.read_text(encoding="utf-8")

    assert "../config/household.demo.toml:/app/config/household.demo.toml:ro" in compose_text
    assert compose_text.count("/app/config/household.demo.toml:ro") >= 2
