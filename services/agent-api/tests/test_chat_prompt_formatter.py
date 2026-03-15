from app.clients.search import WebSearchResultItem
from app.modules.chat.formatters import ChatPromptFormatter
from app.schemas.chat import ChatMessage


def test_formatter_inserts_memory_after_existing_system_messages() -> None:
    formatter = ChatPromptFormatter()

    messages = formatter.augment_with_memory(
        [
            ChatMessage(role="system", content="existing"),
            ChatMessage(role="user", content="hello"),
        ],
        ("Fact one", "Fact two"),
    )

    assert messages[0].content == "existing"
    assert messages[1].role == "system"
    assert "Relevant memory from prior conversations" in messages[1].content
    assert "- Fact one" in messages[1].content
    assert messages[2].content == "hello"


def test_formatter_includes_search_results() -> None:
    formatter = ChatPromptFormatter()

    messages = formatter.augment_with_search_results(
        [ChatMessage(role="user", content="latest status")],
        [
            WebSearchResultItem(
                title="Release notes",
                url="https://example.com/release",
                snippet="Recent changes",
            )
        ],
    )

    assert "Relevant web search results" in messages[0].content
    assert "https://example.com/release" in messages[0].content


def test_formatter_includes_spotify_action_arguments() -> None:
    formatter = ChatPromptFormatter()

    messages = formatter.augment_with_spotify_action(
        messages=[ChatMessage(role="user", content="play")],
        tool_name="spotify-play",
        arguments={"track_uri": "spotify:track:123", "device_id": "phone"},
    )

    assert "Spotify action completed: spotify-play." in messages[0].content
    assert "track uri=spotify:track:123" in messages[0].content
    assert "device id=phone" in messages[0].content


def test_formatter_includes_spotify_playlists() -> None:
    formatter = ChatPromptFormatter()

    messages = formatter.augment_with_spotify_playlists(
        [ChatMessage(role="user", content="what playlists do I have?")],
        [
            {
                "name": "Focus Flow",
                "owner": "Alex",
                "uri": "spotify:playlist:001",
                "external_url": "https://open.spotify.com/playlist/001",
            }
        ],
    )

    assert "Available Spotify playlists" in messages[0].content
    assert "Focus Flow" in messages[0].content
    assert "Owner: Alex" in messages[0].content


def test_formatter_marks_tool_unavailable_with_tool_specific_copy() -> None:
    formatter = ChatPromptFormatter()

    web_search = formatter.augment_with_tool_unavailable(
        [ChatMessage(role="user", content="latest updates")],
        "web-search",
    )
    other = formatter.augment_with_tool_unavailable(
        [ChatMessage(role="user", content="play music")],
        "spotify-play",
    )

    assert "Web search was requested but is currently unavailable." in web_search[0].content
    assert "spotify-play" in other[0].content
