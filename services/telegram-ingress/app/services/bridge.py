import asyncio
import logging
from dataclasses import asdict, dataclass
from collections import deque
from time import perf_counter
from typing import Any

from app.clients.agent_api import AgentApiClient, AgentApiError
from app.clients.telegram import TelegramClient, TelegramSendError
from app.core.config import Settings
from app.core.logging import log_event
from app.modules.webhook.commands import CommandRouter
from app.modules.webhook.parser import TelegramUpdate, TelegramUpdateParser


class TelegramBridgeRetryableError(RuntimeError):
    """Raised when an update should be retried instead of acknowledged."""


@dataclass(frozen=True, slots=True)
class WebhookResult:
    status: str
    update_id: int | None = None
    chat_id: int | None = None
    message_id: int | None = None
    conversation_id: str | None = None
    reason: str | None = None

    @classmethod
    def ok(
        cls,
        *,
        update_id: int,
        chat_id: int,
        message_id: int,
        conversation_id: str,
        status: str,
    ) -> "WebhookResult":
        return cls(
            status=status,
            update_id=update_id,
            chat_id=chat_id,
            message_id=message_id,
            conversation_id=conversation_id,
        )

    @classmethod
    def ignored(cls, *, reason: str) -> "WebhookResult":
        return cls(status="ignored", reason=reason)

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class DedupCache:
    """Short-term idempotency cache with TTL and bounded size."""

    def __init__(self, *, ttl_seconds: float, max_events: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_events = max_events
        self._events: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def should_process(self, key: str) -> bool:
        now = perf_counter()
        async with self._lock:
            self._evict(now)
            if key in self._events:
                return False
            self._events[key] = now
            self._enforce_capacity(now)
            return True

    async def release(self, key: str) -> None:
        async with self._lock:
            self._events.pop(key, None)

    def _evict(self, now: float) -> None:
        if not self._events:
            return
        expired_cutoff = now - self._ttl_seconds
        for event_key in list(self._events):
            if self._events[event_key] < expired_cutoff:
                self._events.pop(event_key, None)

    def _enforce_capacity(self, now: float) -> None:
        if len(self._events) <= self._max_events:
            return
        sorted_keys = sorted(self._events.items(), key=lambda item: item[1])
        for stale_key, _ in sorted_keys[:-self._max_events]:
            self._events.pop(stale_key, None)

        if self._events and now - min(self._events.values()) > self._ttl_seconds:
            self._evict(now)


class RateLimiter:
    """Sliding-window rate limiter with bounded history per key."""

    def __init__(self, *, limit_per_window: int, window_seconds: float) -> None:
        self._limit_per_window = max(0, limit_per_window)
        self._window_seconds = max(0.0, window_seconds)
        self._history: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        if self._limit_per_window <= 0 or self._window_seconds <= 0:
            return True

        now = perf_counter()
        async with self._lock:
            events = self._history.setdefault(key, deque())
            cutoff = now - self._window_seconds

            while events and events[0] < cutoff:
                events.popleft()

            if len(events) >= self._limit_per_window:
                return False

            events.append(now)
            return True


class TelegramBridgeService:
    """Single-pass webhook bridge from Telegram update -> agent-api -> telegram send."""

    def __init__(
        self,
        *,
        agent_client: AgentApiClient,
        telegram_client: TelegramClient,
        settings: Settings,
    ) -> None:
        self._agent_client = agent_client
        self._telegram_client = telegram_client
        self._settings = settings
        self._dedupe = DedupCache(
            ttl_seconds=self._settings.dedupe_window_seconds,
            max_events=self._settings.dedupe_max_events,
        )
        self._chat_rate_limiter = RateLimiter(
            limit_per_window=self._settings.telegram_rate_limit_per_chat,
            window_seconds=self._settings.rate_limit_window_seconds,
        )
        self._global_rate_limiter = RateLimiter(
            limit_per_window=self._settings.telegram_rate_limit_global,
            window_seconds=self._settings.rate_limit_window_seconds,
        )
        self._parser = TelegramUpdateParser(
            allowed_commands=self._settings.telegram_allowed_commands,
        )
        self._command_router = CommandRouter(parser=self._parser)

    async def process_update(
        self,
        payload: dict[str, object],
        *,
        request_id: str,
    ) -> WebhookResult:
        started = perf_counter()
        context = self._parser.payload_context(payload)
        log_event(
            "telegram_update_received",
            request_id=request_id,
            **context,
        )
        update = self._parser.parse_update(payload)
        if update is None:
            return self._log_update_result(
                request_id=request_id,
                started=started,
                result=WebhookResult.ignored(reason="message not text or missing chat"),
                **context,
            )

        if len(update.text) > self._settings.telegram_max_input_chars:
            return self._log_update_result(
                request_id=request_id,
                started=started,
                result=WebhookResult(
                    status="ignored",
                    update_id=update.update_id,
                    chat_id=update.chat_id,
                    message_id=update.message_id,
                    reason="input_too_large",
                ),
                update_id=update.update_id,
                chat_id=update.chat_id,
                message_id=update.message_id,
                conversation_id=f"telegram:{update.chat_id}",
            )

        cache_key = self._cache_key(update)
        if not await self._dedupe.should_process(cache_key):
            return self._log_update_result(
                request_id=request_id,
                started=started,
                result=WebhookResult(
                    status="ignored",
                    update_id=update.update_id,
                    chat_id=update.chat_id,
                    message_id=update.message_id,
                    reason="duplicate_update",
                ),
                update_id=update.update_id,
                chat_id=update.chat_id,
                message_id=update.message_id,
                conversation_id=f"telegram:{update.chat_id}",
            )
        if not await self._global_rate_limiter.allow("global"):
            return self._log_update_result(
                request_id=request_id,
                started=started,
                result=WebhookResult.ignored(reason="rate_limited_global"),
                update_id=update.update_id,
                chat_id=update.chat_id,
                message_id=update.message_id,
                conversation_id=f"telegram:{update.chat_id}",
            )
        if not await self._chat_rate_limiter.allow(str(update.chat_id)):
            return self._log_update_result(
                request_id=request_id,
                started=started,
                result=WebhookResult.ignored(reason="rate_limited_chat"),
                update_id=update.update_id,
                chat_id=update.chat_id,
                message_id=update.message_id,
                conversation_id=f"telegram:{update.chat_id}",
            )

        conversation_id = f"telegram:{update.chat_id}"
        command = self._parser.extract_command(update.text)
        if command is not None:
            if not self._parser.is_command_allowed(update.text):
                return self._log_update_result(
                    request_id=request_id,
                    started=started,
                    result=WebhookResult(
                        status="ignored",
                        update_id=update.update_id,
                        chat_id=update.chat_id,
                        message_id=update.message_id,
                        reason="command_not_allowed",
                    ),
                    update_id=update.update_id,
                    chat_id=update.chat_id,
                    message_id=update.message_id,
                    conversation_id=conversation_id,
                )
            try:
                handled = await self._handle_command(
                    update=update,
                    conversation_id=conversation_id,
                    request_id=request_id,
                )
            except TelegramBridgeRetryableError:
                self._log_update_failure(
                    request_id=request_id,
                    started=started,
                    update_id=update.update_id,
                    chat_id=update.chat_id,
                    message_id=update.message_id,
                    conversation_id=conversation_id,
                )
                raise
            if handled is not None:
                return self._log_update_result(
                    request_id=request_id,
                    started=started,
                    result=handled,
                    update_id=update.update_id,
                    chat_id=update.chat_id,
                    message_id=update.message_id,
                    conversation_id=conversation_id,
                )
            return self._log_update_result(
                request_id=request_id,
                started=started,
                result=WebhookResult(
                    status="ignored",
                    update_id=update.update_id,
                    chat_id=update.chat_id,
                    message_id=update.message_id,
                    reason="command_not_allowed",
                ),
                update_id=update.update_id,
                chat_id=update.chat_id,
                message_id=update.message_id,
                conversation_id=conversation_id,
            )

        try:
            result = await self._complete_and_send(
                update=update,
                conversation_id=conversation_id,
                prompt_text=update.text,
                request_id=request_id,
            )
        except TelegramBridgeRetryableError:
            self._log_update_failure(
                request_id=request_id,
                started=started,
                update_id=update.update_id,
                chat_id=update.chat_id,
                message_id=update.message_id,
                conversation_id=conversation_id,
            )
            raise
        return self._log_update_result(
            request_id=request_id,
            started=started,
            result=result,
            update_id=update.update_id,
            chat_id=update.chat_id,
            message_id=update.message_id,
            conversation_id=conversation_id,
        )

    async def _handle_command(
        self,
        *,
        update: TelegramUpdate,
        conversation_id: str,
        request_id: str,
    ) -> WebhookResult | None:
        route = self._command_router.route(update.text)
        if route is None:
            return None

        if route.mode == "local_reply":
            return await self._send_local_reply(
                update=update,
                conversation_id=conversation_id,
                text=route.text,
            )
        if route.mode == "completion":
            return await self._complete_and_send(
                update=update,
                conversation_id=conversation_id,
                prompt_text=route.text,
                request_id=request_id,
            )
        return None

    async def _send_local_reply(
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
            return WebhookResult.ok(
                status="processed",
                update_id=update.update_id,
                chat_id=update.chat_id,
                message_id=update.message_id,
                conversation_id=conversation_id,
            )
        except TelegramSendError:
            await self._dedupe.release(self._cache_key(update))
            raise TelegramBridgeRetryableError(
                "telegram bridge downstream unavailable"
            )

    async def _complete_and_send(
        self,
        *,
        update: TelegramUpdate,
        conversation_id: str,
        prompt_text: str,
        request_id: str,
    ) -> WebhookResult:
        try:
            response = await self._agent_client.complete(
                model=self._settings.agent_api_model,
                text=prompt_text,
                conversation_id=conversation_id,
                request_id=request_id,
            )
            if len(response) > self._settings.max_reply_chars:
                response = response[: self._settings.max_reply_chars]

            await self._telegram_client.send_message(
                chat_id=update.chat_id,
                text=response,
            )
            return WebhookResult.ok(
                status="processed",
                update_id=update.update_id,
                chat_id=update.chat_id,
                message_id=update.message_id,
                conversation_id=conversation_id,
            )
        except (AgentApiError, TelegramSendError):
            await self._dedupe.release(self._cache_key(update))
            raise TelegramBridgeRetryableError(
                "telegram bridge downstream unavailable"
            )

    async def close(self) -> None:
        await self._agent_client.close()
        await self._telegram_client.close()

    def _cache_key(self, update: TelegramUpdate) -> str:
        if update.update_id > 0:
            return str(update.update_id)
        return f"{update.chat_id}:{update.message_id}"

    def _log_update_result(
        self,
        *,
        request_id: str,
        started: float,
        result: WebhookResult,
        update_id: int | None,
        chat_id: int | None,
        message_id: int | None,
        conversation_id: str | None,
    ) -> WebhookResult:
        level = logging.INFO if result.status == "processed" else logging.WARNING
        log_event(
            "telegram_update_completed",
            level=level,
            request_id=request_id,
            outcome=result.status,
            duration_ms=round((perf_counter() - started) * 1000, 2),
            update_id=update_id,
            chat_id=chat_id,
            message_id=message_id,
            conversation_id=conversation_id,
            reason=result.reason,
        )
        return result

    def _log_update_failure(
        self,
        *,
        request_id: str,
        started: float,
        update_id: int | None,
        chat_id: int | None,
        message_id: int | None,
        conversation_id: str | None,
    ) -> None:
        log_event(
            "telegram_update_failed",
            level=logging.WARNING,
            request_id=request_id,
            outcome="retryable_error",
            duration_ms=round((perf_counter() - started) * 1000, 2),
            update_id=update_id,
            chat_id=chat_id,
            message_id=message_id,
            conversation_id=conversation_id,
        )
