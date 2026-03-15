from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
VOICE_ENV_FILE = REPO_ROOT / "infra" / "env" / "app.ci-voice-smoke.example.env"


def _extract_job_body(job_name: str) -> str:
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    target = f"  {job_name}:"
    try:
        start_index = lines.index(target)
    except ValueError as exc:
        raise AssertionError(f"Workflow job {job_name!r} is missing") from exc

    body: list[str] = []
    for line in lines[start_index + 1 :]:
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            break
        body.append(line)
    return "\n".join(body)


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_voice_smoke_env_enables_supported_voice_profile() -> None:
    values = _parse_env_file(VOICE_ENV_FILE)

    assert values["VOICE_ENABLED"] == "true"
    assert values["SPOTIFY_DEMO_ENABLED"] == "true"
    assert values["STT_MODEL"] == "base"
    assert values["STT_DEVICE"] == "cpu"
    assert values["STT_COMPUTE_TYPE"] == "int8"
    assert values["STT_PREWARM_ON_STARTUP"] == "true"
    assert values["TTS_DEFAULT_VOICE"] == "assistant-default"


def test_ci_declares_mandatory_voice_smoke_job() -> None:
    job_body = _extract_job_body("smoke-voice")

    assert "cp infra/env/app.ci-voice-smoke.example.env infra/env/app.env" in job_body
    assert "cp infra/env/telegram.ci-smoke.example.env infra/env/telegram.env" in job_body
    assert "docker compose --profile voice" in job_body
    assert (
        "build agent-api ollama-fake stt-service tts-service telegram-ingress telegram-fake"
        in job_body
    )
    assert "up -d postgres ollama-fake telegram-fake" in job_body
    assert "run --rm --no-deps agent-api python -m app.cli migrate" in job_body
    assert "up -d --no-deps stt-service tts-service agent-api open-webui telegram-ingress" in job_body
    assert 'SMOKE_SKIP_DOMAIN_CHECK: "true"' in job_body
    assert 'SMOKE_CHECK_VOICE: "true"' in job_body
    assert 'SMOKE_CHECK_STT: "true"' in job_body
    assert 'TELEGRAM_SMOKE_BASE_URL: "http://127.0.0.1:18081"' in job_body
    assert 'TELEGRAM_FAKE_BASE_URL: "http://127.0.0.1:18082"' in job_body
    assert 'TELEGRAM_SMOKE_WEBHOOK_PATH: "/telegram/webhook"' in job_body
    assert 'TELEGRAM_SMOKE_WEBHOOK_SECRET_TOKEN: "ci-webhook-secret"' in job_body
    assert 'TELEGRAM_SMOKE_BOT_TOKEN: "ci-telegram-bot"' in job_body
    assert 'TELEGRAM_SMOKE_ALERT_AUTH_TOKEN: "ci-alert-secret"' in job_body
    assert 'TELEGRAM_SMOKE_ALERT_BOT_TOKEN: "ci-telegram-alert-bot"' in job_body
    assert 'TELEGRAM_SMOKE_ALERT_CHAT_IDS: "9001"' in job_body
    assert 'TELEGRAM_SMOKE_ALERT_WARNING_CHAT_IDS: "9002"' in job_body
    assert 'TELEGRAM_SMOKE_ALERT_CRITICAL_CHAT_IDS: "9003"' in job_body
    assert "bash infra/scripts/smoke.sh" in job_body
    assert (
        "logs --no-color postgres ollama-fake stt-service tts-service agent-api open-webui "
        "telegram-ingress telegram-fake" in job_body
    )
