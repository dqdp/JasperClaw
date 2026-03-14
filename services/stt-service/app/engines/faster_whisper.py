from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

from app.engines.base import (
    SttEngine,
    SttEngineBadResponseError,
    SttEngineRequestError,
    SttEngineUnavailableError,
)

_REQUEST_LOCAL_EXCEPTION_NAMES = frozenset(
    {
        "DecoderNotFoundError",
        "DemuxerNotFoundError",
        "InvalidDataError",
    }
)
_REQUEST_LOCAL_ERROR_PATTERNS = (
    "could not decode",
    "decode failed",
    "error opening input",
    "failed to open input",
    "invalid data found when processing input",
    "moov atom not found",
    "unsupported codec",
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

    def validate_runtime(self) -> None:
        _ = self._load_model()

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
            if _is_request_local_transcription_error(exc):
                raise SttEngineRequestError(
                    "faster-whisper transcription failed"
                ) from exc
            raise
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


def _is_request_local_transcription_error(exc: Exception) -> bool:
    for cls in type(exc).__mro__:
        if cls.__name__ in _REQUEST_LOCAL_EXCEPTION_NAMES:
            return True

    normalized = " ".join(str(exc).casefold().split())
    return any(pattern in normalized for pattern in _REQUEST_LOCAL_ERROR_PATTERNS)
