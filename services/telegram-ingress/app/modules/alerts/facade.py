from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import log_event
from app.modules.alerts.planner import AlertPlanner
from app.services.alert_delivery import (
    AlertDeliveryHandler,
    AlertDeliveryRequest,
    AlertDeliveryStorageError,
)
from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class AlertFacadeResponse:
    status_code: int
    payload: dict[str, object]


class AlertFacade:
    def __init__(
        self,
        *,
        settings: Settings,
        alert_delivery_service: AlertDeliveryHandler,
    ) -> None:
        self._alert_delivery_service = alert_delivery_service
        self._planner = AlertPlanner(settings=settings)

    async def submit_alert(
        self,
        *,
        payload: dict[str, object],
        request_id: str,
        header_idempotency_key: str | None,
    ) -> AlertFacadeResponse:
        plan = self._planner.plan_delivery(payload)
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
        key = payload.get("idempotency_key")
        if isinstance(key, str):
            key = key.strip()
        return key or None
