from __future__ import annotations

import json
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
ALERT_RULES_PATH = (
    REPO_ROOT / "infra/compose/observability/prometheus/alerts/telegram-ingress.rules.yml"
)
DASHBOARD_PATH = (
    REPO_ROOT / "infra/compose/observability/grafana/dashboards/telegram-operations.json"
)
ROLLOUT_DOC_PATH = REPO_ROOT / "docs/ops/dashboard-and-alert-rollout.md"


def test_telegram_alert_rules_include_delivery_escalation_signal() -> None:
    rules = yaml.safe_load(ALERT_RULES_PATH.read_text())
    alert = next(
        rule
        for group in rules["groups"]
        for rule in group["rules"]
        if rule.get("alert") == "TelegramAlertDeliveryEscalated"
    )

    assert alert["labels"]["severity"] == "critical"
    assert 'sum by (reason) (increase(telegram_alert_delivery_escalated_total[10m])) > 0' == alert["expr"]
    assert "{{ $labels.reason }}" in alert["annotations"]["description"]


def test_telegram_dashboard_includes_escalation_panel() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text())
    panel = next(panel for panel in dashboard["panels"] if panel["title"] == "Escalations")

    assert (
        panel["targets"][0]["expr"]
        == 'sum by (reason) (rate(telegram_alert_delivery_escalated_total[5m]))'
    )


def test_telegram_rollout_doc_mentions_escalation_signal() -> None:
    rollout_doc = ROLLOUT_DOC_PATH.read_text()

    assert "telegram_alert_delivery_escalated_total" in rollout_doc
    assert "TelegramAlertDeliveryEscalated" in rollout_doc
    assert "finalize_failed_total" in rollout_doc
