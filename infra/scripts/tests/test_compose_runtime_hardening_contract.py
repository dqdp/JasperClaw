from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "infra" / "compose" / "compose.yml"
ROOT_ENV_FILE = REPO_ROOT / ".env.example"
PROD_ENV_FILE = REPO_ROOT / "infra" / "env" / "prod.example.env"


def _service_block(service_name: str) -> str:
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    match = re.search(
        rf"^  {re.escape(service_name)}:\n(?P<body>(?:^    .*(?:\n|$))*)",
        compose_text,
        re.MULTILINE,
    )
    assert match is not None, f"compose.yml is missing service block for {service_name}"
    return match.group("body")


def test_compose_telegram_ingress_healthcheck_uses_readyz() -> None:
    block = _service_block("telegram-ingress")

    assert "127.0.0.1:8080/readyz" in block
    assert "127.0.0.1:8080/healthz" not in block


def test_compose_voice_services_define_readyz_healthchecks() -> None:
    stt_block = _service_block("stt-service")
    tts_block = _service_block("tts-service")

    assert "healthcheck:" in stt_block
    assert "127.0.0.1:8080/readyz" in stt_block
    assert "healthcheck:" in tts_block
    assert "127.0.0.1:8080/readyz" in tts_block


def test_compose_observability_defaults_are_localhost_only() -> None:
    prometheus_block = _service_block("prometheus")
    grafana_block = _service_block("grafana")

    assert '"${OBSERVABILITY_BIND_HOST:-127.0.0.1}:9090:9090"' in prometheus_block
    assert '"${OBSERVABILITY_BIND_HOST:-127.0.0.1}:3000:3000"' in grafana_block


def test_compose_observability_does_not_enable_unsafe_admin_defaults() -> None:
    prometheus_block = _service_block("prometheus")
    grafana_block = _service_block("grafana")

    assert "--web.enable-lifecycle" not in prometheus_block
    assert "GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER}" in grafana_block
    assert "GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}" in grafana_block
    assert "GF_SECURITY_ADMIN_USER: admin" not in grafana_block
    assert "GF_SECURITY_ADMIN_PASSWORD: admin" not in grafana_block


def test_root_env_templates_define_observability_admin_settings() -> None:
    root_env = ROOT_ENV_FILE.read_text(encoding="utf-8")
    prod_env = PROD_ENV_FILE.read_text(encoding="utf-8")

    for env_text in (root_env, prod_env):
        assert "OBSERVABILITY_BIND_HOST=127.0.0.1" in env_text
        assert "GRAFANA_ADMIN_USER=grafana-admin" in env_text
        assert "GRAFANA_ADMIN_PASSWORD=change-me-observability" in env_text
