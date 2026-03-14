from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT = REPO_ROOT / "infra" / "scripts" / "smoke.sh"


def _write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _env_file(
    path: Path,
    *,
    voice_enabled: str,
    default_voice: str,
) -> Path:
    path.write_text(
        "\n".join(
            [
                "INTERNAL_OPENAI_API_KEY=test-key",
                "DOMAIN=localhost",
                f"VOICE_ENABLED={voice_enabled}",
                f"TTS_DEFAULT_VOICE={default_voice}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _docker_stub(path: Path, log_path: Path) -> Path:
    _write_file(
        path,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'printf "%s\\n" "$*" >> "{log_path}"',
                'case "$*" in',
                '  *" exec -T agent-api python -"*)',
                "    cat >/dev/null || true",
                "    exit 0",
                "    ;;",
                '  *" exec -T open-webui env"*)',
                "    cat <<'EOF'",
                "ENABLE_OPENAI_API=True",
                "ENABLE_OLLAMA_API=False",
                "OPENAI_API_BASE_URL=http://agent-api:8080/v1",
                "OPENAI_API_KEY=test-key",
                "AUDIO_STT_ENGINE=openai",
                "AUDIO_STT_MODEL=whisper-1",
                "AUDIO_STT_OPENAI_API_BASE_URL=http://agent-api:8080/v1",
                "AUDIO_STT_OPENAI_API_KEY=test-key",
                "AUDIO_TTS_ENGINE=openai",
                "AUDIO_TTS_MODEL=tts-1",
                "AUDIO_TTS_VOICE=assistant-fast",
                "AUDIO_TTS_OPENAI_API_BASE_URL=http://agent-api:8080/v1",
                "AUDIO_TTS_OPENAI_API_KEY=test-key",
                "EOF",
                "    exit 0",
                "    ;;",
                "esac",
                "exit 0",
                "",
            ]
        ),
    )
    return path


def _run_smoke(
    tmp_path: Path,
    *,
    voice_enabled: str,
    default_voice: str,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    docker_log = tmp_path / "docker.log"
    env_file = _env_file(
        tmp_path / "smoke.env",
        voice_enabled=voice_enabled,
        default_voice=default_voice,
    )
    docker_stub = _docker_stub(tmp_path / "docker-stub.sh", docker_log)

    env = os.environ.copy()
    env.update(
        {
            "ROOT_ENV_FILE": str(env_file),
            "DOCKER_BIN": str(docker_stub),
            "PYTHON_BIN": sys.executable,
            "SMOKE_SKIP_DOMAIN_CHECK": "true",
        }
    )

    result = subprocess.run(
        ["bash", str(SMOKE_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, docker_log


def test_smoke_runs_open_webui_wiring_check_for_voice_profile(tmp_path: Path) -> None:
    result, docker_log = _run_smoke(
        tmp_path,
        voice_enabled="true",
        default_voice="assistant-fast",
    )

    assert result.returncode == 0, result.stderr
    docker_calls = docker_log.read_text(encoding="utf-8").splitlines()
    assert any("agent-api python -" in call for call in docker_calls)
    assert any("open-webui env" in call for call in docker_calls)


def test_smoke_skips_open_webui_wiring_check_for_text_profile(tmp_path: Path) -> None:
    result, docker_log = _run_smoke(
        tmp_path,
        voice_enabled="false",
        default_voice="assistant-default",
    )

    assert result.returncode == 0, result.stderr
    docker_calls = docker_log.read_text(encoding="utf-8").splitlines()
    assert any("agent-api python -" in call for call in docker_calls)
    assert not any("open-webui env" in call for call in docker_calls)


def test_smoke_runs_telegram_smoke_only_when_inputs_are_configured(
    tmp_path: Path,
) -> None:
    docker_log = tmp_path / "docker.log"
    python_log = tmp_path / "python.log"
    env_file = _env_file(
        tmp_path / "smoke.env",
        voice_enabled="false",
        default_voice="assistant-default",
    )
    docker_stub = _docker_stub(tmp_path / "docker-stub.sh", docker_log)
    python_stub = tmp_path / "python-stub.sh"
    _write_file(
        python_stub,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'printf "%s\\n" "$*" >> "{python_log}"',
                "exit 0",
                "",
            ]
        ),
    )

    env = os.environ.copy()
    env.update(
        {
            "ROOT_ENV_FILE": str(env_file),
            "DOCKER_BIN": str(docker_stub),
            "PYTHON_BIN": str(python_stub),
            "SMOKE_SKIP_DOMAIN_CHECK": "true",
            "TELEGRAM_SMOKE_BASE_URL": "http://127.0.0.1:18081",
            "TELEGRAM_FAKE_BASE_URL": "http://127.0.0.1:18082",
            "TELEGRAM_SMOKE_WEBHOOK_SECRET_TOKEN": "test-secret",
            "TELEGRAM_SMOKE_BOT_TOKEN": "test-bot",
            "TELEGRAM_SMOKE_ALERT_AUTH_TOKEN": "test-alert-auth",
            "TELEGRAM_SMOKE_ALERT_BOT_TOKEN": "test-alert-bot",
        }
    )

    result = subprocess.run(
        ["bash", str(SMOKE_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    python_calls = python_log.read_text(encoding="utf-8").splitlines()
    assert python_calls == ["infra/scripts/smoke-telegram-ingress.py"]
