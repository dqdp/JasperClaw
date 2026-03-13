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
        release_retry_state: Callable[[TelegramUpdate], Awaitable[None]],
        retryable_error_factory: Callable[[str], Exception],
    ) -> None:
        self._agent_client = agent_client
        self._telegram_client = telegram_client
        self._agent_model = agent_model
        self._max_reply_chars = max_reply_chars
        # The bridge owns dedupe policy; the pipeline only requests release when a
        # retryable downstream failure makes the cached update unsafe to retain.
        self._release_retry_state = release_retry_state
        self._retryable_error_factory = retryable_error_factory

    async def send_local_reply(
        self,
        *,
        update: TelegramUpdate,
        conversation_id: str,
        text: str,
    ) -> WebhookResult:
        try:
            await self._telegram_client.send_message(
                chat_id=update.chat_id,
                text=text,
            )
        except TelegramSendError:
            await self._release_retry_state(update)
            raise self._retryable_error_factory(
                "telegram bridge downstream unavailable"
            )
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
    ) -> WebhookResult:
        try:
            response = await self._agent_client.complete(
                model=self._agent_model,
                text=prompt_text,
                conversation_id=conversation_id,
                request_id=request_id,
            )
            if len(response) > self._max_reply_chars:
                response = response[: self._max_reply_chars]
            await self._telegram_client.send_message(
                chat_id=update.chat_id,
                text=response,
            )
        except (AgentApiError, TelegramSendError):
            await self._release_retry_state(update)
            raise self._retryable_error_factory(
                "telegram bridge downstream unavailable"
            )
        return WebhookResult.ok(
            status="processed",
            update_id=update.update_id,
            chat_id=update.chat_id,
            message_id=update.message_id,
            conversation_id=conversation_id,
        )
