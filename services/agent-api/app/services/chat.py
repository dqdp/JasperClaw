import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from time import perf_counter, time
from uuid import uuid4

from app.clients.ollama import (
    OllamaChatClient,
    OllamaChatResult,
    OllamaChatStreamChunk,
)
from app.clients.search import WebSearchClient, WebSearchResultItem
from app.clients.spotify import SpotifyClient, SpotifyTrackItem
from app.core.config import Settings
from app.core.errors import APIError
from app.core.logging import log_event
from app.repositories import (
    ChatPersistenceResult,
    ChatRepository,
    ConversationContext,
    MemoryRetrievalRecord,
    MemorySearchHit,
    PersistedMessage,
    ToolExecutionRecord,
)
from app.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionUsage,
    ChatMessage,
)

_SUPPORTED_TOOL_NAMES = (
    "web-search",
    "spotify-search",
    "spotify-play",
    "spotify-pause",
    "spotify-next",
)


@dataclass(slots=True)
class RuntimeProfile:
    public_id: str
    runtime_model: str


@dataclass(slots=True)
class ChatResult:
    response_id: str
    created: int
    public_model: str
    conversation_id: str
    content: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage | None


@dataclass(slots=True)
class ChatStreamEvent:
    content: str | None
    role: str | None
    finish_reason: str | None


@dataclass(slots=True)
class ChatStreamSession:
    response_id: str
    created: int
    public_model: str
    conversation_id: str
    events: Iterator[ChatStreamEvent]


@dataclass(frozen=True, slots=True)
class MemoryContext:
    runtime_messages: list[ChatMessage]
    retrieval: MemoryRetrievalRecord | None = None


@dataclass(frozen=True, slots=True)
class ToolContext:
    runtime_messages: list[ChatMessage]
    execution: ToolExecutionRecord | None = None


@dataclass(frozen=True, slots=True)
class ToolPlanningDecision:
    tool_name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolPlanningResult:
    runtime_result: OllamaChatResult
    decision: ToolPlanningDecision | None
    content_outcome: str


@dataclass(frozen=True, slots=True)
class ToolPolicyDecision:
    allowed: bool
    policy_decision: str
    error_type: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    adapter_name: str | None = None
    provider: str | None = None


class ChatService:
    def __init__(
        self,
        settings: Settings,
        ollama_client: OllamaChatClient,
        repository: ChatRepository,
        web_search_client: WebSearchClient | None = None,
        spotify_client: SpotifyClient | None = None,
    ) -> None:
        self._settings = settings
        self._ollama_client = ollama_client
        self._repository = repository
        self._web_search_client = web_search_client
        self._spotify_client = spotify_client

    def create_chat_completion(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None = None,
    ) -> ChatResult:
        profile = self._resolve_profile(request.model)
        resolved_conversation_hint = (
            conversation_id_hint or self._extract_conversation_hint(request)
        )
        memory_context = self._prepare_memory_context(
            request_id=request_id,
            request=request,
        )
        tool_context = ToolContext(runtime_messages=memory_context.runtime_messages)
        started_at = datetime.now(timezone.utc)
        runtime_started = perf_counter()

        try:
            planning_result = self._maybe_run_tool_planning_pass(
                request_id=request_id,
                request=request,
                profile=profile,
                base_messages=memory_context.runtime_messages,
            )
            if self._is_web_search_requested(request):
                tool_context = self._prepare_tool_context(
                    request_id=request_id,
                    request=request,
                    base_messages=memory_context.runtime_messages,
                )
            elif planning_result is not None and planning_result.decision is not None:
                tool_context = self._prepare_model_driven_tool_context(
                    request_id=request_id,
                    request=request,
                    base_messages=memory_context.runtime_messages,
                    decision=planning_result.decision,
                )
            elif planning_result is not None:
                completed_at = datetime.now(timezone.utc)
                return self._build_success_result(
                    request_id=request_id,
                    request=request,
                    profile=profile,
                    conversation_id_hint=resolved_conversation_hint,
                    memory_context=memory_context,
                    tool_context=tool_context,
                    runtime_result=planning_result.runtime_result,
                    started_at=started_at,
                    completed_at=completed_at,
                    runtime_started=runtime_started,
                    log_runtime=False,
                )

            runtime_started = perf_counter()
            runtime_result = self._ollama_client.chat(
                model=profile.runtime_model,
                messages=tool_context.runtime_messages,
            )
        except APIError as exc:
            completed_at = datetime.now(timezone.utc)
            self._log_runtime_error(
                request_id=request_id,
                profile=profile,
                runtime_started=runtime_started,
                error=exc,
            )
            persistence = self._persist_failed_completion(
                request_id=request_id,
                profile=profile,
                request=request,
                conversation_id_hint=resolved_conversation_hint,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            self._record_memory_retrieval(
                request_id=request_id,
                profile=profile,
                conversation_id=(
                    persistence.conversation_id if persistence is not None else None
                ),
                memory_context=memory_context,
                created_at=completed_at,
            )
            self._record_tool_execution(
                request_id=request_id,
                conversation_id=(
                    persistence.conversation_id if persistence is not None else None
                ),
                model_run_id=persistence.model_run_id if persistence is not None else None,
                tool_context=tool_context,
            )
            raise

        completed_at = datetime.now(timezone.utc)
        return self._build_success_result(
            request_id=request_id,
            request=request,
            profile=profile,
            conversation_id_hint=resolved_conversation_hint,
            memory_context=memory_context,
            tool_context=tool_context,
            runtime_result=runtime_result,
            started_at=started_at,
            completed_at=completed_at,
            runtime_started=runtime_started,
        )

    def create_streaming_chat_completion(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None = None,
    ) -> ChatStreamSession:
        profile = self._resolve_profile(request.model)
        resolved_conversation_hint = (
            conversation_id_hint or self._extract_conversation_hint(request)
        )
        started_at = datetime.now(timezone.utc)
        context = self._repository.prepare_conversation(
            public_model=profile.public_id,
            request_messages=request.messages,
            conversation_id_hint=resolved_conversation_hint,
            created_at=started_at,
        )
        memory_context = self._prepare_memory_context(
            request_id=request_id,
            request=request,
        )
        tool_context = ToolContext(runtime_messages=memory_context.runtime_messages)
        runtime_started = perf_counter()

        try:
            planning_result = self._maybe_run_tool_planning_pass(
                request_id=request_id,
                request=request,
                profile=profile,
                base_messages=memory_context.runtime_messages,
            )
            if self._is_web_search_requested(request):
                tool_context = self._prepare_tool_context(
                    request_id=request_id,
                    request=request,
                    base_messages=memory_context.runtime_messages,
                )
            elif planning_result is not None and planning_result.decision is not None:
                tool_context = self._prepare_model_driven_tool_context(
                    request_id=request_id,
                    request=request,
                    base_messages=memory_context.runtime_messages,
                    decision=planning_result.decision,
                )
            elif planning_result is not None:
                response_id = f"chatcmpl_{uuid4().hex[:12]}"
                created = int(time())
                events = self._stream_precomputed_result(
                    request_id=request_id,
                    request=request,
                    profile=profile,
                    context=context,
                    memory_context=memory_context,
                    tool_context=tool_context,
                    started_at=started_at,
                    runtime_result=planning_result.runtime_result,
                )
                return ChatStreamSession(
                    response_id=response_id,
                    created=created,
                    public_model=profile.public_id,
                    conversation_id=context.conversation_id,
                    events=events,
                )

            runtime_started = perf_counter()
            stream = self._ollama_client.stream_chat(
                model=profile.runtime_model,
                messages=tool_context.runtime_messages,
            )
            first_chunk = next(stream)
        except StopIteration as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned an unexpected empty stream",
            ) from exc
        except APIError as exc:
            completed_at = datetime.now(timezone.utc)
            self._log_runtime_error(
                request_id=request_id,
                profile=profile,
                runtime_started=runtime_started,
                error=exc,
            )
            persistence = self._persist_failed_completion(
                request_id=request_id,
                profile=profile,
                request=request,
                conversation_id_hint=context.conversation_id,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            self._record_memory_retrieval(
                request_id=request_id,
                profile=profile,
                conversation_id=(
                    persistence.conversation_id if persistence is not None else None
                ),
                memory_context=memory_context,
                created_at=completed_at,
            )
            self._record_tool_execution(
                request_id=request_id,
                conversation_id=(
                    persistence.conversation_id if persistence is not None else None
                ),
                model_run_id=persistence.model_run_id if persistence is not None else None,
                tool_context=tool_context,
            )
            raise

        response_id = f"chatcmpl_{uuid4().hex[:12]}"
        created = int(time())
        events = self._stream_events(
            request_id=request_id,
            request=request,
            profile=profile,
            context=context,
            memory_context=memory_context,
            tool_context=tool_context,
            started_at=started_at,
            runtime_started=runtime_started,
            first_chunk=first_chunk,
            remaining_chunks=stream,
        )
        return ChatStreamSession(
            response_id=response_id,
            created=created,
            public_model=profile.public_id,
            conversation_id=context.conversation_id,
            events=events,
        )

    def _stream_events(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        profile: RuntimeProfile,
        context: ConversationContext,
        memory_context: MemoryContext,
        tool_context: ToolContext,
        started_at: datetime,
        runtime_started: float,
        first_chunk: OllamaChatStreamChunk,
        remaining_chunks: Iterator[OllamaChatStreamChunk],
    ) -> Iterator[ChatStreamEvent]:
        chunks = self._iter_stream_chunks(first_chunk, remaining_chunks)
        content_parts: list[str] = []
        sent_any_content = False

        try:
            for chunk in chunks:
                if chunk.content:
                    content_parts.append(chunk.content)
                    yield ChatStreamEvent(
                        content=chunk.content,
                        role="assistant" if not sent_any_content else None,
                        finish_reason=None,
                    )
                    sent_any_content = True

                if not chunk.done:
                    continue

                completed_at = datetime.now(timezone.utc)
                usage = self._build_usage(
                    prompt_tokens=chunk.prompt_tokens,
                    completion_tokens=chunk.completion_tokens,
                    total_tokens=chunk.total_tokens,
                )
                self._log_runtime_success(
                    request_id=request_id,
                    profile=profile,
                    runtime_started=runtime_started,
                    usage=usage,
                )
                persistence = self._persist_successful_completion(
                    request_id=request_id,
                    profile=profile,
                    request=request,
                    conversation_id_hint=context.conversation_id,
                    response_content="".join(content_parts),
                    usage=usage,
                    started_at=started_at,
                    completed_at=completed_at,
                )
                self._record_memory_retrieval(
                    request_id=request_id,
                    profile=profile,
                    conversation_id=persistence.conversation_id,
                    memory_context=memory_context,
                    created_at=completed_at,
                )
                self._record_tool_execution(
                    request_id=request_id,
                    conversation_id=persistence.conversation_id,
                    model_run_id=persistence.model_run_id,
                    tool_context=tool_context,
                )
                self._store_memory_items(
                    request_id=request_id,
                    conversation_id=persistence.conversation_id,
                    persistence=persistence,
                    created_at=completed_at,
                )
                yield ChatStreamEvent(
                    content=None,
                    role=None,
                    finish_reason="stop",
                )
                return

            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned an incomplete stream",
            )
        except APIError as exc:
            completed_at = datetime.now(timezone.utc)
            self._log_runtime_error(
                request_id=request_id,
                profile=profile,
                runtime_started=runtime_started,
                error=exc,
            )
            persistence = self._persist_failed_completion(
                request_id=request_id,
                profile=profile,
                request=request,
                conversation_id_hint=context.conversation_id,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            self._record_memory_retrieval(
                request_id=request_id,
                profile=profile,
                conversation_id=(
                    persistence.conversation_id if persistence is not None else None
                ),
                memory_context=memory_context,
                created_at=completed_at,
            )
            self._record_tool_execution(
                request_id=request_id,
                conversation_id=(
                    persistence.conversation_id if persistence is not None else None
                ),
                model_run_id=persistence.model_run_id if persistence is not None else None,
                tool_context=tool_context,
            )
            raise

    def _iter_stream_chunks(
        self,
        first_chunk: OllamaChatStreamChunk,
        remaining_chunks: Iterator[OllamaChatStreamChunk],
    ) -> Iterator[OllamaChatStreamChunk]:
        yield first_chunk
        yield from remaining_chunks

    def _build_success_result(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        profile: RuntimeProfile,
        conversation_id_hint: str | None,
        memory_context: MemoryContext,
        tool_context: ToolContext,
        runtime_result: OllamaChatResult,
        started_at: datetime,
        completed_at: datetime,
        runtime_started: float,
        log_runtime: bool = True,
    ) -> ChatResult:
        response_id = f"chatcmpl_{uuid4().hex[:12]}"
        created = int(time())
        usage = self._build_usage(
            prompt_tokens=runtime_result.prompt_tokens,
            completion_tokens=runtime_result.completion_tokens,
            total_tokens=runtime_result.total_tokens,
        )

        if log_runtime:
            self._log_runtime_success(
                request_id=request_id,
                profile=profile,
                runtime_started=runtime_started,
                usage=usage,
            )
        persistence = self._persist_successful_completion(
            request_id=request_id,
            profile=profile,
            request=request,
            conversation_id_hint=conversation_id_hint,
            response_content=runtime_result.content,
            usage=usage,
            started_at=started_at,
            completed_at=completed_at,
        )
        self._record_memory_retrieval(
            request_id=request_id,
            profile=profile,
            conversation_id=persistence.conversation_id,
            memory_context=memory_context,
            created_at=completed_at,
        )
        self._record_tool_execution(
            request_id=request_id,
            conversation_id=persistence.conversation_id,
            model_run_id=persistence.model_run_id,
            tool_context=tool_context,
        )
        self._store_memory_items(
            request_id=request_id,
            conversation_id=persistence.conversation_id,
            persistence=persistence,
            created_at=completed_at,
        )

        return ChatResult(
            response_id=response_id,
            created=created,
            public_model=profile.public_id,
            conversation_id=persistence.conversation_id,
            content=runtime_result.content,
            choices=[
                ChatCompletionChoice(
                    message=ChatCompletionChoiceMessage(content=runtime_result.content)
                )
            ],
            usage=usage,
        )

    def _stream_precomputed_result(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        profile: RuntimeProfile,
        context: ConversationContext,
        memory_context: MemoryContext,
        tool_context: ToolContext,
        started_at: datetime,
        runtime_result: OllamaChatResult,
    ) -> Iterator[ChatStreamEvent]:
        if runtime_result.content:
            yield ChatStreamEvent(
                content=runtime_result.content,
                role="assistant",
                finish_reason=None,
            )

        completed_at = datetime.now(timezone.utc)
        usage = self._build_usage(
            prompt_tokens=runtime_result.prompt_tokens,
            completion_tokens=runtime_result.completion_tokens,
            total_tokens=runtime_result.total_tokens,
        )
        persistence = self._persist_successful_completion(
            request_id=request_id,
            profile=profile,
            request=request,
            conversation_id_hint=context.conversation_id,
            response_content=runtime_result.content,
            usage=usage,
            started_at=started_at,
            completed_at=completed_at,
        )
        self._record_memory_retrieval(
            request_id=request_id,
            profile=profile,
            conversation_id=persistence.conversation_id,
            memory_context=memory_context,
            created_at=completed_at,
        )
        self._record_tool_execution(
            request_id=request_id,
            conversation_id=persistence.conversation_id,
            model_run_id=persistence.model_run_id,
            tool_context=tool_context,
        )
        self._store_memory_items(
            request_id=request_id,
            conversation_id=persistence.conversation_id,
            persistence=persistence,
            created_at=completed_at,
        )
        yield ChatStreamEvent(
            content=None,
            role=None,
            finish_reason="stop",
        )

    def _persist_successful_completion(
        self,
        *,
        request_id: str,
        profile: RuntimeProfile,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None,
        response_content: str,
        usage: ChatCompletionUsage | None,
        started_at: datetime,
        completed_at: datetime,
    ) -> ChatPersistenceResult:
        storage_started = perf_counter()
        persistence = self._repository.record_successful_completion(
            request_id=request_id,
            public_model=profile.public_id,
            runtime_model=profile.runtime_model,
            request_messages=request.messages,
            conversation_id_hint=conversation_id_hint,
            response_content=response_content,
            usage=usage,
            started_at=started_at,
            completed_at=completed_at,
        )
        log_event(
            "chat_storage_completed",
            request_id=request_id,
            outcome="success",
            duration_ms=round((perf_counter() - storage_started) * 1000, 2),
            conversation_id=persistence.conversation_id,
            model_run_id=persistence.model_run_id,
            assistant_message_id=persistence.assistant_message_id,
        )
        return persistence

    def _persist_failed_completion(
        self,
        *,
        request_id: str,
        profile: RuntimeProfile,
        request: ChatCompletionRequest,
        conversation_id_hint: str | None,
        started_at: datetime,
        completed_at: datetime,
        error: APIError,
    ) -> ChatPersistenceResult | None:
        storage_started = perf_counter()
        try:
            persistence = self._repository.record_failed_completion(
                request_id=request_id,
                public_model=profile.public_id,
                runtime_model=profile.runtime_model,
                request_messages=request.messages,
                conversation_id_hint=conversation_id_hint,
                error_type=error.error_type,
                error_code=error.code,
                error_message=error.message,
                started_at=started_at,
                completed_at=completed_at,
            )
            log_event(
                "chat_storage_completed",
                level=logging.WARNING,
                request_id=request_id,
                outcome="persisted_failure",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=persistence.conversation_id,
                model_run_id=persistence.model_run_id,
            )
            return persistence
        except APIError:
            log_event(
                "chat_storage_completed",
                level=logging.ERROR,
                request_id=request_id,
                outcome="error",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
            )
            return None

    def _prepare_memory_context(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
    ) -> MemoryContext:
        if not self._settings.memory_enabled or not self._settings.ollama_embed_model:
            return MemoryContext(runtime_messages=list(request.messages))

        query_text = self._latest_user_message(request.messages)
        if not query_text:
            return MemoryContext(runtime_messages=list(request.messages))

        retrieval_started = perf_counter()
        try:
            embeddings = self._ollama_client.embed(
                model=self._settings.ollama_embed_model,
                input_text=query_text,
            )
            query_embedding = self._require_single_embedding(embeddings)
            hits = tuple(
                self._repository.retrieve_memory(
                    query_embedding=query_embedding,
                    limit=self._settings.memory_top_k,
                    min_score=self._settings.memory_min_score,
                )
            )
            retrieval = MemoryRetrievalRecord(
                query_text=query_text,
                status="completed",
                top_k=self._settings.memory_top_k,
                latency_ms=round((perf_counter() - retrieval_started) * 1000, 2),
                hits=hits,
            )
            self._log_memory_retrieval(
                request_id=request_id,
                outcome="success",
                retrieval=retrieval,
            )
            if not hits:
                return MemoryContext(
                    runtime_messages=list(request.messages),
                    retrieval=retrieval,
                )
            return MemoryContext(
                runtime_messages=self._augment_messages_with_memory(
                    request.messages,
                    hits,
                ),
                retrieval=retrieval,
            )
        except APIError as exc:
            retrieval = MemoryRetrievalRecord(
                query_text=query_text,
                status="error",
                top_k=self._settings.memory_top_k,
                latency_ms=round((perf_counter() - retrieval_started) * 1000, 2),
                error_type=exc.error_type,
                error_code=exc.code,
            )
            self._log_memory_retrieval(
                request_id=request_id,
                outcome="error",
                retrieval=retrieval,
            )
            return MemoryContext(
                runtime_messages=list(request.messages),
                retrieval=retrieval,
            )

    def _prepare_tool_context(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        base_messages: list[ChatMessage],
    ) -> ToolContext:
        if not self._is_web_search_requested(request):
            return ToolContext(runtime_messages=list(base_messages))

        query_text = self._latest_user_message(request.messages)
        if not query_text:
            return ToolContext(runtime_messages=list(base_messages))

        return self._execute_tool_decision(
            request_id=request_id,
            base_messages=base_messages,
            decision=ToolPlanningDecision(
                tool_name="web-search",
                arguments={"query": query_text},
            ),
            annotate_failures=False,
            request_source=self._extract_request_source(request),
        )

    def _prepare_model_driven_tool_context(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        base_messages: list[ChatMessage],
        decision: ToolPlanningDecision,
    ) -> ToolContext:
        return self._execute_tool_decision(
            request_id=request_id,
            base_messages=base_messages,
            decision=decision,
            annotate_failures=True,
            request_source=self._extract_request_source(request),
        )

    def _execute_tool_decision(
        self,
        *,
        request_id: str,
        base_messages: list[ChatMessage],
        decision: ToolPlanningDecision,
        annotate_failures: bool,
        request_source: str | None,
    ) -> ToolContext:
        policy = self._evaluate_tool_policy(
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

    def _evaluate_tool_policy(
        self,
        tool_name: str,
        *,
        request_source: str | None = None,
    ) -> ToolPolicyDecision:
        normalized_tool = self._normalize_tool_name(tool_name)

        if normalized_tool not in _SUPPORTED_TOOL_NAMES:
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
            if self._web_search_client is None:
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

    def _normalize_tool_name(self, tool_name: str) -> str:
        return tool_name.strip().casefold()

    def _extract_request_source(
        self,
        request: ChatCompletionRequest,
    ) -> str | None:
        if not request.metadata:
            return None
        value = request.metadata.get("source")
        if not value:
            return None
        normalized = value.strip().casefold()
        return normalized or None

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
                runtime_messages=self._augment_messages_with_search_results(
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
                    runtime_messages=self._augment_messages_with_spotify_results(
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
                runtime_messages=self._augment_messages_with_spotify_action(
                    base_messages=base_messages,
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

    def _record_tool_execution(
        self,
        *,
        request_id: str,
        conversation_id: str | None,
        model_run_id: str | None,
        tool_context: ToolContext,
    ) -> None:
        if tool_context.execution is None or conversation_id is None:
            return

        storage_started = perf_counter()
        try:
            self._repository.record_tool_execution(
                conversation_id=conversation_id,
                request_id=request_id,
                model_run_id=model_run_id,
                tool_execution=tool_context.execution,
            )
            log_event(
                "chat_tool_audit_completed",
                request_id=request_id,
                outcome="success",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=conversation_id,
                model_run_id=model_run_id,
                tool_name=tool_context.execution.tool_name,
                tool_status=tool_context.execution.status,
                invocation_id=tool_context.execution.invocation_id,
            )
        except APIError as exc:
            log_event(
                "chat_tool_audit_completed",
                level=logging.WARNING,
                request_id=request_id,
                outcome="error",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=conversation_id,
                model_run_id=model_run_id,
                tool_name=tool_context.execution.tool_name,
                error_type=exc.error_type,
                error_code=exc.code,
            )

    def _record_memory_retrieval(
        self,
        *,
        request_id: str,
        profile: RuntimeProfile,
        conversation_id: str | None,
        memory_context: MemoryContext,
        created_at: datetime,
    ) -> None:
        if memory_context.retrieval is None or conversation_id is None:
            return

        storage_started = perf_counter()
        try:
            self._repository.record_retrieval(
                conversation_id=conversation_id,
                request_id=request_id,
                public_model=profile.public_id,
                retrieval=memory_context.retrieval,
                created_at=created_at,
            )
            log_event(
                "chat_memory_audit_completed",
                request_id=request_id,
                outcome="success",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=conversation_id,
                retrieval_status=memory_context.retrieval.status,
                retrieval_hit_count=len(memory_context.retrieval.hits),
            )
        except APIError as exc:
            log_event(
                "chat_memory_audit_completed",
                level=logging.WARNING,
                request_id=request_id,
                outcome="error",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=conversation_id,
                error_type=exc.error_type,
                error_code=exc.code,
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

    def _store_memory_items(
        self,
        *,
        request_id: str,
        conversation_id: str,
        persistence: ChatPersistenceResult,
        created_at: datetime,
    ) -> None:
        if not self._settings.memory_enabled or not self._settings.ollama_embed_model:
            return

        candidate_messages = tuple(
            message
            for message in persistence.persisted_messages
            if self._is_memory_candidate(message)
        )
        if not candidate_messages:
            return

        try:
            embeddings = self._ollama_client.embed(
                model=self._settings.ollama_embed_model,
                input_text=[message.content for message in candidate_messages],
            )
            if len(embeddings) != len(candidate_messages) or any(
                not embedding for embedding in embeddings
            ):
                raise APIError(
                    status_code=502,
                    error_type="upstream_error",
                    code="dependency_bad_response",
                    message="Model runtime returned an unexpected embedding payload",
                )
        except APIError as exc:
            log_event(
                "chat_memory_materialization_completed",
                level=logging.WARNING,
                request_id=request_id,
                outcome="error",
                conversation_id=conversation_id,
                error_type=exc.error_type,
                error_code=exc.code,
            )
            return

        storage_started = perf_counter()
        try:
            self._repository.store_memory_items(
                conversation_id=conversation_id,
                messages=candidate_messages,
                embeddings=embeddings,
                embedding_model=self._settings.ollama_embed_model,
                created_at=created_at,
            )
            log_event(
                "chat_memory_materialization_completed",
                request_id=request_id,
                outcome="success",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=conversation_id,
                memory_item_count=len(candidate_messages),
            )
        except APIError as exc:
            log_event(
                "chat_memory_materialization_completed",
                level=logging.WARNING,
                request_id=request_id,
                outcome="error",
                duration_ms=round((perf_counter() - storage_started) * 1000, 2),
                conversation_id=conversation_id,
                error_type=exc.error_type,
                error_code=exc.code,
            )

    def _log_memory_retrieval(
        self,
        *,
        request_id: str,
        outcome: str,
        retrieval: MemoryRetrievalRecord,
    ) -> None:
        level = logging.INFO if outcome == "success" else logging.WARNING
        log_event(
            "chat_memory_retrieval_completed",
            level=level,
            request_id=request_id,
            outcome=outcome,
            retrieval_status=retrieval.status,
            duration_ms=retrieval.latency_ms,
            retrieval_hit_count=len(retrieval.hits),
            error_type=retrieval.error_type,
            error_code=retrieval.error_code,
        )

    def _augment_messages_with_memory(
        self,
        messages: list[ChatMessage],
        hits: tuple[MemorySearchHit, ...],
    ) -> list[ChatMessage]:
        memory_lines = "\n".join(f"- {hit.content}" for hit in hits)
        memory_message = ChatMessage(
            role="system",
            content=(
                "Relevant memory from prior conversations:\n"
                f"{memory_lines}\n"
                "Use it only when helpful and do not treat it as authoritative "
                "if the current conversation conflicts with it."
            ),
        )
        insert_at = 0
        while insert_at < len(messages) and messages[insert_at].role == "system":
            insert_at += 1
        return [
            *messages[:insert_at],
            memory_message,
            *messages[insert_at:],
        ]

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

    def _augment_messages_with_spotify_results(
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
        insert_at = 0
        while insert_at < len(messages) and messages[insert_at].role == "system":
            insert_at += 1
        return [
            *messages[:insert_at],
            spotify_message,
            *messages[insert_at:],
        ]

    def _augment_messages_with_spotify_action(
        self,
        *,
        base_messages: list[ChatMessage],
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
        insert_at = 0
        while insert_at < len(base_messages) and base_messages[insert_at].role == "system":
            insert_at += 1
        return [
            *base_messages[:insert_at],
            action_message,
            *base_messages[insert_at:],
        ]

    def _augment_messages_with_search_results(
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
        insert_at = 0
        while insert_at < len(messages) and messages[insert_at].role == "system":
            insert_at += 1
        return [
            *messages[:insert_at],
            search_message,
            *messages[insert_at:],
        ]

    def _augment_messages_with_tool_unavailable(
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

        unavailable_message = ChatMessage(
            role="system",
            content=unavailable_text,
        )
        insert_at = 0
        while insert_at < len(messages) and messages[insert_at].role == "system":
            insert_at += 1
        return [
            *messages[:insert_at],
            unavailable_message,
            *messages[insert_at:],
        ]

    def _build_tool_planning_messages(
        self,
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        tool_examples: list[str] = []
        if self._settings.web_search_enabled and self._web_search_client is not None:
            tool_examples.append('{"tool":"web-search","query":"..."}')
        if self._settings.is_spotify_client_configured():
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

    def _maybe_run_tool_planning_pass(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        profile: RuntimeProfile,
        base_messages: list[ChatMessage],
    ) -> ToolPlanningResult | None:
        if not self._should_attempt_model_driven_web_search(request):
            return None

        planning_messages = self._build_tool_planning_messages(base_messages)
        runtime_started = perf_counter()
        runtime_result = self._ollama_client.chat(
            model=profile.runtime_model,
            messages=planning_messages,
        )

        usage = self._build_usage(
            prompt_tokens=runtime_result.prompt_tokens,
            completion_tokens=runtime_result.completion_tokens,
            total_tokens=runtime_result.total_tokens,
        )
        decision = self._parse_tool_planning_decision(runtime_result.content)
        content_outcome = self._tool_planning_content_outcome(
            runtime_result.content,
            decision,
        )
        self._log_runtime_success(
            request_id=request_id,
            profile=profile,
            runtime_started=runtime_started,
            usage=usage,
            phase="planning",
        )
        self._log_tool_planning(
            request_id=request_id,
            outcome=content_outcome,
            decision=decision,
        )
        return ToolPlanningResult(
            runtime_result=runtime_result,
            decision=decision,
            content_outcome=content_outcome,
        )

    def _parse_tool_planning_decision(
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

        tool_name = self._normalize_tool_name(tool_name)
        if not tool_name:
            return None

        arguments: dict[str, object] = {
            key: value for key, value in payload.items() if key != "tool"
        }

        if tool_name == "web-search":
            query = arguments.get("query")
            if not isinstance(query, str):
                return None
            query = query.strip()
            if not query:
                return None
            arguments["query"] = query
        elif tool_name == "spotify-search":
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

        if tool_name not in _SUPPORTED_TOOL_NAMES:
            return None

        return ToolPlanningDecision(tool_name=tool_name, arguments=arguments)

    def _tool_planning_content_outcome(
        self,
        content: str,
        decision: ToolPlanningDecision | None,
    ) -> str:
        if decision is not None:
            return "tool_requested"
        if content.strip().startswith("{"):
            return "invalid_directive"
        return "respond_directly"

    def _log_tool_planning(
        self,
        *,
        request_id: str,
        outcome: str,
        decision: ToolPlanningDecision | None,
    ) -> None:
        level = logging.INFO if outcome != "invalid_directive" else logging.WARNING
        log_event(
            "chat_tool_planning_completed",
            level=level,
            request_id=request_id,
            outcome=outcome,
            tool_name=decision.tool_name if decision is not None else None,
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
        return self._augment_messages_with_tool_unavailable(base_messages, tool_name)

    def _latest_user_message(self, messages: list[ChatMessage]) -> str | None:
        for message in reversed(messages):
            content = message.content.strip()
            if message.role == "user" and content:
                return content
        return None

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

    def _is_web_search_requested(self, request: ChatCompletionRequest) -> bool:
        if not request.metadata:
            return False
        value = request.metadata.get("web_search")
        if not value:
            return False
        return value.strip().casefold() in {"1", "true", "yes", "on"}

    def _should_attempt_model_driven_web_search(
        self,
        request: ChatCompletionRequest,
    ) -> bool:
        if request.metadata and "web_search" in request.metadata:
            return False
        if (
            not self._settings.web_search_enabled
            and not self._settings.is_spotify_client_configured()
        ):
            return False
        if self._settings.web_search_enabled and self._web_search_client is None:
            if not self._settings.is_spotify_client_configured():
                return False
        return self._latest_user_message(request.messages) is not None

    def _require_single_embedding(
        self,
        embeddings: list[list[float]],
    ) -> list[float]:
        if len(embeddings) != 1 or not embeddings[0]:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned an unexpected embedding payload",
            )
        return embeddings[0]

    def _is_memory_candidate(self, message: PersistedMessage) -> bool:
        content = message.content.strip()
        if message.role != "user" or message.source != "request_transcript":
            return False
        if len(content) < 15:
            return False
        if content.endswith("?"):
            return False
        return True

    def _log_runtime_success(
        self,
        *,
        request_id: str,
        profile: RuntimeProfile,
        runtime_started: float,
        usage: ChatCompletionUsage | None,
        phase: str = "final",
    ) -> None:
        log_event(
            "chat_runtime_completed",
            request_id=request_id,
            public_model=profile.public_id,
            runtime_model=profile.runtime_model,
            dependency="ollama",
            phase=phase,
            outcome="success",
            duration_ms=round((perf_counter() - runtime_started) * 1000, 2),
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
        )

    def _log_runtime_error(
        self,
        *,
        request_id: str,
        profile: RuntimeProfile,
        runtime_started: float,
        error: APIError,
        phase: str = "final",
    ) -> None:
        log_event(
            "chat_runtime_completed",
            level=logging.WARNING,
            request_id=request_id,
            public_model=profile.public_id,
            runtime_model=profile.runtime_model,
            dependency="ollama",
            phase=phase,
            outcome="error",
            duration_ms=round((perf_counter() - runtime_started) * 1000, 2),
            error_type=error.error_type,
            error_code=error.code,
        )

    def _build_usage(
        self,
        *,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
    ) -> ChatCompletionUsage | None:
        usage = ChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        if (
            usage.prompt_tokens is None
            and usage.completion_tokens is None
            and usage.total_tokens is None
        ):
            return None
        return usage

    def _resolve_profile(self, public_model: str) -> RuntimeProfile:
        if public_model == "assistant-v1":
            return RuntimeProfile(
                public_id=public_model,
                runtime_model=self._settings.ollama_chat_model,
            )
        if public_model == "assistant-fast":
            return RuntimeProfile(
                public_id=public_model,
                runtime_model=self._settings.ollama_fast_chat_model,
            )

        raise APIError(
            status_code=422,
            error_type="validation_error",
            code="unknown_profile",
            message="Unknown assistant profile",
        )

    def _extract_conversation_hint(
        self, request: ChatCompletionRequest
    ) -> str | None:
        if not request.metadata:
            return None

        for key in ("conversation_id", "chat_id", "session_id"):
            value = request.metadata.get(key)
            if value:
                return value
        return None
