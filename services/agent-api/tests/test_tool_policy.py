from app.core.config import Settings
from app.modules.chat.policy import ToolPolicyEngine


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ollama_base_url": "http://ollama:11434",
        "ollama_chat_model": "qwen3:8b",
        "ollama_fast_chat_model": "qwen3:8b",
        "ollama_timeout_seconds": 30.0,
        "database_url": "postgresql://assistant:change-me@postgres:5432/assistant",
        "internal_openai_api_key": "secret",
        "web_search_enabled": False,
        "spotify_access_token": "",
        "spotify_client_id": "",
        "spotify_client_secret": "",
    }
    base.update(overrides)
    return Settings(**base)


def test_tool_policy_denies_unknown_and_telegram_origin_tools() -> None:
    engine = ToolPolicyEngine(
        settings=_settings(web_search_enabled=True),
        web_search_adapter_available=True,
    )

    unknown = engine.evaluate("made-up-tool")
    blocked = engine.evaluate("web-search", request_source="telegram")

    assert unknown.allowed is False
    assert unknown.error_code == "tool_not_allowed"
    assert blocked.allowed is False
    assert blocked.adapter_name == "search-http"
    assert blocked.provider == "search-provider"


def test_tool_policy_denies_disabled_or_unconfigured_web_search() -> None:
    disabled = ToolPolicyEngine(
        settings=_settings(web_search_enabled=False),
        web_search_adapter_available=True,
    ).evaluate("web-search")
    missing_adapter = ToolPolicyEngine(
        settings=_settings(web_search_enabled=True),
        web_search_adapter_available=False,
    ).evaluate("web-search")

    assert disabled.allowed is False
    assert "disabled" in (disabled.error_message or "")
    assert missing_adapter.allowed is False
    assert "not configured" in (missing_adapter.error_message or "")


def test_tool_policy_allows_configured_web_search_and_spotify() -> None:
    web_search = ToolPolicyEngine(
        settings=_settings(web_search_enabled=True),
        web_search_adapter_available=True,
    ).evaluate("web-search")
    spotify = ToolPolicyEngine(
        settings=_settings(spotify_access_token="token"),
        web_search_adapter_available=False,
    ).evaluate("spotify-play")

    assert web_search.allowed is True
    assert web_search.adapter_name == "search-http"
    assert spotify.allowed is True
    assert spotify.adapter_name == "spotify-http"


def test_tool_policy_requires_real_spotify_bootstrap_for_playlist_listing() -> None:
    denied = ToolPolicyEngine(
        settings=_settings(spotify_access_token="token"),
        web_search_adapter_available=False,
    ).evaluate("spotify-list-playlists")
    denied_play = ToolPolicyEngine(
        settings=_settings(spotify_access_token="token"),
        web_search_adapter_available=False,
    ).evaluate("spotify-play-playlist")
    allowed = ToolPolicyEngine(
        settings=_settings(
            spotify_client_id="client-id",
            spotify_client_secret="client-secret",
            spotify_redirect_uri="http://assistant.test/callback",
            spotify_refresh_token="refresh-token",
        ),
        web_search_adapter_available=False,
    ).evaluate("spotify-list-playlists")

    assert denied.allowed is False
    assert "real Spotify baseline" in (denied.error_message or "")
    assert denied_play.allowed is False
    assert allowed.allowed is True
    assert allowed.adapter_name == "spotify-http"
