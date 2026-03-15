from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.clients.agent_api import AgentApiClient, AgentApiError
from app.clients.telegram import TelegramClient, TelegramSendError
from app.modules.webhook.parser import TelegramUpdate
from app.modules.webhook.result import WebhookResult


class ReplyPipeline:
    """Owns downstream completion/local-reply execution for webhook updates."""

    def __init__(
        self,
        *,
        agent_client: AgentApiClient,
        telegram_client: TelegramClient,
        agent_model: str,
        max_reply_chars: int,
        stage_reply: Callable[[TelegramUpdate, str, str], Awaitable[None]],
        complete_delivery: Callable[[TelegramUpdate], Awaitable[None]],
        abandon_processing_state: Callable[[TelegramUpdate], Awaitable[None]],
        retryable_error_factory: Callable[[str], Exception],
    ) -> None:
        self._agent_client = agent_client
        self._telegram_client = telegram_client
        self._agent_model = agent_model
        self._max_reply_chars = max_reply_chars
        self._stage_reply = stage_reply
        self._complete_delivery = complete_delivery
        self._abandon_processing_state = abandon_processing_state
        self._retryable_error_factory = retryable_error_factory

    async def send_local_reply(
        self,
        *,
        update: TelegramUpdate,
        conversation_id: str,
        text: str,
        staged_reply_text: str | None = None,
    ) -> WebhookResult:
        reply_text = staged_reply_text or text
        try:
            if staged_reply_text is None:
                await self._stage_reply(update, conversation_id, reply_text)
            await self._telegram_client.send_message(
                chat_id=update.chat_id,
                text=reply_text,
            )
        except TelegramSendError:
            raise self._retryable_error_factory(
                "telegram bridge downstream unavailable"
            )
        await self._complete_delivery(update)
        return WebhookResult.ok(
            status="processed",
            update_id=update.update_id,
            chat_id=update.chat_id,
            message_id=update.message_id,
            conversation_id=conversation_id,
        )

    async def complete_and_send(
        self,
        *,
        update: TelegramUpdate,
        conversation_id: str,
        prompt_text: str,
        request_id: str,
        idempotency_key: str,
        staged_reply_text: str | None = None,
    ) -> WebhookResult:
        try:
            response = staged_reply_text
            if response is None:
                response = await self._agent_client.complete(
                    model=self._agent_model,
                    text=prompt_text,
                    conversation_id=conversation_id,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                )
                if len(response) > self._max_reply_chars:
                    response = response[: self._max_reply_chars]
                await self._stage_reply(update, conversation_id, response)
            await self._telegram_client.send_message(
                chat_id=update.chat_id,
                text=response,
            )
        except AgentApiError:
            await self._abandon_processing_state(update)
            raise self._retryable_error_factory(
                "telegram bridge downstream unavailable"
            )
        except TelegramSendError:
            raise self._retryable_error_factory(
                "telegram bridge downstream unavailable"
            )
        await self._complete_delivery(update)
        return WebhookResult.ok(
            status="processed",
            update_id=update.update_id,
            chat_id=update.chat_id,
            message_id=update.message_id,
            conversation_id=conversation_id,
        )
