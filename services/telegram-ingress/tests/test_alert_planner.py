from app.core.config import Settings
from app.modules.alerts.planner import AlertDeliveryPlan, AlertPlanner


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "telegram_alert_chat_ids": (100,),
        "telegram_alert_warning_chat_ids": (200,),
        "telegram_alert_critical_chat_ids": (300,),
        "telegram_alert_send_resolved": False,
    }
    base.update(overrides)
    return Settings(**base)


def test_alert_planner_routes_manual_text_to_all_available_targets() -> None:
    planner = AlertPlanner(
        settings=_settings(
            telegram_alert_chat_ids=(),
            telegram_alert_warning_chat_ids=(200, 201),
            telegram_alert_critical_chat_ids=(201, 300),
        )
    )

    plan = planner.plan_delivery({"text": "manual alert"})

    assert plan == AlertDeliveryPlan(
        deliveries=((200, "manual alert"), (201, "manual alert"), (300, "manual alert")),
        matched_alerts=1,
    )


def test_alert_planner_routes_by_severity_and_deduplicates_recipients() -> None:
    planner = AlertPlanner(
        settings=_settings(
            telegram_alert_chat_ids=(100,),
            telegram_alert_warning_chat_ids=(100, 200),
            telegram_alert_critical_chat_ids=(200, 300),
        )
    )

    plan = planner.plan_delivery(
        {
            "status": "firing",
            "alerts": [
                {
                    "labels": {
                        "alertname": "DiskFull",
                        "severity": "critical",
                        "service": "db",
                    },
                    "annotations": {"description": "95% full"},
                }
            ],
        }
    )

    assert plan.matched_alerts == 1
    assert tuple(chat_id for chat_id, _ in plan.deliveries) == (100, 200, 300)
    assert all("DiskFull [critical] on db: 95% full" in text for _, text in plan.deliveries)


def test_alert_planner_filters_resolved_alerts_by_default() -> None:
    planner = AlertPlanner(settings=_settings())

    plan = planner.plan_delivery(
        {
            "status": "resolved",
            "alerts": [
                {
                    "labels": {
                        "alertname": "DiskFull",
                        "severity": "critical",
                    },
                    "annotations": {"description": "ok"},
                }
            ],
        }
    )

    assert plan == AlertDeliveryPlan(deliveries=(), matched_alerts=0)


def test_alert_planner_can_include_resolved_alerts_when_enabled() -> None:
    planner = AlertPlanner(
        settings=_settings(telegram_alert_send_resolved=True)
    )

    plan = planner.plan_delivery(
        {
            "status": "resolved",
            "alerts": [
                {
                    "labels": {
                        "alertname": "DiskFull",
                        "severity": "critical",
                    },
                    "annotations": {"description": "ok"},
                }
            ],
        }
    )

    assert plan.matched_alerts == 1
    assert tuple(chat_id for chat_id, _ in plan.deliveries) == (100, 200, 300)
