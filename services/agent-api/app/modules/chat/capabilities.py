from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.config import Settings
from shared_infra.household_config import resolve_household_config

CapabilityState = Literal["demo", "real", "unconfigured"]


@dataclass(frozen=True, slots=True)
class CapabilityDiscoveryEntry:
    id: str
    label: str
    state: CapabilityState


@dataclass(frozen=True, slots=True)
class CapabilityDiscoverySnapshot:
    capabilities: tuple[CapabilityDiscoveryEntry, ...]
    commands: tuple[str, ...]
    help_text: str
    status_text: str

    def as_dict(self) -> dict[str, object]:
        return {
            "capabilities": [
                {
                    "id": capability.id,
                    "label": capability.label,
                    "state": capability.state,
                }
                for capability in self.capabilities
            ],
            "commands": list(self.commands),
            "help_text": self.help_text,
            "status_text": self.status_text,
        }


def build_capability_discovery_snapshot(
    *,
    capabilities: tuple[CapabilityDiscoveryEntry, ...],
    commands: tuple[str, ...],
) -> CapabilityDiscoverySnapshot:
    status_text = "\n".join(
        f"{capability.label}: {_state_label(capability.state)}"
        for capability in capabilities
    )
    state_summary = "; ".join(
        f"{capability.label} is {_state_label(capability.state)}"
        for capability in capabilities
    )
    help_text = (
        "I can answer questions, talk by voice when enabled, help with Spotify "
        "playback, and send Telegram messages to configured aliases.\n"
        f"Current state: {state_summary}.\n"
        f"Commands: {', '.join(commands)}"
    )
    return CapabilityDiscoverySnapshot(
        capabilities=capabilities,
        commands=commands,
        help_text=help_text,
        status_text=status_text,
    )


def resolve_capability_discovery(settings: Settings) -> CapabilityDiscoverySnapshot:
    telegram_state = _resolve_telegram_household_state(settings)
    capabilities = (
        CapabilityDiscoveryEntry(
            id="voice",
            label="Voice conversation",
            state="real" if settings.voice_enabled else "unconfigured",
        ),
        CapabilityDiscoveryEntry(
            id="spotify_playback",
            label="Spotify playback",
            state="real"
            if settings.is_spotify_real_configured()
            else "unconfigured",
        ),
        CapabilityDiscoveryEntry(
            id="spotify_station",
            label="Spotify station",
            # Station discovery exists in the product contract before the execution
            # path lands; keep the state honest until the typed capability exists.
            state="unconfigured",
        ),
        CapabilityDiscoveryEntry(
            id="telegram_send",
            label="Telegram send",
            state=telegram_state,
        ),
    )
    return build_capability_discovery_snapshot(
        capabilities=capabilities,
        commands=("/help", "/status", "/ask <message>"),
    )


def _state_label(state: CapabilityState) -> str:
    if state == "real":
        return "connected"
    if state == "demo":
        return "demo"
    return "not configured"


def _resolve_telegram_household_state(settings: Settings) -> CapabilityState:
    selection = resolve_household_config(
        real_path=_optional_path(settings.household_config_path),
        demo_path=_optional_path(settings.demo_household_config_path),
    )
    if selection is None:
        return "unconfigured"
    return "real" if selection.mode == "real" else "demo"


def _optional_path(raw_path: str) -> Path | None:
    normalized = raw_path.strip()
    if not normalized:
        return None
    return Path(normalized)
