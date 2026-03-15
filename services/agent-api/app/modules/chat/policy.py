from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.modules.chat.household import (
    is_telegram_send_available,
    resolve_household_selection,
)
from app.modules.chat.planner import SUPPORTED_TOOL_NAMES


@dataclass(frozen=True, slots=True)
class ToolPolicyDecision:
    allowed: bool
    policy_decision: str
    error_type: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    adapter_name: str | None = None
    provider: str | None = None


class ToolPolicyEngine:
    """Owns pure deployment and source-based tool access policy."""

    def __init__(
        self,
        *,
        settings: Settings,
        web_search_adapter_available: bool,
    ) -> None:
        self._settings = settings
        self._web_search_adapter_available = web_search_adapter_available

    def evaluate(
        self,
        tool_name: str,
        *,
        request_source: str | None = None,
    ) -> ToolPolicyDecision:
        normalized_tool = tool_name.strip().casefold()

        if normalized_tool not in SUPPORTED_TOOL_NAMES:
            return ToolPolicyDecision(
                allowed=False,
                policy_decision="deny",
                error_type="policy_error",
                error_code="tool_not_allowed",
                error_message=(
                    f"Tool '{normalized_tool}' is not declared in the policy catalog."
                ),
            )

        if request_source == "telegram":
            return ToolPolicyDecision(
                allowed=False,
                policy_decision="deny",
                error_type="policy_error",
                error_code="tool_not_allowed",
                error_message=(
                    f"Tool '{normalized_tool}' is blocked for Telegram-originated "
                    "requests."
                ),
                adapter_name=(
                    "search-http" if normalized_tool == "web-search" else "spotify-http"
                ),
                provider=(
                    "search-provider"
                    if normalized_tool == "web-search"
                    else "spotify"
                ),
            )

        if request_source == "telegram_command":
            if normalized_tool not in {"telegram-send", "telegram-list-aliases"}:
                return ToolPolicyDecision(
                    allowed=False,
                    policy_decision="deny",
                    error_type="policy_error",
                    error_code="tool_not_allowed",
                    error_message=(
                        f"Tool '{normalized_tool}' is blocked for Telegram command "
                        "requests."
                    ),
                    adapter_name=(
                        "search-http"
                        if normalized_tool == "web-search"
                        else "spotify-http"
                    ),
                    provider=(
                        "search-provider"
                        if normalized_tool == "web-search"
                        else "spotify"
                    ),
                )

        if normalized_tool == "web-search":
            if not self._settings.web_search_enabled:
                return ToolPolicyDecision(
                    allowed=False,
                    policy_decision="deny",
                    error_type="policy_error",
                    error_code="tool_not_allowed",
                    error_message=(
                        "web-search is currently disabled by deployment policy."
                    ),
                    adapter_name="search-http",
                    provider="search-provider",
                )
            if not self._web_search_adapter_available:
                return ToolPolicyDecision(
                    allowed=False,
                    policy_decision="deny",
                    error_type="policy_error",
                    error_code="tool_not_allowed",
                    error_message=(
                        "web-search is currently unavailable because the adapter is "
                        "not configured."
                    ),
                    adapter_name="search-http",
                    provider="search-provider",
                )
            return ToolPolicyDecision(
                allowed=True,
                policy_decision="allow",
                adapter_name="search-http",
                provider="search-provider",
            )

        if normalized_tool in {"telegram-list-aliases", "telegram-send"}:
            selection = resolve_household_selection(self._settings)
            if selection is None:
                return ToolPolicyDecision(
                    allowed=False,
                    policy_decision="deny",
                    error_type="policy_error",
                    error_code="tool_not_allowed",
                    error_message=(
                        f"{normalized_tool} is unavailable because the household "
                        "config is not configured."
                    ),
                    adapter_name=(
                        "telegram-config"
                        if normalized_tool == "telegram-list-aliases"
                        else "telegram-bot-api"
                    ),
                    provider="telegram",
                )
            if normalized_tool == "telegram-send" and not is_telegram_send_available(
                self._settings
            ):
                return ToolPolicyDecision(
                    allowed=False,
                    policy_decision="deny",
                    error_type="policy_error",
                    error_code="tool_not_allowed",
                    error_message=(
                        "telegram-send is unavailable because Telegram Bot API is "
                        "not configured."
                    ),
                    adapter_name="telegram-bot-api",
                    provider="telegram",
                )
            return ToolPolicyDecision(
                allowed=True,
                policy_decision="allow",
                adapter_name=(
                    "telegram-config"
                    if normalized_tool == "telegram-list-aliases"
                    else "telegram-bot-api"
                ),
                provider="telegram",
            )

        if normalized_tool in {
            "spotify-list-playlists",
            "spotify-play-playlist",
            "spotify-start-station",
        }:
            if self._settings.is_spotify_real_configured():
                return ToolPolicyDecision(
                    allowed=True,
                    policy_decision="allow",
                    adapter_name="spotify-http",
                    provider="spotify",
                )
            if self._settings.is_spotify_demo_configured():
                return ToolPolicyDecision(
                    allowed=True,
                    policy_decision="allow",
                    adapter_name="spotify-demo",
                    provider="spotify",
                )
            else:
                return ToolPolicyDecision(
                    allowed=False,
                    policy_decision="deny",
                    error_type="policy_error",
                    error_code="tool_not_allowed",
                    error_message=(
                        f"{normalized_tool} is unavailable because the real "
                        "Spotify baseline is not configured."
                    ),
                    adapter_name="spotify-http",
                    provider="spotify",
                )

        if not self._settings.is_spotify_client_configured():
            return ToolPolicyDecision(
                allowed=False,
                policy_decision="deny",
                error_type="policy_error",
                error_code="tool_not_allowed",
                error_message=(
                    "Spotify tools are currently unavailable because they are not "
                    "configured."
                ),
                adapter_name="spotify-http",
                provider="spotify",
            )

        return ToolPolicyDecision(
            allowed=True,
            policy_decision="allow",
            adapter_name="spotify-http",
            provider="spotify",
        )
