from __future__ import annotations

from app.services.bridge import TelegramBridgeService, WebhookResult


class WebhookFacade:
    def __init__(self, *, bridge_service: TelegramBridgeService) -> None:
        self._bridge_service = bridge_service

    async def handle_update(
        self,
        *,
        update: dict[str, object],
        request_id: str,
    ) -> WebhookResult:
        return await self._bridge_service.process_update(
            update,
            request_id=request_id,
        )
