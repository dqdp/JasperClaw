from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from app.engines.base import (
    TtsEngineBadResponseError,
    TtsEngineTimeoutError,
    TtsEngineUnavailableError,
)
from app.voice_registry import VoiceConfig


class PiperTtsEngine:
    def __init__(
        self,
        *,
        voices: dict[str, VoiceConfig],
        model_dir: str,
        binary_path: str,
        timeout_seconds: float,
    ) -> None:
        self._voices = voices
        self._model_dir = Path(model_dir) if model_dir else Path()
        self._binary_path = binary_path
        self._timeout_seconds = timeout_seconds

    def synthesize(self, *, text: str, voice_id: str) -> bytes:
        voice = self._voices[voice_id]
        model_path = self._resolve_model_path(voice.model)
        config_path = self._resolve_config_path(model_path)
        if not model_path.is_file():
            raise TtsEngineUnavailableError("Piper model is not available")
        if not config_path.is_file():
            raise TtsEngineUnavailableError("Piper model config is not available")

        with tempfile.TemporaryDirectory(prefix="piper-tts-") as temp_dir:
            output_path = Path(temp_dir) / "speech.wav"
            try:
                completed = subprocess.run(
                    [
                        self._binary_path,
                        "--model",
                        str(model_path),
                        "--output_file",
                        str(output_path),
                    ],
                    input=text.encode("utf-8"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self._timeout_seconds,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise TtsEngineUnavailableError(
                    "Piper runtime is not installed"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise TtsEngineTimeoutError("Piper runtime timed out") from exc

            if completed.returncode != 0:
                error_message = completed.stderr.decode(
                    "utf-8", errors="ignore"
                ).strip()
                raise TtsEngineBadResponseError(
                    error_message or "Piper runtime failed to synthesize audio"
                )
            if not output_path.is_file():
                raise TtsEngineBadResponseError("Piper runtime did not produce audio")
            audio = output_path.read_bytes()
            if not audio:
                raise TtsEngineBadResponseError("Piper runtime produced empty audio")
            return audio

    def _resolve_model_path(self, model: str) -> Path:
        candidate = Path(model)
        if candidate.suffix == ".onnx":
            return candidate if candidate.is_absolute() else self._model_dir / candidate
        return self._model_dir / f"{model}.onnx"

    def _resolve_config_path(self, model_path: Path) -> Path:
        return Path(f"{model_path}.json")
