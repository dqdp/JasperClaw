from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from app.core.config import Settings
from app.voice_registry import VoiceConfig


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    status: str
    checks: dict[str, str]

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"


class ReadinessService:
    def __init__(
        self,
        *,
        settings: Settings,
        voice_registry: dict[str, VoiceConfig],
    ) -> None:
        self._settings = settings
        self._voice_registry = voice_registry

    def check(self) -> ReadinessResult:
        checks = {
            "voice_enabled": self._check_voice_enabled(),
            "registry": self._check_registry(),
            "models": self._check_models(),
            "runtime": self._check_runtime(),
        }
        status = (
            "ready" if all(value == "ok" for value in checks.values()) else "not_ready"
        )
        return ReadinessResult(status=status, checks=checks)

    def _check_voice_enabled(self) -> str:
        return "ok" if self._settings.voice_enabled else "fail"

    def _check_registry(self) -> str:
        if not self._voice_registry:
            return "fail"
        if self._settings.tts_default_voice not in self._voice_registry:
            return "fail"
        if any(
            voice.engine != self._settings.tts_engine
            for voice in self._voice_registry.values()
        ):
            return "fail"
        return "ok"

    def _check_models(self) -> str:
        if self._settings.tts_engine != "piper":
            return "fail"

        for voice in self._voice_registry.values():
            model_path = self._resolve_model_path(voice.model)
            config_path = Path(f"{model_path}.json")
            if (not model_path.is_file()) or (not config_path.is_file()):
                return "fail"
        return "ok"

    def _check_runtime(self) -> str:
        if self._settings.tts_engine != "piper":
            return "fail"

        try:
            completed = subprocess.run(
                [self._settings.piper_binary_path, "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=min(max(self._settings.piper_timeout_seconds, 0.1), 5.0),
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "fail"

        return "ok" if completed.returncode == 0 else "fail"

    def _resolve_model_path(self, model: str) -> Path:
        candidate = Path(model)
        model_dir = (
            Path(self._settings.piper_model_dir)
            if self._settings.piper_model_dir
            else Path()
        )
        if candidate.suffix == ".onnx":
            return candidate if candidate.is_absolute() else model_dir / candidate
        return model_dir / f"{model}.onnx"
