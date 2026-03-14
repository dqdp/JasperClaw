from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

from app.engines.base import (
    SttEngine,
    SttEngineBadResponseError,
    SttEngineUnavailableError,
)


class FasterWhisperEngine(SttEngine):
    def __init__(
        self,
        *,
        model_name: str,
        device: str,
        compute_type: str,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._model = None
        self._model_lock = Lock()

    def _load_model(self):
        with self._model_lock:
            if self._model is not None:
                return self._model

            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise SttEngineUnavailableError(
                    "faster-whisper dependency is not installed"
                ) from exc

            try:
                self._model = WhisperModel(
                    self._model_name,
                    device=self._device,
                    compute_type=self._compute_type,
                )
            except Exception as exc:
                raise SttEngineUnavailableError(
                    "Failed to initialize faster-whisper runtime"
                ) from exc

            return self._model

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        _ = content_type
        model = self._load_model()
        temp_path: str | None = None

        try:
            suffix = Path(filename).suffix or ".bin"
            with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(audio_bytes)
                temp_path = temp_file.name
            segments, _ = model.transcribe(temp_path)
        except SttEngineUnavailableError:
            raise
        except Exception as exc:
            raise SttEngineUnavailableError("faster-whisper transcription failed") from exc
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

        transcript_parts: list[str] = []
        try:
            for segment in segments:
                text = getattr(segment, "text", None)
                if not isinstance(text, str):
                    raise SttEngineBadResponseError(
                        "faster-whisper segment did not expose string text"
                    )
                normalized = text.strip()
                if normalized:
                    transcript_parts.append(normalized)
        except SttEngineBadResponseError:
            raise
        except Exception as exc:
            raise SttEngineBadResponseError(
                "Failed to normalize faster-whisper transcript"
            ) from exc

        return " ".join(transcript_parts).strip()
