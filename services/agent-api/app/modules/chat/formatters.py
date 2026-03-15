from __future__ import annotations

from app.clients.search import WebSearchResultItem
from app.schemas.chat import ChatMessage


class ChatPromptFormatter:
    """Pure prompt augmentation for retrieved memory and tool outputs."""

    def augment_with_memory(
        self,
        messages: list[ChatMessage],
        memory_lines: tuple[str, ...],
    ) -> list[ChatMessage]:
        memory_message = ChatMessage(
            role="system",
            content=(
                "Relevant memory from prior conversations:\n"
                + "\n".join(f"- {line}" for line in memory_lines)
                + "\nUse it only when helpful and do not treat it as authoritative "
                "if the current conversation conflicts with it."
            ),
        )
        return self._insert_after_system(messages, memory_message)

    def augment_with_spotify_results(
        self,
        messages: list[ChatMessage],
        results: list[dict[str, object]],
    ) -> list[ChatMessage]:
        lines = [
            (
                f"- {result['name']}\n"
                f"  Artists: {result['artists']}\n"
                f"  URI: {result['uri']}"
            )
            for result in results
        ]
        spotify_message = ChatMessage(
            role="system",
            content=(
                "Relevant Spotify tracks:\n"
                + "\n".join(lines)
                + "\nUse these results only when they help answer the request."
            ),
        )
        return self._insert_after_system(messages, spotify_message)

    def augment_with_spotify_playlists(
        self,
        messages: list[ChatMessage],
        results: list[dict[str, object]],
    ) -> list[ChatMessage]:
        lines = [
            (
                f"- {result['name']}\n"
                f"  Owner: {result['owner']}\n"
                f"  URI: {result['uri']}"
            )
            for result in results
        ]
        playlist_message = ChatMessage(
            role="system",
            content=(
                "Available Spotify playlists:\n"
                + "\n".join(lines)
                + "\nUse these playlists only when they help answer the request."
            ),
        )
        return self._insert_after_system(messages, playlist_message)

    def augment_with_telegram_aliases(
        self,
        messages: list[ChatMessage],
        results: list[dict[str, object]],
    ) -> list[ChatMessage]:
        lines = [
            f"- {result['alias']}: {result['description']}"
            for result in results
        ]
        alias_message = ChatMessage(
            role="system",
            content=(
                "Available Telegram aliases:\n"
                + "\n".join(lines)
                + "\nUse these aliases only when they help answer the request."
            ),
        )
        return self._insert_after_system(messages, alias_message)

    def augment_with_spotify_action(
        self,
        *,
        messages: list[ChatMessage],
        tool_name: str,
        arguments: dict[str, object],
    ) -> list[ChatMessage]:
        argument_lines = [
            f"{key.replace('_', ' ')}={value}"
            for key, value in arguments.items()
            if value is not None
        ]
        detail = ", ".join(argument_lines)
        action_message = ChatMessage(
            role="system",
            content=(
                f"Spotify action completed: {tool_name}. "
                f"Arguments: {detail}. "
                "Continue with a normal response."
            ),
        )
        return self._insert_after_system(messages, action_message)

    def augment_with_search_results(
        self,
        messages: list[ChatMessage],
        results: list[WebSearchResultItem],
    ) -> list[ChatMessage]:
        result_lines = "\n".join(
            (
                f"- {result.title}\n"
                f"  URL: {result.url}\n"
                f"  Snippet: {result.snippet}"
            )
            for result in results
        )
        search_message = ChatMessage(
            role="system",
            content=(
                "Relevant web search results:\n"
                f"{result_lines}\n"
                "Use these results only when they help answer the current request. "
                "Cite the source URLs in the answer when appropriate."
            ),
        )
        return self._insert_after_system(messages, search_message)

    def augment_with_tool_unavailable(
        self,
        messages: list[ChatMessage],
        tool_name: str,
    ) -> list[ChatMessage]:
        normalized_tool = tool_name.strip().casefold()
        if normalized_tool == "web-search":
            unavailable_text = (
                "Web search was requested but is currently unavailable. "
                "Answer using existing knowledge only, and be explicit when fresh "
                "facts may be uncertain."
            )
        else:
            unavailable_text = (
                f"The tool '{tool_name}' is currently unavailable or blocked by policy. "
                "Answer the request using existing context without external calls."
            )
        return self._insert_after_system(
            messages,
            ChatMessage(role="system", content=unavailable_text),
        )

    def _insert_after_system(
        self,
        messages: list[ChatMessage],
        injected_message: ChatMessage,
    ) -> list[ChatMessage]:
        insert_at = 0
        while insert_at < len(messages) and messages[insert_at].role == "system":
            insert_at += 1
        return [
            *messages[:insert_at],
            injected_message,
            *messages[insert_at:],
        ]
