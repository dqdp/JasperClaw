import hmac

from fastapi import Body, FastAPI, Header, HTTPException

from app.clients.agent_api import AgentApiClient
from app.clients.telegram import TelegramClient
from app.core.config import Settings, get_settings
from app.services.bridge import TelegramBridgeService, WebhookResult


def create_app(
    *,
    settings: Settings | None = None,
    bridge_service: TelegramBridgeService | None = None,
) -> FastAPI:
    config = settings if settings is not None else get_settings()
    app = FastAPI(title="telegram-ingress", version="0.1.0")

    if bridge_service is None:
        bridge_service = TelegramBridgeService(
            agent_client=AgentApiClient(
                base_url=config.agent_api_base_url,
                api_key=config.agent_api_key,
                timeout_seconds=config.request_timeout_seconds,
            ),
            telegram_client=TelegramClient(
                bot_token=config.telegram_bot_token,
                api_base_url=config.telegram_api_base_url,
                timeout_seconds=config.request_timeout_seconds,
            ),
            settings=config,
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

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
        await bridge_service.close()

    return app


app = create_app()
