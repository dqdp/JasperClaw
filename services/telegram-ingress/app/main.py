import asyncio
import hmac
import logging
from contextlib import suppress
from time import perf_counter

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.clients.agent_api import AgentApiClient
from app.clients.telegram import TelegramClient
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_event, new_request_id
from app.modules.alerts.facade import AlertFacade, unique_chat_ids
from app.modules.webhook.facade import WebhookFacade
from app.services.alert_delivery import (
    AlertDeliveryHandler,
    AlertDeliveryService,
    AlertDeliveryStorageError,
    PostgresAlertDeliveryRepository,
)
from app.services.bridge import (
    TelegramBridgeRetryableError,
    TelegramBridgeService,
)

configure_logging()
logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    bridge_service: TelegramBridgeService | None = None,
    alert_delivery_service: AlertDeliveryHandler | None = None,
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
    if bridge_service is None:
        telegram_client = TelegramClient(
            bot_token=config.telegram_bot_token,
            api_base_url=config.telegram_api_base_url,
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
    webhook_facade = WebhookFacade(bridge_service=bridge_service)

    alert_telegram_client = None
    alert_chat_ids = unique_chat_ids(
        config.telegram_alert_chat_ids,
        config.telegram_alert_warning_chat_ids,
        config.telegram_alert_critical_chat_ids,
    )
    if alert_delivery_service is None and config.telegram_alert_bot_token and alert_chat_ids:
        alert_telegram_client = TelegramClient(
            bot_token=config.telegram_alert_bot_token,
            api_base_url=config.telegram_alert_api_base_url,
            timeout_seconds=config.request_timeout_seconds,
        )
        alert_delivery_service = AlertDeliveryService(
            repository=PostgresAlertDeliveryRepository(config.database_url),
            telegram_client=alert_telegram_client,
            retry_backoff_seconds=config.telegram_alert_retry_backoff_seconds,
            max_attempts=config.telegram_alert_max_attempts,
            claim_ttl_seconds=config.telegram_alert_claim_ttl_seconds,
        )
    alert_facade = None
    if alert_delivery_service is not None:
        alert_facade = AlertFacade(
            settings=config,
            alert_delivery_service=alert_delivery_service,
        )

    polling_task: asyncio.Task[None] | None = None
    alert_retry_task: asyncio.Task[None] | None = None

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
                            await webhook_facade.handle_update(
                                update=update,
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
        nonlocal alert_retry_task, polling_task
        if config.telegram_webhook_url and not config.telegram_webhook_secret_token:
            raise RuntimeError(
                "TELEGRAM_WEBHOOK_SECRET_TOKEN is required when "
                "TELEGRAM_WEBHOOK_URL is configured"
            )
        if (
            alert_delivery_service is not None
            and config.telegram_alert_retry_worker_enabled
        ):
            alert_retry_task = asyncio.create_task(_retry_alert_deliveries_forever())
            app.state.alert_retry_task = alert_retry_task
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

    async def _retry_alert_deliveries_forever() -> None:
        assert alert_facade is not None
        poll_seconds = max(config.telegram_alert_retry_poll_seconds, 0.1)
        while True:
            try:
                processed = await alert_facade.process_due_once(limit=10)
            except Exception:
                logger.exception("telegram alert retry loop error")
                await asyncio.sleep(poll_seconds)
                continue
            if processed == 0:
                await asyncio.sleep(poll_seconds)
            else:
                await asyncio.sleep(0)

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
            return {"status": "ignored", "reason": "invalid_payload"}

        try:
            result = await webhook_facade.handle_update(
                update=update,
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
        request: Request,
        payload: dict[str, object] = Body(...),
        x_telegram_alert_token: str | None = Header(default=None, alias="X-Telegram-Alert-Token"),
        x_telegram_alert_idempotency_key: str | None = Header(
            default=None,
            alias="X-Telegram-Alert-Idempotency-Key",
        ),
    ) -> object:
        if alert_facade is None or not alert_chat_ids:
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

        try:
            result = await alert_facade.submit_alert(
                payload=payload,
                request_id=request.state.request_id,
                header_idempotency_key=x_telegram_alert_idempotency_key,
            )
        except AlertDeliveryStorageError as exc:
            raise HTTPException(
                status_code=503,
                detail="telegram alert delivery unavailable",
            ) from exc

        return JSONResponse(status_code=result.status_code, content=result.payload)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if alert_retry_task is not None:
            alert_retry_task.cancel()
            with suppress(asyncio.CancelledError):
                await alert_retry_task
        if polling_task is not None:
            polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await polling_task
        if alert_delivery_service is not None:
            await alert_delivery_service.close()
        if alert_telegram_client is not None:
            await alert_telegram_client.close()
        await bridge_service.close()

    return app


app = create_app()
