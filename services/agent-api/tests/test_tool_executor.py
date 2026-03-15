from app.clients.search import WebSearchResultItem
from app.clients.spotify import SpotifyPlaylistItem, SpotifyTrackItem
from app.core.config import Settings
from app.core.errors import APIError
from app.modules.chat.executor import ToolContext, ToolExecutor
from app.modules.chat.formatters import ChatPromptFormatter
from app.modules.chat.planner import ToolPlanningDecision
from app.modules.chat.policy import ToolPolicyEngine
from app.schemas.chat import ChatMessage


class _FakeSearchClient:
    def __init__(
        self,
        *,
        results: list[object] | None = None,
        error: APIError | None = None,
    ) -> None:
        self.results = results or []
        self.error = error
        self.calls: list[dict[str, object]] = []

    def search(self, *, query: str, limit: int):
        self.calls.append({"query": query, "limit": limit})
        if self.error is not None:
            raise self.error
        return list(self.results)


class _FakeSpotifyClient:
    def __init__(self) -> None:
        self.list_calls: list[dict[str, object]] = []
        self.search_calls: list[dict[str, object]] = []
        self.play_calls: list[dict[str, object]] = []
        self.play_playlist_calls: list[dict[str, object]] = []
        self.start_station_calls: list[dict[str, object]] = []

    def list_playlists(self, *, limit: int) -> list[SpotifyPlaylistItem]:
        self.list_calls.append({"limit": limit})
        return [
            SpotifyPlaylistItem(
                name="Focus Flow",
                owner="Alex",
                uri="spotify:playlist:001",
                external_url="https://open.spotify.com/playlist/001",
            )
        ]

    def search_tracks(self, *, query: str, limit: int) -> list[SpotifyTrackItem]:
        self.search_calls.append({"query": query, "limit": limit})
        return [
            SpotifyTrackItem(
                name="Lofi Track",
                artists="DJ Test",
                uri="spotify:track:001",
                album="Focus",
                external_url="https://open.spotify.com/track/001",
            )
        ]

    def play_track(self, *, track_uri: str, device_id: str | None = None) -> None:
        self.play_calls.append({"track_uri": track_uri, "device_id": device_id})

    def play_playlist(self, *, playlist_uri: str, device_id: str | None = None) -> None:
        self.play_playlist_calls.append(
            {"playlist_uri": playlist_uri, "device_id": device_id}
        )

    def start_station(
        self,
        *,
        seed_kind: str,
        seed_value: str,
        limit: int,
        device_id: str | None = None,
    ) -> None:
        self.start_station_calls.append(
            {
                "seed_kind": seed_kind,
                "seed_value": seed_value,
                "limit": limit,
                "device_id": device_id,
            }
        )

    def pause_playback(self, *, device_id: str | None = None) -> None:
        raise AssertionError("unexpected pause")

    def next_track(self, *, device_id: str | None = None) -> None:
        raise AssertionError("unexpected next")


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_message(self, *, chat_id: int, text: str) -> None:
        self.calls.append({"chat_id": chat_id, "text": text})


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ollama_base_url": "http://ollama:11434",
        "ollama_chat_model": "qwen3:8b",
        "ollama_fast_chat_model": "qwen3:8b",
        "ollama_timeout_seconds": 30.0,
        "database_url": "postgresql://assistant:change-me@postgres:5432/assistant",
        "internal_openai_api_key": "secret",
        "web_search_enabled": True,
        "spotify_access_token": "token",
        "spotify_playlist_top_k": 5,
        "spotify_station_top_k": 20,
        "spotify_demo_enabled": False,
        "telegram_bot_token": "telegram-bot-token",
        "telegram_api_base_url": "https://api.telegram.org",
    }
    base.update(overrides)
    return Settings(**base)


def test_tool_executor_denies_policy_blocked_tools_with_annotation() -> None:
    settings = _settings(web_search_enabled=True)
    policy = ToolPolicyEngine(
        settings=settings,
        web_search_adapter_available=True,
    )
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=_FakeSpotifyClient(),
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=policy,
    )

    context = executor.execute(
        request_id="req_1",
        base_messages=[ChatMessage(role="user", content="latest updates")],
        decision=ToolPlanningDecision(
            tool_name="web-search",
            arguments={"query": "latest updates"},
        ),
        annotate_failures=True,
        request_source="telegram",
    )

    assert isinstance(context, ToolContext)
    assert context.execution is not None
    assert context.execution.status == "failed"
    assert context.execution.error_code == "tool_not_allowed"
    assert "Web search was requested but is currently unavailable." in context.runtime_messages[0].content


def test_tool_executor_executes_web_search_and_augments_prompt() -> None:
    settings = _settings(web_search_enabled=True)
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(
            results=[
                WebSearchResultItem(
                    title="Release notes",
                    url="https://example.com/release",
                    snippet="Recent changes",
                )
            ]
        ),
        spotify_client=_FakeSpotifyClient(),
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_2",
        base_messages=[ChatMessage(role="user", content="latest updates")],
        decision=ToolPlanningDecision(
            tool_name="web-search",
            arguments={"query": "latest updates"},
        ),
        annotate_failures=False,
        request_source=None,
    )

    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output is not None
    assert context.execution.output["results"][0]["url"] == "https://example.com/release"
    assert "Relevant web search results" in context.runtime_messages[0].content


def test_tool_executor_executes_spotify_play_action() -> None:
    settings = _settings()
    spotify_client = _FakeSpotifyClient()
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=spotify_client,
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_3",
        base_messages=[ChatMessage(role="user", content="play lofi")],
        decision=ToolPlanningDecision(
            tool_name="spotify-play",
            arguments={"track_uri": "spotify:track:001", "device_id": "phone"},
        ),
        annotate_failures=True,
        request_source=None,
    )

    assert spotify_client.play_calls == [
        {"track_uri": "spotify:track:001", "device_id": "phone"}
    ]
    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output == {"status": "ok"}
    assert "Spotify action completed: spotify-play." in context.runtime_messages[0].content


def test_tool_executor_executes_spotify_playlist_listing() -> None:
    settings = _settings(
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        spotify_redirect_uri="http://assistant.test/callback",
        spotify_refresh_token="refresh-token",
    )
    spotify_client = _FakeSpotifyClient()
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=spotify_client,
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_3a",
        base_messages=[ChatMessage(role="user", content="what playlists do I have?")],
        decision=ToolPlanningDecision(
            tool_name="spotify-list-playlists",
            arguments={},
        ),
        annotate_failures=False,
        request_source=None,
    )

    assert spotify_client.list_calls == [{"limit": 5}]
    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output == {
        "results": [
            {
                "name": "Focus Flow",
                "owner": "Alex",
                "uri": "spotify:playlist:001",
                "external_url": "https://open.spotify.com/playlist/001",
            }
        ]
    }
    assert "Available Spotify playlists" in context.runtime_messages[0].content


def test_tool_executor_executes_spotify_playlist_listing_in_demo_mode() -> None:
    settings = _settings(
        spotify_access_token="",
        spotify_demo_enabled=True,
    )
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=None,
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_spotify_demo_list",
        base_messages=[ChatMessage(role="user", content="what playlists do I have?")],
        decision=ToolPlanningDecision(
            tool_name="spotify-list-playlists",
            arguments={},
        ),
        annotate_failures=False,
        request_source=None,
    )

    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output == {
        "mode": "demo",
        "results": [
            {
                "name": "Focus Flow",
                "owner": "Assistant demo",
                "uri": "spotify:playlist:demo-focus-flow",
                "external_url": None,
            },
            {
                "name": "Energy Kick",
                "owner": "Assistant demo",
                "uri": "spotify:playlist:demo-energy-kick",
                "external_url": None,
            },
        ],
    }
    assert "Available Spotify playlists (demo)" in context.runtime_messages[0].content


def test_tool_executor_executes_telegram_send_in_demo_mode(tmp_path) -> None:
    demo_path = tmp_path / "household.demo.toml"
    demo_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
""".strip()
    )
    settings = _settings(
        household_config_path="",
        demo_household_config_path=str(demo_path),
    )
    telegram_client = _FakeTelegramClient()
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=_FakeSpotifyClient(),
        telegram_client=telegram_client,
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_tg_demo",
        base_messages=[ChatMessage(role="user", content="send wife hello")],
        decision=ToolPlanningDecision(
            tool_name="telegram-send",
            arguments={"alias": "wife", "text": "hello"},
        ),
        annotate_failures=False,
        request_source=None,
    )

    assert telegram_client.calls == []
    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output == {"status": "demo", "alias": "wife"}


def test_tool_executor_executes_telegram_send_in_real_mode(tmp_path) -> None:
    household_path = tmp_path / "household.toml"
    household_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
""".strip()
    )
    settings = _settings(
        household_config_path=str(household_path),
        demo_household_config_path="",
    )
    telegram_client = _FakeTelegramClient()
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=_FakeSpotifyClient(),
        telegram_client=telegram_client,
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_tg_real",
        base_messages=[ChatMessage(role="user", content="send wife hello")],
        decision=ToolPlanningDecision(
            tool_name="telegram-send",
            arguments={"alias": "wife", "text": "hello"},
        ),
        annotate_failures=False,
        request_source=None,
    )

    assert telegram_client.calls == [{"chat_id": 111111111, "text": "hello"}]
    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output == {"status": "ok", "alias": "wife"}


def test_tool_executor_executes_spotify_playlist_playback() -> None:
    settings = _settings(
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        spotify_redirect_uri="http://assistant.test/callback",
        spotify_refresh_token="refresh-token",
    )
    spotify_client = _FakeSpotifyClient()
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=spotify_client,
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_3b",
        base_messages=[ChatMessage(role="user", content="play my focus flow playlist")],
        decision=ToolPlanningDecision(
            tool_name="spotify-play-playlist",
            arguments={"playlist_name": "Focus Flow", "device_id": "speaker"},
        ),
        annotate_failures=False,
        request_source=None,
    )

    assert spotify_client.list_calls == [{"limit": 5}]
    assert spotify_client.play_playlist_calls == [
        {"playlist_uri": "spotify:playlist:001", "device_id": "speaker"}
    ]
    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output == {"status": "ok"}
    assert "Spotify action completed: spotify-play-playlist." in context.runtime_messages[0].content


def test_tool_executor_executes_spotify_playlist_playback_in_demo_mode() -> None:
    settings = _settings(
        spotify_access_token="",
        spotify_demo_enabled=True,
    )
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=None,
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_spotify_demo_play",
        base_messages=[ChatMessage(role="user", content="play focus flow")],
        decision=ToolPlanningDecision(
            tool_name="spotify-play-playlist",
            arguments={"playlist_name": "Focus Flow"},
        ),
        annotate_failures=False,
        request_source=None,
    )

    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output == {"status": "demo"}
    assert "Spotify demo action completed: spotify-play-playlist." in (
        context.runtime_messages[0].content
    )


def test_tool_executor_executes_spotify_station_start() -> None:
    settings = _settings(
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        spotify_redirect_uri="http://assistant.test/callback",
        spotify_refresh_token="refresh-token",
    )
    spotify_client = _FakeSpotifyClient()
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=spotify_client,
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_3c",
        base_messages=[ChatMessage(role="user", content="play something energetic")],
        decision=ToolPlanningDecision(
            tool_name="spotify-start-station",
            arguments={
                "seed_kind": "mood",
                "seed_value": "energy",
                "device_id": "speaker",
            },
        ),
        annotate_failures=False,
        request_source=None,
    )

    assert spotify_client.start_station_calls == [
        {
            "seed_kind": "mood",
            "seed_value": "energy",
            "limit": 20,
            "device_id": "speaker",
        }
    ]
    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output == {"status": "ok"}
    assert "Spotify action completed: spotify-start-station." in context.runtime_messages[0].content


def test_tool_executor_executes_spotify_station_start_in_demo_mode() -> None:
    settings = _settings(
        spotify_access_token="",
        spotify_demo_enabled=True,
    )
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=None,
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_spotify_demo_station",
        base_messages=[ChatMessage(role="user", content="play something energetic")],
        decision=ToolPlanningDecision(
            tool_name="spotify-start-station",
            arguments={"seed_kind": "mood", "seed_value": "energy"},
        ),
        annotate_failures=False,
        request_source=None,
    )

    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output == {
        "status": "demo",
        "seed_kind": "mood",
        "seed_value": "energy",
    }
    assert "Spotify demo action completed: spotify-start-station." in (
        context.runtime_messages[0].content
    )


def test_tool_executor_executes_telegram_alias_listing(tmp_path) -> None:
    household_path = tmp_path / "household.toml"
    household_path.write_text(
        """
[telegram]
trusted_chat_ids = [123456789]

[telegram.aliases.wife]
chat_id = 111111111
description = "Personal chat"
""".strip()
    )
    settings = _settings(household_config_path=str(household_path))
    executor = ToolExecutor(
        settings=settings,
        web_search_client=_FakeSearchClient(),
        spotify_client=_FakeSpotifyClient(),
        prompt_formatter=ChatPromptFormatter(),
        policy_engine=ToolPolicyEngine(
            settings=settings,
            web_search_adapter_available=True,
        ),
    )

    context = executor.execute(
        request_id="req_3d",
        base_messages=[ChatMessage(role="user", content="what aliases do I have?")],
        decision=ToolPlanningDecision(
            tool_name="telegram-list-aliases",
            arguments={},
        ),
        annotate_failures=False,
        request_source=None,
    )

    assert context.execution is not None
    assert context.execution.status == "completed"
    assert context.execution.output == {
        "results": [
            {
                "alias": "wife",
                "description": "Personal chat",
            }
        ]
    }
    assert "Available Telegram aliases" in context.runtime_messages[0].content
