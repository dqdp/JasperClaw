import asyncio
from dataclasses import dataclass
import hmac
import logging
from contextlib import suppress
from time import perf_counter
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Request

from app.clients.agent_api import AgentApiClient
from app.clients.telegram import TelegramClient
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_event, new_request_id
from app.services.bridge import (
    TelegramBridgeRetryableError,
    TelegramBridgeService,
    WebhookResult,
)

configure_logging()
logger = logging.getLogger(__name__)

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


def _unique_chat_ids(*groups: tuple[int, ...]) -> tuple[int, ...]:
    ordered: list[int] = []
    seen: set[int] = set()
    for group in groups:
        for chat_id in group:
            if chat_id in seen:
                continue
            seen.add(chat_id)
            ordered.append(chat_id)
    return tuple(ordered)


def create_app(
    *,
    settings: Settings | None = None,
    bridge_service: TelegramBridgeService | None = None,
) -> FastAPI:
    config = settings if settings is not None else get_settings()
    app = FastAPI(title="telegram-ingress", version="0.1.0")

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or new_request_id()
        started = perf_counter()
        log_event(
            "request_started",
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        event = "request_completed" if response.status_code < 400 else "request_failed"
        log_event(
            event,
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return response

    telegram_client = None
    alert_telegram_client = None
    if bridge_service is None:
        telegram_client = TelegramClient(
            bot_token=config.telegram_bot_token,
            api_base_url=config.telegram_api_base_url,
            timeout_seconds=config.request_timeout_seconds,
        )
        if config.telegram_alert_bot_token and _unique_chat_ids(
            config.telegram_alert_chat_ids,
            config.telegram_alert_warning_chat_ids,
            config.telegram_alert_critical_chat_ids,
        ):
            alert_telegram_client = TelegramClient(
                bot_token=config.telegram_alert_bot_token,
                api_base_url=config.telegram_alert_api_base_url,
                timeout_seconds=config.request_timeout_seconds,
            )
        bridge_service = TelegramBridgeService(
            agent_client=AgentApiClient(
                base_url=config.agent_api_base_url,
                api_key=config.agent_api_key,
                timeout_seconds=config.request_timeout_seconds,
            ),
            telegram_client=telegram_client,
            settings=config,
        )

    polling_task: asyncio.Task[None] | None = None

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    async def _poll_updates_forever() -> None:
        assert telegram_client is not None

        next_offset: int | None = None
        while True:
            try:
                updates = await telegram_client.get_updates(
                    timeout=config.telegram_polling_timeout_seconds,
                    offset=next_offset,
                    limit=config.telegram_polling_batch_size,
                )
            except Exception:
                logger.exception("telegram polling error, retrying")
                await asyncio.sleep(1)
                continue

            if updates:
                max_seen_update_id: int | None = None
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int) and update_id > 0:
                        request_id = new_request_id()
                        try:
                            await bridge_service.process_update(
                                update,
                                request_id=request_id,
                            )
                        except TelegramBridgeRetryableError:
                            logger.exception(
                                "telegram update processing failed, will retry update %s",
                                update_id,
                            )
                            next_offset = update_id
                            await asyncio.sleep(1)
                            break
                        max_seen_update_id = (
                            update_id
                            if max_seen_update_id is None
                            else max(max_seen_update_id, update_id)
                        )
                    else:
                        logger.warning(
                            "telegram poll update missing update_id: %s",
                            update.get("update_id"),
                        )
                else:
                    if max_seen_update_id is not None:
                        next_offset = max_seen_update_id + 1
            else:
                await asyncio.sleep(1.0)

    @app.on_event("startup")
    async def _startup() -> None:
        nonlocal polling_task
        if config.telegram_webhook_url and not config.telegram_webhook_secret_token:
            raise RuntimeError(
                "TELEGRAM_WEBHOOK_SECRET_TOKEN is required when "
                "TELEGRAM_WEBHOOK_URL is configured"
            )
        if not config.is_operational() or telegram_client is None:
            return

        if config.telegram_webhook_url:
            await telegram_client.set_webhook(
                url=config.telegram_webhook_url,
                secret_token=config.telegram_webhook_secret_token,
            )
            logger.info("telegram ingress webhook registered")
            return

        if config.telegram_polling_enabled:
            logger.info("telegram polling enabled, no webhook URL configured")
            polling_task = asyncio.create_task(_poll_updates_forever())
            app.state.telegram_polling_task = polling_task

    def _extract_field(*names: str, source: dict[str, Any]) -> str:
        for name in names:
            value = source.get(name)
            if isinstance(value, str):
                return value.strip()
        return ""

    def _normalize_alert_status(raw_status: str) -> str | None:
        normalized = raw_status.strip().lower()
        if normalized in _ALERT_ACCEPTED_STATUSES:
            return normalized
        return None

    def _normalize_alert_severity(raw_severity: str) -> str | None:
        normalized = raw_severity.strip().lower()
        normalized = _ALERT_SEVERITY_ALIASES.get(normalized, normalized)
        if normalized in _ALERT_SEVERITY_RANK:
            return normalized
        return None

    def _alert_line(
        *,
        alert: dict[str, object],
        fallback_status: str | None,
    ) -> tuple[str, str] | None:
        status = _normalize_alert_status(
            _extract_field("status", source=alert) or (fallback_status or ""),
        )
        if status is None:
            return None
        if status == "resolved" and not config.telegram_alert_send_resolved:
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

        severity = _normalize_alert_severity(labels_map.get("severity", ""))
        if severity is None:
            return None

        name = labels_map.get("alertname") or annotations_map.get("summary") or "alert"
        description = annotations_map.get("description") or annotations_map.get("summary") or name
        component = labels_map.get("service") or labels_map.get("instance") or "unknown"
        generator_url = _extract_field("generatorURL", "generator_url", source=alert)

        line = f"{status.upper()} {name} [{severity}] on {component}: {description}"
        if generator_url:
            line = f"{line} ({generator_url})"
        return severity, line

    def _route_chat_ids_for_severity(severity: str) -> tuple[int, ...]:
        rank = _ALERT_SEVERITY_RANK[severity]
        groups: list[tuple[int, ...]] = [config.telegram_alert_chat_ids]
        if rank >= _ALERT_SEVERITY_RANK["warning"]:
            groups.append(config.telegram_alert_warning_chat_ids)
        if rank >= _ALERT_SEVERITY_RANK["critical"]:
            groups.append(config.telegram_alert_critical_chat_ids)
        return _unique_chat_ids(*groups)

    def _manual_alert_chat_ids() -> tuple[int, ...]:
        if config.telegram_alert_chat_ids:
            return _unique_chat_ids(config.telegram_alert_chat_ids)
        return _unique_chat_ids(
            config.telegram_alert_warning_chat_ids,
            config.telegram_alert_critical_chat_ids,
        )

    def _plan_alert_delivery(payload: dict[str, object]) -> AlertDeliveryPlan:
        direct_text = _extract_field("text", "message", source=payload)
        if direct_text:
            recipients = _manual_alert_chat_ids()
            return AlertDeliveryPlan(
                deliveries=tuple((chat_id, direct_text) for chat_id in recipients),
                matched_alerts=1,
            )

        alerts_value = payload.get("alerts")
        if isinstance(alerts_value, list) and alerts_value:
            recipient_lines: dict[int, list[str]] = {}
            matched_alerts = 0
            fallback_status = _normalize_alert_status(_extract_field("status", source=payload))
            for alert in alerts_value:
                if not isinstance(alert, dict):
                    continue
                line_result = _alert_line(alert=alert, fallback_status=fallback_status)
                if line_result is None:
                    continue
                severity, line = line_result
                matched_alerts += 1
                for chat_id in _route_chat_ids_for_severity(severity):
                    lines = recipient_lines.setdefault(chat_id, [])
                    if line not in lines:
                        lines.append(line)

            deliveries = tuple(
                (chat_id, "\n".join(lines))
                for chat_id, lines in recipient_lines.items()
                if lines
            )
            return AlertDeliveryPlan(
                deliveries=deliveries,
                matched_alerts=matched_alerts,
            )

        return AlertDeliveryPlan(deliveries=(), matched_alerts=0)

    @app.post(config.webhook_path)
    async def webhook(
        request: Request,
        update: dict[str, object] = Body(...),
        x_telegram_secret_token: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
    ) -> dict[str, object]:
        if config.telegram_webhook_secret_token and (
            x_telegram_secret_token is None
            or not hmac.compare_digest(
                x_telegram_secret_token,
                config.telegram_webhook_secret_token,
            )
        ):
            raise HTTPException(status_code=401, detail="invalid webhook token")

        if not config.is_operational():
            raise HTTPException(status_code=503, detail="telegram ingress is not configured")

        if not isinstance(update, dict):
            return WebhookResult.ignored(reason="invalid_payload").as_dict()

        try:
            result = await bridge_service.process_update(
                update,
                request_id=request.state.request_id,
            )
        except TelegramBridgeRetryableError as exc:
            raise HTTPException(
                status_code=503,
                detail="telegram bridge downstream unavailable",
            ) from exc
        return result.as_dict()

    @app.post("/telegram/alerts")
    async def telegram_alerts(
        payload: dict[str, object] = Body(...),
        x_telegram_alert_token: str | None = Header(default=None, alias="X-Telegram-Alert-Token"),
    ) -> dict[str, object]:
        if alert_telegram_client is None or not _unique_chat_ids(
            config.telegram_alert_chat_ids,
            config.telegram_alert_warning_chat_ids,
            config.telegram_alert_critical_chat_ids,
        ):
            raise HTTPException(
                status_code=503,
                detail="telegram alert relay is not configured",
            )

        if config.telegram_alert_auth_token and (
            x_telegram_alert_token is None
            or not hmac.compare_digest(
                x_telegram_alert_token,
                config.telegram_alert_auth_token,
            )
        ):
            raise HTTPException(status_code=401, detail="invalid alert token")

        plan = _plan_alert_delivery(payload)
        if not plan.deliveries:
            return {
                "status": "ignored",
                "reason": "alert_policy_filtered",
                "matched_alerts": plan.matched_alerts,
            }

        try:
            for chat_id, message in plan.deliveries:
                await alert_telegram_client.send_message(chat_id=chat_id, text=message)
        except Exception as exc:
            log_event(
                "telegram_alert_delivery_failed",
                request_id="alert_delivery",
                recipients=len(plan.deliveries),
                matched_alerts=plan.matched_alerts,
                error_type=type(exc).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="telegram alert delivery failed",
            ) from exc
        return {
            "status": "sent",
            "recipients": len(plan.deliveries),
            "matched_alerts": plan.matched_alerts,
        }

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if polling_task is not None:
            polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await polling_task
        if alert_telegram_client is not None:
            await alert_telegram_client.close()
        await bridge_service.close()

    return app


app = create_app()
