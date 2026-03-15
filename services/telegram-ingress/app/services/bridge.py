import asyncio
import logging
from collections import deque
from pathlib import Path
from time import perf_counter

from app.clients.agent_api import AgentApiClient, AgentApiError
from app.clients.telegram import TelegramClient, TelegramSendError
from app.core.config import Settings
from app.core.logging import log_event
from app.modules.webhook.commands import CommandRouter
from app.modules.webhook.parser import TelegramUpdate, TelegramUpdateParser
from app.modules.webhook.reply_pipeline import ReplyPipeline
from app.modules.webhook.result import WebhookResult
from shared_infra.household_config import HouseholdConfigSelection, resolve_household_config


class TelegramBridgeRetryableError(RuntimeError):
    """Raised when an update should be retried instead of acknowledged."""


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
        self._household_selection = self._resolve_household_selection()
        self._reply_pipeline = ReplyPipeline(
            agent_client=self._agent_client,
            telegram_client=self._telegram_client,
            agent_model=self._settings.agent_api_model,
            max_reply_chars=self._settings.max_reply_chars,
            release_retry_state=self._release_update_dedupe,
            retryable_error_factory=TelegramBridgeRetryableError,
        )

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

        if not self._is_trusted_chat(update.chat_id):
            result = await self._reply_pipeline.send_local_reply(
                update=update,
                conversation_id=f"telegram:{update.chat_id}",
                text="This chat is not authorized for household assistant access.",
            )
            return self._log_update_result(
                request_id=request_id,
                started=started,
                result=result,
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
            result = await self._reply_pipeline.complete_and_send(
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

        if route.mode == "discovery_help":
            return await self._reply_pipeline.send_local_reply(
                update=update,
                conversation_id=conversation_id,
                text=await self._resolve_discovery_reply(
                    request_id=request_id,
                    route=route,
                ),
            )
        if route.mode == "discovery_status":
            return await self._reply_pipeline.send_local_reply(
                update=update,
                conversation_id=conversation_id,
                text=await self._resolve_discovery_reply(
                    request_id=request_id,
                    route=route,
                ),
            )
        if route.mode == "discovery_aliases":
            return await self._reply_pipeline.send_local_reply(
                update=update,
                conversation_id=conversation_id,
                text=self._render_aliases_reply(),
            )
        if route.mode == "send_alias":
            return await self._handle_send_alias(
                update=update,
                conversation_id=conversation_id,
                route=route,
                request_id=request_id,
            )
        if route.mode == "local_reply":
            return await self._reply_pipeline.send_local_reply(
                update=update,
                conversation_id=conversation_id,
                text=route.text,
            )
        if route.mode == "completion":
            return await self._reply_pipeline.complete_and_send(
                update=update,
                conversation_id=conversation_id,
                prompt_text=route.text,
                request_id=request_id,
            )
        return None

    async def _resolve_discovery_reply(
        self,
        *,
        request_id: str,
        route: CommandRoute,
    ) -> str:
        try:
            discovery = await self._agent_client.describe_capabilities(
                request_id=request_id,
            )
        except AgentApiError:
            # Help/status should degrade to bounded local text instead of turning a
            # simple discovery command into a retryable downstream failure.
            return route.text
        if route.mode == "discovery_help":
            return discovery.help_text
        return discovery.status_text

    async def close(self) -> None:
        await self._agent_client.close()
        await self._telegram_client.close()

    async def _release_update_dedupe(self, update: TelegramUpdate) -> None:
        await self._dedupe.release(self._cache_key(update))

    def _resolve_household_selection(self) -> HouseholdConfigSelection | None:
        return resolve_household_config(
            real_path=self._optional_path(self._settings.household_config_path),
            demo_path=self._optional_path(self._settings.demo_household_config_path),
        )

    def _is_trusted_chat(self, chat_id: int) -> bool:
        if self._household_selection is None:
            return False
        return chat_id in self._household_selection.config.trusted_chat_ids

    def _render_aliases_reply(self) -> str:
        if self._household_selection is None or not self._household_selection.config.aliases:
            return "No aliases are configured right now."
        lines = [
            f"- {alias}: {config.description}"
            for alias, config in self._household_selection.config.aliases.items()
        ]
        return "Available aliases:\n" + "\n".join(lines)

    async def _handle_send_alias(
        self,
        *,
        update: TelegramUpdate,
        conversation_id: str,
        route: CommandRoute,
        request_id: str,
    ) -> WebhookResult:
        alias = (route.alias or "").strip().casefold()
        if self._household_selection is None or not alias:
            return await self._reply_pipeline.send_local_reply(
                update=update,
                conversation_id=conversation_id,
                text="Usage: /send <alias> <message>",
            )
        try:
            reply_text = await self._agent_client.send_alias_command(
                model=self._settings.agent_api_model,
                alias=alias,
                text=route.text,
                conversation_id=conversation_id,
                request_id=request_id,
            )
            if not reply_text.strip():
                raise AgentApiError("agent-api response content missing")
            return await self._reply_pipeline.send_local_reply(
                update=update,
                conversation_id=conversation_id,
                text=reply_text,
            )
        except (AgentApiError, TelegramSendError):
            await self._release_update_dedupe(update)
            raise TelegramBridgeRetryableError(
                "telegram bridge downstream unavailable"
            )

    def _cache_key(self, update: TelegramUpdate) -> str:
        if update.update_id > 0:
            return str(update.update_id)
        return f"{update.chat_id}:{update.message_id}"

    @staticmethod
    def _optional_path(raw_path: str) -> Path | None:
        normalized = raw_path.strip()
        if not normalized:
            return None
        return Path(normalized)

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
