from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from shared_infra.household_config import HouseholdConfigSelection, resolve_household_config


def resolve_household_selection(
    settings: Settings,
) -> HouseholdConfigSelection | None:
    return resolve_household_config(
        real_path=_optional_path(settings.household_config_path),
        demo_path=_optional_path(settings.demo_household_config_path),
    )


def _optional_path(raw_path: str) -> Path | None:
    normalized = raw_path.strip()
    if not normalized:
        return None
    return Path(normalized)
