from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SCRIPT = REPO_ROOT / "infra" / "scripts" / "deploy.sh"


def _write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _base_env_file(tmp_path: Path, *, voice_enabled: str, compose_profiles: str) -> Path:
    env_file = tmp_path / "deploy.env"
    env_file.write_text(
        "\n".join(
            [
                "APP_VERSION=dev",
                "GHCR_OWNER=local",
                "POSTGRES_PASSWORD=change-me",
                "INTERNAL_OPENAI_API_KEY=test-key",
                "WEBUI_SECRET_KEY=test-secret",
                f"VOICE_ENABLED={voice_enabled}",
                f"COMPOSE_PROFILES={compose_profiles}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return env_file


def _stub_script(path: Path, log_path: Path, label: str) -> Path:
    _write_file(
        path,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'printf "{label} ROOT_ENV_FILE=%s COMPOSE_BASE_FILE=%s COMPOSE_OVERRIDE_FILE=%s\\n" '
                '"${ROOT_ENV_FILE:-}" "${COMPOSE_BASE_FILE:-}" "${COMPOSE_OVERRIDE_FILE:-}" '
                f'>> "{log_path}"',
                "",
            ]
        ),
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
                "",
            ]
        ),
    )
    return path


def _run_deploy(
    tmp_path: Path,
    *,
    voice_enabled: str,
    compose_profiles: str,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    docker_log = tmp_path / "docker.log"
    script_log = tmp_path / "scripts.log"
    env_file = _base_env_file(
        tmp_path,
        voice_enabled=voice_enabled,
        compose_profiles=compose_profiles,
    )
    docker_stub = _docker_stub(tmp_path / "docker-stub.sh", docker_log)
    ensure_stub = _stub_script(tmp_path / "ensure.sh", script_log, "ensure")
    smoke_stub = _stub_script(tmp_path / "smoke.sh", script_log, "smoke")

    env = os.environ.copy()
    env.update(
        {
            "ROOT_ENV_FILE": str(env_file),
            "DOCKER_BIN": str(docker_stub),
            "ENSURE_OLLAMA_SCRIPT": str(ensure_stub),
            "SMOKE_SCRIPT": str(smoke_stub),
        }
    )

    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, docker_log, script_log


def test_deploy_rejects_voice_contract_mismatch(tmp_path: Path) -> None:
    result, docker_log, script_log = _run_deploy(
        tmp_path,
        voice_enabled="true",
        compose_profiles="",
    )

    assert result.returncode != 0
    assert "Invalid rollout contract" in result.stderr
    assert not docker_log.exists()
    assert not script_log.exists()


def test_deploy_runs_text_only_service_set(tmp_path: Path) -> None:
    result, docker_log, script_log = _run_deploy(
        tmp_path,
        voice_enabled="false",
        compose_profiles="",
    )

    assert result.returncode == 0, result.stderr
    assert "Deploy profile: text-only" in result.stdout
    assert "Deploy services: agent-api telegram-ingress open-webui caddy" in result.stdout
    docker_calls = docker_log.read_text(encoding="utf-8").splitlines()
    assert docker_calls[-1].endswith(
        "up -d --remove-orphans agent-api telegram-ingress open-webui caddy"
    )
    assert "stt-service" not in docker_calls[-1]
    assert "tts-service" not in docker_calls[-1]

    script_calls = script_log.read_text(encoding="utf-8").splitlines()
    assert len(script_calls) == 2
    assert script_calls[0].startswith("ensure ROOT_ENV_FILE=")
    assert script_calls[1].startswith("smoke ROOT_ENV_FILE=")


def test_deploy_runs_voice_enabled_service_set(tmp_path: Path) -> None:
    result, docker_log, _script_log = _run_deploy(
        tmp_path,
        voice_enabled="true",
        compose_profiles="voice",
    )

    assert result.returncode == 0, result.stderr
    assert "Deploy profile: voice-enabled-cpu" in result.stdout
    assert (
        "Deploy services: agent-api telegram-ingress open-webui caddy stt-service tts-service"
        in result.stdout
    )
    docker_calls = docker_log.read_text(encoding="utf-8").splitlines()
    assert docker_calls[-1].endswith(
        "up -d --remove-orphans agent-api telegram-ingress open-webui caddy stt-service tts-service"
    )
