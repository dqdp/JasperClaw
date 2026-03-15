from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
VOICE_ENV_FILE = REPO_ROOT / "infra" / "env" / "app.ci-voice-smoke.example.env"
TELEGRAM_ENV_FILE = REPO_ROOT / "infra" / "env" / "telegram.ci-smoke.example.env"


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
    assert values["DEMO_HOUSEHOLD_CONFIG_PATH"] == "/app/config/household.demo.toml"
    assert values["TELEGRAM_BOT_TOKEN"] == "ci-telegram-bot"
    assert values["TELEGRAM_API_BASE_URL"] == "http://telegram-fake:8080"
    assert values["STT_MODEL"] == "base"
    assert values["STT_DEVICE"] == "cpu"
    assert values["STT_COMPUTE_TYPE"] == "int8"
    assert values["STT_PREWARM_ON_STARTUP"] == "true"
    assert values["TTS_DEFAULT_VOICE"] == "assistant-default"


def test_telegram_smoke_env_enables_demo_household_contract() -> None:
    values = _parse_env_file(TELEGRAM_ENV_FILE)

    assert values["DEMO_HOUSEHOLD_CONFIG_PATH"] == "/app/config/household.demo.toml"
    assert values["TELEGRAM_ALLOWED_COMMANDS"] == "/help,/status,/ask,/aliases,/send"


def test_ci_declares_mandatory_voice_smoke_job() -> None:
    job_body = _extract_job_body("smoke-voice")

    assert "cp infra/env/app.ci-voice-smoke.example.env infra/env/app.env" in job_body
    assert "cp infra/env/telegram.ci-smoke.example.env infra/env/telegram.env" in job_body
    assert "docker compose --env-file infra/env/root.ci-smoke.example.env" in job_body
    assert "--profile voice" not in job_body
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
    assert 'TELEGRAM_SMOKE_CHECK_HOUSEHOLD: "true"' in job_body
    assert 'TELEGRAM_SMOKE_TRUSTED_CHAT_ID: "123456789"' in job_body
    assert 'TELEGRAM_SMOKE_ALIAS: "demo_home"' in job_body
    assert 'TELEGRAM_SMOKE_ALIAS_CHAT_ID: "111111111"' in job_body
    assert "bash infra/scripts/smoke.sh" in job_body
    assert (
        "logs --no-color postgres ollama-fake stt-service tts-service agent-api open-webui "
        "telegram-ingress telegram-fake" in job_body
    )
