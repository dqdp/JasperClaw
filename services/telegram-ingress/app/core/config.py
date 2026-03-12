from dataclasses import dataclass
from functools import lru_cache
import os


_PLACEHOLDER_SECRET_VALUES = frozenset({"", "change-me"})


def _strip_secret(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized.casefold() in _PLACEHOLDER_SECRET_VALUES:
        return ""
    return normalized


def _normalize_webhook_path(path: str) -> str:
    normalized = (path or "/webhook").strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"invalid integer env var {name}: {raw}") from exc


def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ValueError(f"invalid float env var {name}: {raw}") from exc


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean env var {name}: {raw}")


@dataclass(frozen=True, slots=True)
class Settings:
    # Canonical chat path in agent-api.
    agent_api_base_url: str = "http://agent-api:8080"
    agent_api_key: str = ""
    agent_api_model: str = "assistant-fast"

    # Telegram bot credentials and webhook guard.
    telegram_bot_token: str = ""
    telegram_webhook_secret_token: str = ""
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_webhook_url: str = ""

    # Endpoint-level behavior.
    webhook_path: str = "/webhook"
    request_timeout_seconds: float = 5.0

    telegram_polling_enabled: bool = False
    telegram_polling_timeout_seconds: int = 30
    telegram_polling_batch_size: int = 100

    # Idempotency control.
    dedupe_window_seconds: float = 3600.0
    dedupe_max_events: int = 1024

    # Optional operational guardrails.
    max_reply_chars: int = 4096

    def is_operational(self) -> bool:
        return bool(self.telegram_bot_token and self.agent_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings(
        agent_api_base_url=(os.getenv("AGENT_API_BASE_URL", "http://agent-api:8080").strip()),
        agent_api_key=_strip_secret(os.getenv("AGENT_API_KEY", "")),
        agent_api_model=os.getenv("AGENT_API_MODEL", "assistant-fast").strip(),
        telegram_bot_token=_strip_secret(os.getenv("TELEGRAM_BOT_TOKEN", "")),
        telegram_webhook_secret_token=_strip_secret(os.getenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "")),
        telegram_api_base_url=os.getenv("TELEGRAM_API_BASE_URL", "https://api.telegram.org").strip(),
        telegram_webhook_url=os.getenv("TELEGRAM_WEBHOOK_URL", "").strip(),
        webhook_path=_normalize_webhook_path(
            os.getenv("TELEGRAM_WEBHOOK_PATH", "/webhook"),
        ),
        request_timeout_seconds=_get_float_env("TELEGRAM_REQUEST_TIMEOUT_SECONDS", 5.0),
        telegram_polling_enabled=_get_bool_env("TELEGRAM_POLLING_ENABLED", False),
        telegram_polling_timeout_seconds=_get_int_env("TELEGRAM_POLLING_TIMEOUT_SECONDS", 30),
        telegram_polling_batch_size=_get_int_env("TELEGRAM_POLLING_BATCH_SIZE", 100),
        dedupe_window_seconds=_get_float_env("TELEGRAM_DEDUP_WINDOW_SECONDS", 3600.0),
        dedupe_max_events=_get_int_env("TELEGRAM_DEDUP_MAX_EVENTS", 1024),
        max_reply_chars=_get_int_env("TELEGRAM_MAX_REPLY_CHARS", 4096),
    )
