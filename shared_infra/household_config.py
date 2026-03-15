from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib


_ALIAS_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class TelegramAliasConfig:
    chat_id: int
    description: str


@dataclass(frozen=True, slots=True)
class HouseholdConfig:
    trusted_chat_ids: tuple[int, ...]
    aliases: dict[str, TelegramAliasConfig]


@dataclass(frozen=True, slots=True)
class HouseholdConfigSelection:
    mode: str
    config: HouseholdConfig


def load_household_config(path: Path) -> HouseholdConfig:
    data = tomllib.loads(path.read_text())
    telegram = data.get("telegram")
    if not isinstance(telegram, dict):
        raise RuntimeError("Household config is invalid: missing telegram section")

    raw_trusted_chat_ids = telegram.get("trusted_chat_ids")
    if not isinstance(raw_trusted_chat_ids, list):
        raise RuntimeError("Household config is invalid: trusted chat ids missing")
    trusted_chat_ids = _normalize_trusted_chat_ids(raw_trusted_chat_ids)

    raw_aliases = telegram.get("aliases", {})
    if not isinstance(raw_aliases, dict):
        raise RuntimeError("Household config is invalid: aliases table missing")

    aliases: dict[str, TelegramAliasConfig] = {}
    for alias_key, raw_alias in raw_aliases.items():
        if not isinstance(alias_key, str) or not _ALIAS_KEY_PATTERN.fullmatch(alias_key):
            raise RuntimeError("Household config is invalid: invalid alias key")
        if not isinstance(raw_alias, dict):
            raise RuntimeError("Household config is invalid: alias entry missing")
        chat_id = raw_alias.get("chat_id")
        if not isinstance(chat_id, int) or isinstance(chat_id, bool) or chat_id <= 0:
            raise RuntimeError("Household config is invalid: alias chat_id missing")
        description = raw_alias.get("description")
        if not isinstance(description, str) or not description.strip():
            raise RuntimeError("Household config is invalid: alias description missing")
        aliases[alias_key] = TelegramAliasConfig(
            chat_id=chat_id,
            description=description.strip(),
        )

    return HouseholdConfig(
        trusted_chat_ids=trusted_chat_ids,
        aliases=aliases,
    )


def resolve_household_config(
    *,
    real_path: Path | None,
    demo_path: Path | None,
) -> HouseholdConfigSelection | None:
    # Real household config always wins over demo so the runtime cannot silently
    # downgrade a configured installation into demo behavior.
    if real_path is not None and real_path.exists():
        return HouseholdConfigSelection(
            mode="real",
            config=load_household_config(real_path),
        )
    if demo_path is not None and demo_path.exists():
        return HouseholdConfigSelection(
            mode="demo",
            config=load_household_config(demo_path),
        )
    return None


def _normalize_trusted_chat_ids(raw_values: list[object]) -> tuple[int, ...]:
    normalized: list[int] = []
    seen: set[int] = set()
    for raw_value in raw_values:
        if not isinstance(raw_value, int) or isinstance(raw_value, bool) or raw_value <= 0:
            raise RuntimeError("Household config is invalid: trusted chat ids invalid")
        if raw_value in seen:
            raise RuntimeError("Household config is invalid: duplicate trusted chat ids")
        seen.add(raw_value)
        normalized.append(raw_value)
    return tuple(normalized)
