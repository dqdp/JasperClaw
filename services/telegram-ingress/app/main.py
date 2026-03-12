import asyncio
import hmac
import logging
from contextlib import suppress
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException

from app.clients.agent_api import AgentApiClient
from app.clients.telegram import TelegramClient
from app.core.config import Settings, get_settings
from app.services.bridge import (
    TelegramBridgeRetryableError,
    TelegramBridgeService,
    WebhookResult,
)

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    bridge_service: TelegramBridgeService | None = None,
) -> FastAPI:
    config = settings if settings is not None else get_settings()
    app = FastAPI(title="telegram-ingress", version="0.1.0")

    telegram_client = None
    alert_telegram_client = None
    if bridge_service is None:
        telegram_client = TelegramClient(
            bot_token=config.telegram_bot_token,
            api_base_url=config.telegram_api_base_url,
            timeout_seconds=config.request_timeout_seconds,
        )
        if config.telegram_alert_bot_token and config.telegram_alert_chat_ids:
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
                        try:
                            await bridge_service.process_update(update)
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

    def _format_alert_message(payload: dict[str, object]) -> str:
        direct_text = _extract_field("text", "message", source=payload)
        if direct_text:
            return direct_text

        alerts_value = payload.get("alerts")
        if isinstance(alerts_value, list) and alerts_value:
            lines: list[str] = []
            status = _extract_field("status", source=payload).upper() or "ALERT"

            for alert in alerts_value:
                if not isinstance(alert, dict):
                    continue

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

                name = labels_map.get("alertname") or annotations_map.get("summary") or "alert"
                severity = labels_map.get("severity") or "unknown"
                description = annotations_map.get("description") or annotations_map.get("summary") or name
                component = labels_map.get("service") or labels_map.get("instance") or "unknown"
                generator_url = _extract_field("generatorURL", "generator_url", source=alert)

                line = f"{status} {name} [{severity}] on {component}: {description}"
                if generator_url:
                    line = f"{line} ({generator_url})"
                lines.append(line)

            if lines:
                return "\n".join(lines)

        return str(payload)

    @app.post(config.webhook_path)
    async def webhook(
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
            result = await bridge_service.process_update(update)
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
        if alert_telegram_client is None or not config.telegram_alert_chat_ids:
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

        message = _format_alert_message(payload)
        for chat_id in config.telegram_alert_chat_ids:
            await alert_telegram_client.send_message(chat_id=chat_id, text=message)
        return {"status": "sent", "recipients": len(config.telegram_alert_chat_ids)}

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
