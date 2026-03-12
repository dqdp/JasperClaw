import asyncio
import hmac
import logging
from contextlib import suppress

from fastapi import Body, FastAPI, Header, HTTPException

from app.clients.agent_api import AgentApiClient
from app.clients.telegram import TelegramClient
from app.core.config import Settings, get_settings
from app.services.bridge import TelegramBridgeService, WebhookResult

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    bridge_service: TelegramBridgeService | None = None,
) -> FastAPI:
    config = settings if settings is not None else get_settings()
    app = FastAPI(title="telegram-ingress", version="0.1.0")

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
                max_seen_update_id: int | None = next_offset
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int) and update_id > 0:
                        if max_seen_update_id is None:
                            max_seen_update_id = update_id
                        else:
                            max_seen_update_id = max(max_seen_update_id, update_id)
                        await bridge_service.process_update(update)
                    else:
                        logger.warning(
                            "telegram poll update missing update_id: %s",
                            update.get("update_id"),
                        )

                if max_seen_update_id is not None:
                    next_offset = max_seen_update_id + 1
            else:
                await asyncio.sleep(1.0)

    @app.on_event("startup")
    async def _startup() -> None:
        nonlocal polling_task
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

        result = await bridge_service.process_update(update)
        return result.as_dict()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if polling_task is not None:
            polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await polling_task
        await bridge_service.close()

    return app


app = create_app()
