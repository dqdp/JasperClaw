from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class Settings:
    voice_enabled: bool
    tts_engine: str
    tts_default_voice: str
    tts_max_input_chars: int
    tts_max_concurrency: int
    tts_voice_registry_path: Path
    piper_model_dir: str
    piper_binary_path: str
    piper_timeout_seconds: float


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in _TRUE_VALUES


@lru_cache
def get_settings() -> Settings:
    default_registry_path = Path(__file__).resolve().parents[1] / "voices.toml"
    return Settings(
        voice_enabled=_get_bool_env("VOICE_ENABLED", default=False),
        tts_engine=(os.getenv("TTS_ENGINE", "piper") or "piper").strip(),
        tts_default_voice=(
            os.getenv("TTS_DEFAULT_VOICE", "assistant-default").strip()
            or "assistant-default"
        ),
        tts_max_input_chars=max(int(os.getenv("TTS_MAX_INPUT_CHARS", "1000")), 1),
        tts_max_concurrency=max(int(os.getenv("TTS_MAX_CONCURRENCY", "1")), 1),
        tts_voice_registry_path=Path(
            os.getenv("TTS_VOICE_REGISTRY_PATH", str(default_registry_path)).strip()
            or str(default_registry_path)
        ),
        piper_model_dir=(os.getenv("PIPER_MODEL_DIR", "") or "").strip(),
        piper_binary_path=(os.getenv("PIPER_BINARY_PATH", "piper") or "piper").strip(),
        piper_timeout_seconds=float(os.getenv("PIPER_TIMEOUT_SECONDS", "30")),
    )
