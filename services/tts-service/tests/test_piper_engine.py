from pathlib import Path
import subprocess

import pytest

from app.engines.base import TtsEngineBadResponseError, TtsEngineUnavailableError
from app.engines.piper import PiperTtsEngine
from app.voice_registry import VoiceConfig


def test_piper_engine_reads_generated_wav(monkeypatch, tmp_path: Path) -> None:
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "ru_RU-irina-medium.onnx").write_bytes(b"model")
    (model_dir / "ru_RU-irina-medium.onnx.json").write_text("{}")
    engine = PiperTtsEngine(
        voices={
            "assistant-default": VoiceConfig(
                engine="piper",
                model="ru_RU-irina-medium",
            )
        },
        model_dir=str(model_dir),
        binary_path="piper",
        timeout_seconds=5.0,
    )

    def _fake_run(cmd, **kwargs):
        output_path = Path(cmd[cmd.index("--output_file") + 1])
        output_path.write_bytes(b"RIFFpiperWAVE")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr("app.engines.piper.subprocess.run", _fake_run)

    audio = engine.synthesize(text="hello", voice_id="assistant-default")

    assert audio == b"RIFFpiperWAVE"


def test_piper_engine_rejects_missing_model(tmp_path: Path) -> None:
    engine = PiperTtsEngine(
        voices={
            "assistant-default": VoiceConfig(
                engine="piper",
                model="ru_RU-irina-medium",
            )
        },
        model_dir=str(tmp_path / "models"),
        binary_path="piper",
        timeout_seconds=5.0,
    )

    with pytest.raises(TtsEngineUnavailableError, match="model"):
        engine.synthesize(text="hello", voice_id="assistant-default")


def test_piper_engine_rejects_missing_model_config(tmp_path: Path) -> None:
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "ru_RU-irina-medium.onnx").write_bytes(b"model")
    engine = PiperTtsEngine(
        voices={
            "assistant-default": VoiceConfig(
                engine="piper",
                model="ru_RU-irina-medium",
            )
        },
        model_dir=str(model_dir),
        binary_path="piper",
        timeout_seconds=5.0,
    )

    with pytest.raises(TtsEngineUnavailableError, match="config"):
        engine.synthesize(text="hello", voice_id="assistant-default")


def test_piper_engine_rejects_non_zero_exit(monkeypatch, tmp_path: Path) -> None:
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "ru_RU-irina-medium.onnx").write_bytes(b"model")
    (model_dir / "ru_RU-irina-medium.onnx.json").write_text("{}")
    engine = PiperTtsEngine(
        voices={
            "assistant-default": VoiceConfig(
                engine="piper",
                model="ru_RU-irina-medium",
            )
        },
        model_dir=str(model_dir),
        binary_path="piper",
        timeout_seconds=5.0,
    )

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, b"", b"failed")

    monkeypatch.setattr("app.engines.piper.subprocess.run", _fake_run)

    with pytest.raises(TtsEngineBadResponseError, match="failed"):
        engine.synthesize(text="hello", voice_id="assistant-default")
