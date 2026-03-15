from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import APIError
from app.modules.chat.household import resolve_household_selection


@dataclass(frozen=True, slots=True)
class ResolvedTelegramSend:
    alias: str
    text: str
    chat_id: int
    mode: str


def resolve_telegram_send(
    *,
    settings: Settings,
    arguments: dict[str, object],
) -> ResolvedTelegramSend:
    selection = resolve_household_selection(settings)
    if selection is None:
        raise APIError(
            status_code=400,
            error_type="validation_error",
            code="invalid_request",
            message="Telegram household config is not configured",
        )

    alias_value = arguments.get("alias")
    if not isinstance(alias_value, str) or not alias_value.strip():
        raise APIError(
            status_code=400,
            error_type="validation_error",
            code="invalid_request",
            message="telegram-send requires a configured alias",
        )
    alias = alias_value.strip().casefold()
    alias_config = selection.config.aliases.get(alias)
    if alias_config is None:
        raise APIError(
            status_code=400,
            error_type="validation_error",
            code="invalid_request",
            message="Requested Telegram alias was not found",
        )

    text_value = arguments.get("text")
    if not isinstance(text_value, str) or not text_value.strip():
        raise APIError(
            status_code=400,
            error_type="validation_error",
            code="invalid_request",
            message="telegram-send requires non-empty text",
        )
    text = text_value.strip()

    return ResolvedTelegramSend(
        alias=alias,
        text=text,
        chat_id=alias_config.chat_id,
        mode=selection.mode,
    )
