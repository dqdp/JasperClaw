from __future__ import annotations

import sys
from types import ModuleType

import pytest

from app.engines.base import SttEngineRequestError
from app.engines.faster_whisper import FasterWhisperEngine


def test_faster_whisper_preserves_request_local_transcription_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = ModuleType("faster_whisper")

    class _FakeModel:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def transcribe(self, path: str):
            _ = path
            raise RuntimeError("decode failed")

    fake_module.WhisperModel = _FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    engine = FasterWhisperEngine(
        model_name="base",
        device="cpu",
        compute_type="int8",
    )

    with pytest.raises(SttEngineRequestError):
        engine.transcribe(
            audio_bytes=b"RIFFfakeWAVE",
            filename="clip.wav",
            content_type="audio/wav",
        )
