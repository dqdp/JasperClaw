from __future__ import annotations

import json
from dataclasses import dataclass

from app.clients.ollama import OllamaChatResult
from app.schemas.chat import ChatCompletionRequest, ChatMessage

SUPPORTED_TOOL_NAMES = (
    "web-search",
    "spotify-search",
    "spotify-play",
    "spotify-pause",
    "spotify-next",
)


@dataclass(frozen=True, slots=True)
class ToolPlanningDecision:
    tool_name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolPlanningResult:
    runtime_result: OllamaChatResult
    decision: ToolPlanningDecision | None
    content_outcome: str


class ToolPlanner:
    """Owns pure tool-planning prompt and directive parsing rules."""

    def __init__(
        self,
        *,
        web_search_available: bool,
        spotify_available: bool,
    ) -> None:
        self._web_search_available = web_search_available
        self._spotify_available = spotify_available

    def is_web_search_requested(self, request: ChatCompletionRequest) -> bool:
        if not request.metadata:
            return False
        value = request.metadata.get("web_search")
        if not value:
            return False
        return value.strip().casefold() in {"1", "true", "yes", "on"}

    def should_attempt_model_driven_tool_use(
        self,
        request: ChatCompletionRequest,
    ) -> bool:
        if request.metadata and "web_search" in request.metadata:
            return False
        if not self._web_search_available and not self._spotify_available:
            return False
        return self._latest_user_message(request.messages) is not None

    def build_planning_messages(
        self,
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        tool_examples: list[str] = []
        if self._web_search_available:
            tool_examples.append('{"tool":"web-search","query":"..."}')
        if self._spotify_available:
            tool_examples.extend(
                [
                    '{"tool":"spotify-search","query":"..."}',
                    '{"tool":"spotify-play","track_uri":"..."}',
                    '{"tool":"spotify-pause"}',
                    '{"tool":"spotify-next"}',
                ]
            )
        tools_description = "; ".join(tool_examples) if tool_examples else ""
        planning_message = ChatMessage(
            role="system",
            content=(
                "You may either answer the user directly or request exactly one tool. "
                "Return strict JSON for the tool request, and no other text. "
                f"Supported examples: {tools_description}. "
                "Otherwise answer the user directly."
            ),
        )
        insert_at = 0
        while insert_at < len(messages) and messages[insert_at].role == "system":
            insert_at += 1
        return [
            *messages[:insert_at],
            planning_message,
            *messages[insert_at:],
        ]

    def parse_decision(
        self,
        content: str,
    ) -> ToolPlanningDecision | None:
        stripped_content = content.strip()
        if not stripped_content.startswith("{"):
            return None

        try:
            payload = json.loads(stripped_content)
        except ValueError:
            return None

        if not isinstance(payload, dict):
            return None

        tool_name = payload.get("tool")
        if not isinstance(tool_name, str):
            return None

        tool_name = tool_name.strip().casefold()
        if not tool_name:
            return None

        arguments: dict[str, object] = {
            key: value for key, value in payload.items() if key != "tool"
        }

        if tool_name in {"web-search", "spotify-search"}:
            query = arguments.get("query")
            if not isinstance(query, str):
                return None
            query = query.strip()
            if not query:
                return None
            arguments["query"] = query
        elif tool_name == "spotify-play":
            track_uri = arguments.get("track_uri")
            if track_uri is None:
                track_uri = arguments.get("uri")
            if not isinstance(track_uri, str):
                return None
            track_uri = track_uri.strip()
            if not track_uri:
                return None
            arguments["track_uri"] = track_uri
            if "uri" in arguments:
                del arguments["uri"]
            device_id = arguments.get("device_id")
            if device_id is not None and (
                not isinstance(device_id, str) or not device_id.strip()
            ):
                return None
        elif tool_name in {"spotify-pause", "spotify-next"}:
            if "track_uri" in arguments:
                del arguments["track_uri"]
            if "uri" in arguments:
                del arguments["uri"]
            device_id = arguments.get("device_id")
            if device_id is not None and (
                not isinstance(device_id, str) or not device_id.strip()
            ):
                return None

        if tool_name not in SUPPORTED_TOOL_NAMES:
            return None

        return ToolPlanningDecision(tool_name=tool_name, arguments=arguments)

    def content_outcome(
        self,
        content: str,
        decision: ToolPlanningDecision | None,
    ) -> str:
        if decision is not None:
            return "tool_requested"
        if content.strip().startswith("{"):
            return "invalid_directive"
        return "respond_directly"

    def _latest_user_message(self, messages: list[ChatMessage]) -> str | None:
        for message in reversed(messages):
            content = message.content.strip()
            if message.role == "user" and content:
                return content
        return None
