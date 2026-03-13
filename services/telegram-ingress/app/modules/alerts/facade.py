from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.logging import log_event
from app.services.alert_delivery import (
    AlertDeliveryHandler,
    AlertDeliveryRequest,
    AlertDeliveryStorageError,
)

_ALERT_SEVERITY_RANK = {
    "info": 10,
    "warning": 20,
    "critical": 30,
}
_ALERT_SEVERITY_ALIASES = {
    "informational": "info",
    "warn": "warning",
    "error": "critical",
    "fatal": "critical",
}
_ALERT_ACCEPTED_STATUSES = frozenset({"firing", "resolved"})


@dataclass(frozen=True, slots=True)
class AlertDeliveryPlan:
    deliveries: tuple[tuple[int, str], ...]
    matched_alerts: int


@dataclass(frozen=True, slots=True)
class AlertFacadeResponse:
    status_code: int
    payload: dict[str, object]


def unique_chat_ids(*groups: tuple[int, ...]) -> tuple[int, ...]:
    ordered: list[int] = []
    seen: set[int] = set()
    for group in groups:
        for chat_id in group:
            if chat_id in seen:
                continue
            seen.add(chat_id)
            ordered.append(chat_id)
    return tuple(ordered)


class AlertFacade:
    def __init__(
        self,
        *,
        settings: Settings,
        alert_delivery_service: AlertDeliveryHandler,
    ) -> None:
        self._settings = settings
        self._alert_delivery_service = alert_delivery_service

    async def submit_alert(
        self,
        *,
        payload: dict[str, object],
        request_id: str,
        header_idempotency_key: str | None,
    ) -> AlertFacadeResponse:
        plan = self._plan_alert_delivery(payload)
        if not plan.deliveries:
            return AlertFacadeResponse(
                status_code=200,
                payload={
                    "status": "ignored",
                    "reason": "alert_policy_filtered",
                    "matched_alerts": plan.matched_alerts,
                },
            )

        idempotency_key = self._alert_idempotency_key(
            payload=payload,
            header_value=header_idempotency_key,
        )

        try:
            result = await self._alert_delivery_service.submit_delivery(
                request=AlertDeliveryRequest(
                    deliveries=plan.deliveries,
                    matched_alerts=plan.matched_alerts,
                    idempotency_key=idempotency_key,
                ),
                request_id=request_id,
            )
        except AlertDeliveryStorageError as exc:
            log_event(
                "telegram_alert_delivery_storage_failed",
                request_id=request_id,
                recipients=len(plan.deliveries),
                matched_alerts=plan.matched_alerts,
                error_type=type(exc).__name__,
            )
            raise

        log_event(
            "telegram_alert_delivery_submitted",
            request_id=request_id,
            delivery_id=result.delivery_id,
            status=result.status,
            recipients=result.recipients,
            matched_alerts=result.matched_alerts,
            deduplicated=result.deduplicated,
        )
        response_status = 200
        if result.status == "accepted":
            response_status = 202
        elif result.status == "failed":
            response_status = 502
        return AlertFacadeResponse(
            status_code=response_status,
            payload={
                "status": result.status,
                "delivery_id": result.delivery_id,
                "recipients": result.recipients,
                "matched_alerts": result.matched_alerts,
                "deduplicated": result.deduplicated,
            },
        )

    async def process_due_once(
        self,
        *,
        limit: int = 10,
    ) -> int:
        return await self._alert_delivery_service.process_due_deliveries(limit=limit)

    def _extract_field(self, *names: str, source: dict[str, Any]) -> str:
        for name in names:
            value = source.get(name)
            if isinstance(value, str):
                return value.strip()
        return ""

    def _normalize_alert_status(self, raw_status: str) -> str | None:
        normalized = raw_status.strip().lower()
        if normalized in _ALERT_ACCEPTED_STATUSES:
            return normalized
        return None

    def _normalize_alert_severity(self, raw_severity: str) -> str | None:
        normalized = raw_severity.strip().lower()
        normalized = _ALERT_SEVERITY_ALIASES.get(normalized, normalized)
        if normalized in _ALERT_SEVERITY_RANK:
            return normalized
        return None

    def _alert_line(
        self,
        *,
        alert: dict[str, object],
        fallback_status: str | None,
    ) -> tuple[str, str] | None:
        status = self._normalize_alert_status(
            self._extract_field("status", source=alert) or (fallback_status or ""),
        )
        if status is None:
            return None
        if status == "resolved" and not self._settings.telegram_alert_send_resolved:
            return None

        labels = alert.get("labels")
        labels_map: dict[str, str] = {}
        if isinstance(labels, dict):
            for key, value in labels.items():
                if isinstance(value, str):
                    labels_map[key] = value

        annotations = alert.get("annotations")
        annotations_map: dict[str, str] = {}
        if isinstance(annotations, dict):
            for key, value in annotations.items():
                if isinstance(value, str):
                    annotations_map[key] = value

        severity = self._normalize_alert_severity(labels_map.get("severity", ""))
        if severity is None:
            return None

        name = labels_map.get("alertname") or annotations_map.get("summary") or "alert"
        description = annotations_map.get("description") or annotations_map.get(
            "summary"
        ) or name
        component = labels_map.get("service") or labels_map.get("instance") or "unknown"
        generator_url = self._extract_field(
            "generatorURL",
            "generator_url",
            source=alert,
        )

        line = f"{status.upper()} {name} [{severity}] on {component}: {description}"
        if generator_url:
            line = f"{line} ({generator_url})"
        return severity, line

    def _route_chat_ids_for_severity(self, severity: str) -> tuple[int, ...]:
        rank = _ALERT_SEVERITY_RANK[severity]
        groups: list[tuple[int, ...]] = [self._settings.telegram_alert_chat_ids]
        if rank >= _ALERT_SEVERITY_RANK["warning"]:
            groups.append(self._settings.telegram_alert_warning_chat_ids)
        if rank >= _ALERT_SEVERITY_RANK["critical"]:
            groups.append(self._settings.telegram_alert_critical_chat_ids)
        return unique_chat_ids(*groups)

    def _manual_alert_chat_ids(self) -> tuple[int, ...]:
        if self._settings.telegram_alert_chat_ids:
            return unique_chat_ids(self._settings.telegram_alert_chat_ids)
        return unique_chat_ids(
            self._settings.telegram_alert_warning_chat_ids,
            self._settings.telegram_alert_critical_chat_ids,
        )

    def _plan_alert_delivery(self, payload: dict[str, object]) -> AlertDeliveryPlan:
        direct_text = self._extract_field("text", "message", source=payload)
        if direct_text:
            recipients = self._manual_alert_chat_ids()
            return AlertDeliveryPlan(
                deliveries=tuple((chat_id, direct_text) for chat_id in recipients),
                matched_alerts=1,
            )

        alerts_value = payload.get("alerts")
        if isinstance(alerts_value, list) and alerts_value:
            recipient_lines: dict[int, list[str]] = {}
            matched_alerts = 0
            fallback_status = self._normalize_alert_status(
                self._extract_field("status", source=payload)
            )
            for alert in alerts_value:
                if not isinstance(alert, dict):
                    continue
                line_result = self._alert_line(
                    alert=alert,
                    fallback_status=fallback_status,
                )
                if line_result is None:
                    continue
                severity, line = line_result
                matched_alerts += 1
                for chat_id in self._route_chat_ids_for_severity(severity):
                    lines = recipient_lines.setdefault(chat_id, [])
                    if line not in lines:
                        lines.append(line)

            deliveries = tuple(
                sorted(
                    (
                        (chat_id, "\n".join(lines))
                        for chat_id, lines in recipient_lines.items()
                        if lines
                    ),
                    key=lambda item: item[0],
                )
            )
            return AlertDeliveryPlan(
                deliveries=deliveries,
                matched_alerts=matched_alerts,
            )

        return AlertDeliveryPlan(deliveries=(), matched_alerts=0)

    def _alert_idempotency_key(
        self,
        *,
        payload: dict[str, object],
        header_value: str | None,
    ) -> str | None:
        if header_value is not None:
            key = header_value.strip()
            if key:
                return key
        key = self._extract_field("idempotency_key", source=payload)
        return key or None
