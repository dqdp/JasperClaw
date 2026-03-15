from __future__ import annotations

from pathlib import Path
from typing import Literal

from app.core.config import Settings
from shared_infra.household_config import HouseholdConfigSelection, resolve_household_config

TelegramSendState = Literal["demo", "real", "unconfigured"]


def resolve_household_selection(
    settings: Settings,
) -> HouseholdConfigSelection | None:
    return resolve_household_config(
        real_path=_optional_path(settings.household_config_path),
        demo_path=_optional_path(settings.demo_household_config_path),
    )


def resolve_telegram_send_state(settings: Settings) -> TelegramSendState:
    selection = resolve_household_selection(settings)
    if selection is None:
        return "unconfigured"
    if selection.mode == "demo":
        return "demo"
    return "real" if settings.telegram_bot_token else "unconfigured"


def is_telegram_send_available(settings: Settings) -> bool:
    return resolve_telegram_send_state(settings) != "unconfigured"


def _optional_path(raw_path: str) -> Path | None:
    normalized = raw_path.strip()
    if not normalized:
        return None
    return Path(normalized)
