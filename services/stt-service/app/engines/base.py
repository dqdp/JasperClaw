from typing import Protocol


class SttEngine(Protocol):
    def validate_runtime(self) -> None: ...

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> str: ...


class SttEngineUnavailableError(RuntimeError):
    """Raised when the STT runtime cannot accept work."""


class SttEngineRequestError(RuntimeError):
    """Raised when one transcription request fails without losing the runtime."""


class SttEngineBadResponseError(RuntimeError):
    """Raised when the STT runtime yields an invalid transcript payload."""
