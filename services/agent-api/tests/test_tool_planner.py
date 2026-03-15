from app.modules.chat.planner import (
    SUPPORTED_TOOL_NAMES,
    ToolPlanner,
    ToolPlanningDecision,
)
from app.schemas.chat import ChatCompletionRequest, ChatMessage


def _request(
    *,
    metadata: dict[str, str] | None = None,
    messages: list[ChatMessage] | None = None,
) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="assistant-fast",
        messages=messages
        or [ChatMessage(role="user", content="Find recent updates about Postgres")],
        metadata=metadata,
    )


def test_tool_planner_respects_explicit_web_search_metadata() -> None:
    planner = ToolPlanner(web_search_available=True, spotify_available=True)
    request = _request(metadata={"web_search": "true"})

    assert planner.is_web_search_requested(request) is True
    assert planner.should_attempt_model_driven_tool_use(request) is False


def test_tool_planner_requires_available_tools_and_user_message() -> None:
    planner = ToolPlanner(web_search_available=False, spotify_available=False)

    assert planner.should_attempt_model_driven_tool_use(_request()) is False
    assert (
        ToolPlanner(web_search_available=True, spotify_available=False)
        .should_attempt_model_driven_tool_use(
            _request(messages=[ChatMessage(role="system", content="only system")])
        )
        is False
    )


def test_tool_planner_builds_prompt_after_existing_system_messages() -> None:
    planner = ToolPlanner(
        web_search_available=True,
        spotify_available=True,
        spotify_real_available=True,
    )

    messages = planner.build_planning_messages(
        [
            ChatMessage(role="system", content="existing system"),
            ChatMessage(role="user", content="play music"),
        ]
    )

    assert messages[0].content == "existing system"
    assert messages[1].role == "system"
    assert '{"tool":"web-search","query":"..."}' in messages[1].content
    assert '{"tool":"spotify-play","track_uri":"..."}' in messages[1].content
    assert '{"tool":"spotify-list-playlists"}' in messages[1].content
    assert '{"tool":"spotify-play-playlist","playlist_name":"..."}' in messages[1].content


def test_tool_planner_parses_supported_directives() -> None:
    planner = ToolPlanner(
        web_search_available=True,
        spotify_available=True,
        spotify_real_available=True,
    )

    assert planner.parse_decision('{"tool":"web-search","query":"  weather  "}') == (
        ToolPlanningDecision(
            tool_name="web-search",
            arguments={"query": "weather"},
        )
    )
    assert planner.parse_decision(
        '{"tool":"spotify-play","uri":" spotify:track:123 ","device_id":"phone"}'
    ) == ToolPlanningDecision(
        tool_name="spotify-play",
        arguments={
            "track_uri": "spotify:track:123",
            "device_id": "phone",
        },
    )
    assert planner.parse_decision('{"tool":"spotify-list-playlists"}') == (
        ToolPlanningDecision(
            tool_name="spotify-list-playlists",
            arguments={},
        )
    )
    assert planner.parse_decision(
        '{"tool":"spotify-play-playlist","playlist_name":" Focus Flow "}'
    ) == ToolPlanningDecision(
        tool_name="spotify-play-playlist",
        arguments={"playlist_name": "Focus Flow"},
    )


def test_tool_planner_rejects_invalid_directives_and_reports_outcome() -> None:
    planner = ToolPlanner(
        web_search_available=True,
        spotify_available=True,
        spotify_real_available=True,
    )

    assert planner.parse_decision('{"tool":"unknown","query":"x"}') is None
    assert planner.parse_decision('{"tool":"spotify-play","device_id":""}') is None
    assert planner.content_outcome(
        '{"tool":"web-search","query":"x"}',
        ToolPlanningDecision(tool_name="web-search", arguments={"query": "x"}),
    ) == "tool_requested"
    assert planner.content_outcome('{"tool":"unknown"}', None) == "invalid_directive"
    assert planner.content_outcome("answer directly", None) == "respond_directly"
    assert "web-search" in SUPPORTED_TOOL_NAMES
    assert "spotify-list-playlists" in SUPPORTED_TOOL_NAMES
    assert "spotify-play-playlist" in SUPPORTED_TOOL_NAMES
