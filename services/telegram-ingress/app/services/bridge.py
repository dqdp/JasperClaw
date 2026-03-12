import asyncio
from dataclasses import asdict, dataclass
from time import perf_counter
from collections import deque
from typing import Any

from app.clients.agent_api import AgentApiClient, AgentApiError
from app.clients.telegram import TelegramClient, TelegramSendError
from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    update_id: int
    chat_id: int
    message_id: int
    user_id: int | None
    text: str


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

    async def process_update(self, payload: dict[str, object]) -> WebhookResult:
        update = self._parse_update(payload)
        if update is None:
            return WebhookResult.ignored(reason="message not text or missing chat")

        if len(update.text) > self._settings.telegram_max_input_chars:
            return WebhookResult(
                status="ignored",
                update_id=update.update_id,
                chat_id=update.chat_id,
                message_id=update.message_id,
                reason="input_too_large",
            )

        cache_key = self._cache_key(update)
        if not await self._dedupe.should_process(cache_key):
            return WebhookResult(
                status="ignored",
                update_id=update.update_id,
                chat_id=update.chat_id,
                message_id=update.message_id,
                reason="duplicate_update",
            )
        if not await self._global_rate_limiter.allow("global"):
            return WebhookResult.ignored(reason="rate_limited_global")
        if not await self._chat_rate_limiter.allow(str(update.chat_id)):
            return WebhookResult.ignored(reason="rate_limited_chat")

        conversation_id = f"telegram:{update.chat_id}"
        try:
            response = await self._agent_client.complete(
                model=self._settings.agent_api_model,
                text=update.text,
                conversation_id=conversation_id,
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
            await self._dedupe.release(cache_key)
            return WebhookResult.ignored(reason="agent_or_telegram_failed")

    async def close(self) -> None:
        await self._agent_client.close()
        await self._telegram_client.close()

    def _cache_key(self, update: TelegramUpdate) -> str:
        if update.update_id > 0:
            return str(update.update_id)
        return f"{update.chat_id}:{update.message_id}"

    def _parse_update(self, payload: dict[str, object]) -> TelegramUpdate | None:
        message = self._extract_message(payload)
        if message is None:
            return None

        if self._is_bot_message(message):
            return None

        update_id = self._coerce_int(payload.get("update_id"), None)
        chat_id = self._coerce_int(message.get("chat"), 0, key="id")
        message_id = self._coerce_int(message, 0, key="message_id")
        if chat_id <= 0 or message_id <= 0:
            return None

        text = self._extract_text(message)
        if not text:
            return None

        user_id = None
        from_block = message.get("from")
        if isinstance(from_block, dict):
            user_id = self._coerce_int(from_block, None, key="id")
            if isinstance(user_id, int) and user_id <= 0:
                user_id = None

        return TelegramUpdate(
            update_id=0 if update_id is None else update_id,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            text=text,
        )

    def _extract_message(self, payload: dict[str, object]) -> dict[str, object] | None:
        message = payload.get("message")
        if isinstance(message, dict):
            return message
        edited_message = payload.get("edited_message")
        if isinstance(edited_message, dict):
            return edited_message
        return None

    def _is_bot_message(self, message: dict[str, object]) -> bool:
        sender = message.get("from")
        if not isinstance(sender, dict):
            return False
        return sender.get("is_bot") is True

    def _extract_text(self, message: dict[str, object]) -> str:
        text = message.get("text")
        if isinstance(text, str):
            return text.strip()
        caption = message.get("caption")
        if isinstance(caption, str):
            return caption.strip()
        return ""

    def _coerce_int(
        self, source: object, default: int | None, key: str | None = None
    ) -> int | None:
        value = source
        if isinstance(key, str) and isinstance(source, dict):
            value = source.get(key)
        elif key is not None:
            raise ValueError("key is only valid with dict source")

        if not isinstance(value, int):
            return default
        if isinstance(value, bool):
            return default
        return value
