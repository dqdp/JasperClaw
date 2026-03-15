from pathlib import Path

import pytest

from shared_infra.household_config import (
    HouseholdConfigSelection,
    load_household_config,
    resolve_household_config,
)


def _write_household(
    path: Path,
    *,
    trusted_chat_ids: str = "123456789",
    alias_name: str = "wife",
    chat_id: str = "111111111",
    description: str = "Personal chat",
) -> None:
    path.write_text(
        (
            "[telegram]\n"
            f"trusted_chat_ids = [{trusted_chat_ids}]\n\n"
            f"[telegram.aliases.{alias_name}]\n"
            f"chat_id = {chat_id}\n"
            f'description = "{description}"\n'
        )
    )


def test_load_household_config_parses_trusted_chats_and_aliases(tmp_path) -> None:
    config_path = tmp_path / "household.toml"
    _write_household(config_path)

    config = load_household_config(config_path)

    assert config.trusted_chat_ids == (123456789,)
    assert tuple(config.aliases) == ("wife",)
    assert config.aliases["wife"].chat_id == 111111111
    assert config.aliases["wife"].description == "Personal chat"


def test_load_household_config_rejects_duplicate_trusted_chat_ids(tmp_path) -> None:
    config_path = tmp_path / "household.toml"
    _write_household(config_path, trusted_chat_ids="123456789, 123456789")

    with pytest.raises(RuntimeError, match="duplicate trusted chat ids"):
        load_household_config(config_path)


def test_load_household_config_rejects_malformed_alias_keys(tmp_path) -> None:
    config_path = tmp_path / "household.toml"
    _write_household(config_path, alias_name="Wife")

    with pytest.raises(RuntimeError, match="invalid alias key"):
        load_household_config(config_path)


def test_load_household_config_rejects_missing_alias_description(tmp_path) -> None:
    config_path = tmp_path / "household.toml"
    config_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
""".strip()
    )

    with pytest.raises(RuntimeError, match="alias description"):
        load_household_config(config_path)


def test_resolve_household_config_prefers_real_over_demo(tmp_path) -> None:
    real_path = tmp_path / "household.toml"
    demo_path = tmp_path / "household.demo.toml"
    _write_household(real_path, alias_name="wife", description="Real contact")
    _write_household(demo_path, alias_name="demo_home", description="Demo alias")

    selection = resolve_household_config(
        real_path=real_path,
        demo_path=demo_path,
    )

    assert selection == HouseholdConfigSelection(
        mode="real",
        config=load_household_config(real_path),
    )


def test_resolve_household_config_returns_none_when_both_paths_missing(tmp_path) -> None:
    assert (
        resolve_household_config(
            real_path=tmp_path / "household.toml",
            demo_path=tmp_path / "household.demo.toml",
        )
        is None
    )
