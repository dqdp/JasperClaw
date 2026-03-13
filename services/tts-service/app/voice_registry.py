from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class VoiceConfig:
    engine: str
    model: str


def load_voice_registry(path: Path) -> dict[str, VoiceConfig]:
    data = tomllib.loads(path.read_text())
    voices = data.get("voices")
    if not isinstance(voices, dict):
        raise RuntimeError("Voice registry is invalid")

    registry: dict[str, VoiceConfig] = {}
    for voice_id, entry in voices.items():
        if not isinstance(voice_id, str) or not isinstance(entry, dict):
            raise RuntimeError("Voice registry is invalid")
        engine = entry.get("engine")
        model = entry.get("model")
        if not isinstance(engine, str) or not isinstance(model, str):
            raise RuntimeError("Voice registry is invalid")
        registry[voice_id] = VoiceConfig(engine=engine, model=model)
    return registry
