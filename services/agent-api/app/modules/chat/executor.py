from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.clients.search import WebSearchClient, WebSearchResultItem
from app.clients.spotify import SpotifyClient, SpotifyPlaylistItem, SpotifyTrackItem
from app.core.config import Settings
from app.core.errors import APIError
from app.core.logging import log_event
from app.core.metrics import get_agent_metrics
from app.modules.chat.formatters import ChatPromptFormatter
from app.modules.chat.planner import ToolPlanningDecision
from app.modules.chat.policy import ToolPolicyDecision, ToolPolicyEngine
from app.repositories import ToolExecutionRecord
from app.schemas.chat import ChatMessage


@dataclass(frozen=True, slots=True)
class ToolContext:
    runtime_messages: list[ChatMessage]
    execution: ToolExecutionRecord | None = None


class ToolExecutor:
    """Owns tool execution and prompt augmentation after tool results."""

    def __init__(
        self,
        *,
        settings: Settings,
        web_search_client: WebSearchClient | None,
        spotify_client: SpotifyClient | None,
        prompt_formatter: ChatPromptFormatter,
        policy_engine: ToolPolicyEngine,
    ) -> None:
        self._settings = settings
        self._web_search_client = web_search_client
        self._spotify_client = spotify_client
        self._prompt_formatter = prompt_formatter
        self._policy_engine = policy_engine

    def execute(
        self,
        *,
        request_id: str,
        base_messages: list[ChatMessage],
        decision: ToolPlanningDecision,
        annotate_failures: bool,
        request_source: str | None,
    ) -> ToolContext:
        policy = self._policy_engine.evaluate(
            decision.tool_name,
            request_source=request_source,
        )
        started_at = datetime.now(timezone.utc)
        tool_started = perf_counter()
        invocation_id = f"tool_{uuid4().hex[:12]}"

        if not policy.allowed:
            execution = ToolExecutionRecord(
                invocation_id=invocation_id,
                tool_name=decision.tool_name,
                status="failed",
                arguments=decision.arguments,
                latency_ms=0.0,
                started_at=started_at,
                completed_at=started_at,
                adapter_name=policy.adapter_name,
                provider=policy.provider,
                policy_decision=policy.policy_decision,
                error_type=policy.error_type,
                error_code=policy.error_code,
            )
            self._log_tool_execution(request_id=request_id, execution=execution)
            return ToolContext(
                runtime_messages=self._apply_tool_failure_policy(
                    base_messages=base_messages,
                    annotate_failures=annotate_failures,
                    tool_name=decision.tool_name,
                ),
                execution=execution,
            )

        if decision.tool_name == "web-search":
            return self._execute_web_search(
                request_id=request_id,
                base_messages=base_messages,
                decision=decision,
                annotate_failures=annotate_failures,
                started_at=started_at,
                tool_started=tool_started,
                invocation_id=invocation_id,
                policy=policy,
            )
        return self._execute_spotify_tool(
            request_id=request_id,
            base_messages=base_messages,
            decision=decision,
            annotate_failures=annotate_failures,
            started_at=started_at,
            tool_started=tool_started,
            invocation_id=invocation_id,
            policy=policy,
        )

    def _execute_web_search(
        self,
        *,
        request_id: str,
        base_messages: list[ChatMessage],
        decision: ToolPlanningDecision,
        annotate_failures: bool,
        started_at: datetime,
        tool_started: float,
        invocation_id: str,
        policy: ToolPolicyDecision,
    ) -> ToolContext:
        raw_query = decision.arguments.get("query")
        query_text = raw_query.strip() if isinstance(raw_query, str) else ""
        if not query_text:
            return ToolContext(runtime_messages=list(base_messages))

        tool_arguments = {
            "query": query_text,
            "limit": self._settings.web_search_top_k,
        }

        if self._web_search_client is None:
            completed_at = datetime.now(timezone.utc)
            execution = ToolExecutionRecord(
                invocation_id=invocation_id,
                tool_name=decision.tool_name,
                status="failed",
                arguments=tool_arguments,
                latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                started_at=started_at,
                completed_at=completed_at,
                adapter_name=policy.adapter_name,
                provider=policy.provider,
                policy_decision=policy.policy_decision,
                error_type="dependency_unavailable",
                error_code="tool_not_configured",
            )
            self._log_tool_execution(request_id=request_id, execution=execution)
            return ToolContext(
                runtime_messages=self._apply_tool_failure_policy(
                    base_messages=base_messages,
                    annotate_failures=annotate_failures,
                    tool_name=decision.tool_name,
                ),
                execution=execution,
            )

        try:
            raw_results = self._web_search_client.search(
                query=query_text,
                limit=self._settings.web_search_top_k,
            )
            results = self._normalize_search_results(raw_results)
            completed_at = datetime.now(timezone.utc)
            execution = ToolExecutionRecord(
                invocation_id=invocation_id,
                tool_name=decision.tool_name,
                status="completed",
                arguments=tool_arguments,
                output={
                    "results": [
                        {
                            "title": result.title,
                            "url": result.url,
                            "snippet": result.snippet,
                        }
                        for result in results
                    ]
                },
                latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                started_at=started_at,
                completed_at=completed_at,
                adapter_name=policy.adapter_name,
                provider=policy.provider,
                policy_decision=policy.policy_decision,
            )
            self._log_tool_execution(request_id=request_id, execution=execution)
            if not results:
                return ToolContext(
                    runtime_messages=list(base_messages),
                    execution=execution,
                )
            return ToolContext(
                runtime_messages=self._prompt_formatter.augment_with_search_results(
                    base_messages,
                    results,
                ),
                execution=execution,
            )
        except APIError as exc:
            completed_at = datetime.now(timezone.utc)
            execution = ToolExecutionRecord(
                invocation_id=invocation_id,
                tool_name=decision.tool_name,
                status="failed",
                arguments=tool_arguments,
                latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                started_at=started_at,
                completed_at=completed_at,
                adapter_name=policy.adapter_name,
                provider=policy.provider,
                policy_decision=policy.policy_decision,
                error_type=exc.error_type,
                error_code=exc.code,
            )
            self._log_tool_execution(request_id=request_id, execution=execution)
            return ToolContext(
                runtime_messages=self._apply_tool_failure_policy(
                    base_messages=base_messages,
                    annotate_failures=annotate_failures,
                    tool_name=decision.tool_name,
                ),
                execution=execution,
            )

    def _execute_spotify_tool(
        self,
        *,
        request_id: str,
        base_messages: list[ChatMessage],
        decision: ToolPlanningDecision,
        annotate_failures: bool,
        started_at: datetime,
        tool_started: float,
        invocation_id: str,
        policy: ToolPolicyDecision,
    ) -> ToolContext:
        if self._spotify_client is None:
            completed_at = datetime.now(timezone.utc)
            execution = ToolExecutionRecord(
                invocation_id=invocation_id,
                tool_name=decision.tool_name,
                status="failed",
                arguments=dict(decision.arguments),
                latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                started_at=started_at,
                completed_at=completed_at,
                adapter_name=policy.adapter_name,
                provider=policy.provider,
                policy_decision=policy.policy_decision,
                error_type="dependency_unavailable",
                error_code="tool_not_configured",
            )
            self._log_tool_execution(request_id=request_id, execution=execution)
            return ToolContext(
                runtime_messages=self._apply_tool_failure_policy(
                    base_messages=base_messages,
                    annotate_failures=annotate_failures,
                    tool_name=decision.tool_name,
                ),
                execution=execution,
            )

        if decision.tool_name == "spotify-search":
            query_text = decision.arguments.get("query", "")
            query = query_text.strip() if isinstance(query_text, str) else ""
            if not query:
                return ToolContext(runtime_messages=list(base_messages))

            tool_arguments = {
                "query": query,
                "limit": self._settings.spotify_search_top_k,
            }

            try:
                tracks = self._spotify_client.search_tracks(
                    query=query,
                    limit=self._settings.spotify_search_top_k,
                )
                spotify_results = self._normalize_spotify_results(tracks)
                completed_at = datetime.now(timezone.utc)
                execution = ToolExecutionRecord(
                    invocation_id=invocation_id,
                    tool_name=decision.tool_name,
                    status="completed",
                    arguments=tool_arguments,
                    output={"results": spotify_results},
                    latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                    started_at=started_at,
                    completed_at=completed_at,
                    adapter_name=policy.adapter_name,
                    provider=policy.provider,
                    policy_decision=policy.policy_decision,
                )
                self._log_tool_execution(request_id=request_id, execution=execution)
                if not spotify_results:
                    return ToolContext(
                        runtime_messages=list(base_messages),
                        execution=execution,
                    )
                return ToolContext(
                    runtime_messages=self._prompt_formatter.augment_with_spotify_results(
                        base_messages,
                        spotify_results,
                    ),
                    execution=execution,
                )
            except APIError as exc:
                completed_at = datetime.now(timezone.utc)
                execution = ToolExecutionRecord(
                    invocation_id=invocation_id,
                    tool_name=decision.tool_name,
                    status="failed",
                    arguments=tool_arguments,
                    latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                    started_at=started_at,
                    completed_at=completed_at,
                    adapter_name=policy.adapter_name,
                    provider=policy.provider,
                    policy_decision=policy.policy_decision,
                    error_type=exc.error_type,
                    error_code=exc.code,
                )
                self._log_tool_execution(request_id=request_id, execution=execution)
                return ToolContext(
                    runtime_messages=self._apply_tool_failure_policy(
                        base_messages=base_messages,
                        annotate_failures=annotate_failures,
                        tool_name=decision.tool_name,
                    ),
                    execution=execution,
                )

        if decision.tool_name == "spotify-list-playlists":
            tool_arguments = {
                "limit": self._settings.spotify_playlist_top_k,
            }
            try:
                playlists = self._spotify_client.list_playlists(
                    limit=self._settings.spotify_playlist_top_k,
                )
                spotify_results = self._normalize_spotify_playlists(playlists)
                completed_at = datetime.now(timezone.utc)
                execution = ToolExecutionRecord(
                    invocation_id=invocation_id,
                    tool_name=decision.tool_name,
                    status="completed",
                    arguments=tool_arguments,
                    output={"results": spotify_results},
                    latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                    started_at=started_at,
                    completed_at=completed_at,
                    adapter_name=policy.adapter_name,
                    provider=policy.provider,
                    policy_decision=policy.policy_decision,
                )
                self._log_tool_execution(request_id=request_id, execution=execution)
                return ToolContext(
                    runtime_messages=self._prompt_formatter.augment_with_spotify_playlists(
                        base_messages,
                        spotify_results,
                    ),
                    execution=execution,
                )
            except APIError as exc:
                completed_at = datetime.now(timezone.utc)
                execution = ToolExecutionRecord(
                    invocation_id=invocation_id,
                    tool_name=decision.tool_name,
                    status="failed",
                    arguments=tool_arguments,
                    latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                    started_at=started_at,
                    completed_at=completed_at,
                    adapter_name=policy.adapter_name,
                    provider=policy.provider,
                    policy_decision=policy.policy_decision,
                    error_type=exc.error_type,
                    error_code=exc.code,
                )
                self._log_tool_execution(request_id=request_id, execution=execution)
                return ToolContext(
                    runtime_messages=self._apply_tool_failure_policy(
                        base_messages=base_messages,
                        annotate_failures=annotate_failures,
                        tool_name=decision.tool_name,
                    ),
                    execution=execution,
                )

        if decision.tool_name == "spotify-play-playlist":
            playlist_name = self._normalize_playlist_name(decision.arguments)
            tool_arguments: dict[str, object] = {
                "playlist_name": playlist_name,
                "limit": self._settings.spotify_playlist_top_k,
            }
            device_id = self._normalize_optional_device_id(decision.arguments)
            if device_id:
                tool_arguments["device_id"] = device_id
            try:
                playlists = self._spotify_client.list_playlists(
                    limit=self._settings.spotify_playlist_top_k,
                )
                playlist_uri = self._resolve_playlist_uri(
                    playlists=playlists,
                    playlist_name=playlist_name,
                )
                tool_arguments["playlist_uri"] = playlist_uri
                self._spotify_client.play_playlist(
                    playlist_uri=playlist_uri,
                    device_id=device_id,
                )
                completed_at = datetime.now(timezone.utc)
                execution = ToolExecutionRecord(
                    invocation_id=invocation_id,
                    tool_name=decision.tool_name,
                    status="completed",
                    arguments=tool_arguments,
                    output={"status": "ok"},
                    latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                    started_at=started_at,
                    completed_at=completed_at,
                    adapter_name=policy.adapter_name,
                    provider=policy.provider,
                    policy_decision=policy.policy_decision,
                )
                self._log_tool_execution(request_id=request_id, execution=execution)
                return ToolContext(
                    runtime_messages=self._prompt_formatter.augment_with_spotify_action(
                        messages=base_messages,
                        tool_name=decision.tool_name,
                        arguments=tool_arguments,
                    ),
                    execution=execution,
                )
            except APIError as exc:
                completed_at = datetime.now(timezone.utc)
                execution = ToolExecutionRecord(
                    invocation_id=invocation_id,
                    tool_name=decision.tool_name,
                    status="failed",
                    arguments=tool_arguments,
                    latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                    started_at=started_at,
                    completed_at=completed_at,
                    adapter_name=policy.adapter_name,
                    provider=policy.provider,
                    policy_decision=policy.policy_decision,
                    error_type=exc.error_type,
                    error_code=exc.code,
                )
                self._log_tool_execution(request_id=request_id, execution=execution)
                return ToolContext(
                    runtime_messages=self._apply_tool_failure_policy(
                        base_messages=base_messages,
                        annotate_failures=annotate_failures,
                        tool_name=decision.tool_name,
                    ),
                    execution=execution,
                )

        device_id = self._normalize_optional_device_id(decision.arguments)

        try:
            if decision.tool_name == "spotify-play":
                track_uri = self._normalize_track_uri(decision.arguments)
                tool_arguments: dict[str, object] = {"track_uri": track_uri}
                if device_id:
                    tool_arguments["device_id"] = device_id
                self._spotify_client.play_track(
                    track_uri=track_uri,
                    device_id=device_id,
                )
            else:
                tool_arguments = {}
                if device_id:
                    tool_arguments["device_id"] = device_id

            if decision.tool_name == "spotify-pause":
                self._spotify_client.pause_playback(device_id=device_id)
            elif decision.tool_name == "spotify-next":
                self._spotify_client.next_track(device_id=device_id)

            completed_at = datetime.now(timezone.utc)
            execution = ToolExecutionRecord(
                invocation_id=invocation_id,
                tool_name=decision.tool_name,
                status="completed",
                arguments=tool_arguments,
                output={"status": "ok"},
                latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                started_at=started_at,
                completed_at=completed_at,
                adapter_name=policy.adapter_name,
                provider=policy.provider,
                policy_decision=policy.policy_decision,
            )
            self._log_tool_execution(request_id=request_id, execution=execution)
            return ToolContext(
                runtime_messages=self._prompt_formatter.augment_with_spotify_action(
                    messages=base_messages,
                    tool_name=decision.tool_name,
                    arguments=tool_arguments,
                ),
                execution=execution,
            )
        except APIError as exc:
            completed_at = datetime.now(timezone.utc)
            execution = ToolExecutionRecord(
                invocation_id=invocation_id,
                tool_name=decision.tool_name,
                status="failed",
                arguments=tool_arguments,
                latency_ms=round((perf_counter() - tool_started) * 1000, 2),
                started_at=started_at,
                completed_at=completed_at,
                adapter_name=policy.adapter_name,
                provider=policy.provider,
                policy_decision=policy.policy_decision,
                error_type=exc.error_type,
                error_code=exc.code,
            )
            self._log_tool_execution(request_id=request_id, execution=execution)
            return ToolContext(
                runtime_messages=self._apply_tool_failure_policy(
                    base_messages=base_messages,
                    annotate_failures=annotate_failures,
                    tool_name=decision.tool_name,
                ),
                execution=execution,
            )

    def _apply_tool_failure_policy(
        self,
        *,
        base_messages: list[ChatMessage],
        annotate_failures: bool,
        tool_name: str,
    ) -> list[ChatMessage]:
        if not annotate_failures:
            return list(base_messages)
        return self._prompt_formatter.augment_with_tool_unavailable(
            base_messages,
            tool_name,
        )

    def _normalize_search_results(
        self,
        results: list[object],
    ) -> list[WebSearchResultItem]:
        normalized_results: list[WebSearchResultItem] = []
        for result in results:
            if isinstance(result, WebSearchResultItem):
                normalized_results.append(result)
                continue
            if isinstance(result, dict):
                title = result.get("title")
                url = result.get("url")
                snippet = result.get("snippet")
                if (
                    isinstance(title, str)
                    and isinstance(url, str)
                    and isinstance(snippet, str)
                ):
                    normalized_results.append(
                        WebSearchResultItem(
                            title=title,
                            url=url,
                            snippet=snippet,
                        )
                    )
                    continue
            raise APIError(
                status_code=500,
                error_type="internal_error",
                code="tool_bad_result",
                message="Search adapter returned an invalid result",
            )
        return normalized_results

    def _normalize_spotify_results(
        self,
        results: list[SpotifyTrackItem],
    ) -> list[dict[str, object]]:
        return [
            {
                "name": item.name,
                "artists": item.artists,
                "uri": item.uri,
                "album": item.album,
                "url": item.external_url,
            }
            for item in results
        ]

    def _normalize_spotify_playlists(
        self,
        playlists: list[SpotifyPlaylistItem],
    ) -> list[dict[str, object]]:
        return [
            {
                "name": item.name,
                "owner": item.owner,
                "uri": item.uri,
                "external_url": item.external_url,
            }
            for item in playlists
        ]

    def _normalize_track_uri(self, arguments: dict[str, object]) -> str:
        if "track_uri" in arguments:
            value = arguments.get("track_uri")
            if isinstance(value, str):
                track_uri = value.strip()
                if track_uri:
                    return track_uri
        if "uri" in arguments:
            value = arguments.get("uri")
            if isinstance(value, str):
                track_uri = value.strip()
                if track_uri:
                    return track_uri
        raise APIError(
            status_code=400,
            error_type="validation_error",
            code="invalid_request",
            message="spotify-play requires a track_uri",
        )

    def _normalize_optional_device_id(
        self,
        arguments: dict[str, object],
    ) -> str | None:
        value = arguments.get("device_id")
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
        return None

    def _normalize_playlist_name(
        self,
        arguments: dict[str, object],
    ) -> str:
        value = arguments.get("playlist_name")
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
        raise APIError(
            status_code=400,
            error_type="validation_error",
            code="invalid_request",
            message="spotify-play-playlist requires a playlist_name",
        )

    def _resolve_playlist_uri(
        self,
        *,
        playlists: list[SpotifyPlaylistItem],
        playlist_name: str,
    ) -> str:
        normalized_name = playlist_name.strip().casefold()
        matches = [
            playlist
            for playlist in playlists
            if playlist.name.strip().casefold() == normalized_name
        ]
        if len(matches) == 1:
            return matches[0].uri
        if not matches:
            raise APIError(
                status_code=400,
                error_type="validation_error",
                code="invalid_request",
                message="Requested Spotify playlist was not found",
            )
        raise APIError(
            status_code=400,
            error_type="validation_error",
            code="invalid_request",
            message="Requested Spotify playlist is ambiguous",
        )

    def _log_tool_execution(
        self,
        *,
        request_id: str,
        execution: ToolExecutionRecord,
    ) -> None:
        level = logging.INFO if execution.status == "completed" else logging.WARNING
        log_event(
            "chat_tool_completed",
            level=level,
            request_id=request_id,
            tool_name=execution.tool_name,
            invocation_id=execution.invocation_id,
            outcome=execution.status,
            duration_ms=execution.latency_ms,
            error_type=execution.error_type,
            error_code=execution.error_code,
        )
        get_agent_metrics().record_tool_execution(
            tool_name=execution.tool_name,
            outcome=execution.status,
            error_type=execution.error_type,
        )
