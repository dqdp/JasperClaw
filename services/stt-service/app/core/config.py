from dataclasses import dataclass
from functools import lru_cache
import os


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class Settings:
    voice_enabled: bool
    stt_model: str
    stt_device: str
    stt_compute_type: str
    stt_max_file_bytes: int
    stt_max_concurrency: int


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in _TRUE_VALUES


@lru_cache
def get_settings() -> Settings:
    model = os.getenv("STT_MODEL")
    device = os.getenv("STT_DEVICE")
    compute_type = os.getenv("STT_COMPUTE_TYPE")
    return Settings(
        voice_enabled=_get_bool_env("VOICE_ENABLED", default=False),
        stt_model="large-v3" if model is None else model.strip(),
        stt_device="cpu" if device is None else device.strip(),
        stt_compute_type="int8" if compute_type is None else compute_type.strip(),
        stt_max_file_bytes=max(int(os.getenv("STT_MAX_FILE_BYTES", "26214400")), 1),
        stt_max_concurrency=max(int(os.getenv("STT_MAX_CONCURRENCY", "1")), 1),
    )
