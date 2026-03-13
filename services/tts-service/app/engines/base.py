from typing import Protocol


class TtsEngine(Protocol):
    def synthesize(self, *, text: str, voice_id: str) -> bytes: ...


class TtsEngineTimeoutError(RuntimeError):
    """Raised when the TTS runtime exceeds the configured timeout."""


class TtsEngineUnavailableError(RuntimeError):
    """Raised when the TTS runtime is unavailable."""


class TtsEngineBadResponseError(RuntimeError):
    """Raised when the TTS runtime returns an invalid result."""
