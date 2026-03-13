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
from app.clients.search import WebSearchClient
from app.clients.spotify import SpotifyClient
from app.core.config import Settings
from app.core.errors import APIError
from app.core.logging import log_event
from app.modules.chat.executor import ToolContext, ToolExecutor
from app.modules.chat.formatters import ChatPromptFormatter
from app.modules.chat.memory import MemoryContext, MemoryService
from app.modules.chat.planner import (
    SUPPORTED_TOOL_NAMES,
    ToolPlanner,
    ToolPlanningDecision,
    ToolPlanningResult,
)
from app.modules.chat.policy import ToolPolicyEngine
from app.repositories import (
    ChatPersistenceResult,
    ChatRepository,
    ConversationContext,
    ToolExecutionRecord,
)
from app.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionUsage,
    ChatMessage,
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
class ClientConversationBinding:
    source: str
    conversation_id: str


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
        self._tool_planner = ToolPlanner(
            web_search_available=(
                self._settings.web_search_enabled and self._web_search_client is not None
            ),
            spotify_available=self._settings.is_spotify_client_configured(),
        )
        self._prompt_formatter = ChatPromptFormatter()
        self._memory_service = MemoryService(
            settings=self._settings,
            ollama_client=self._ollama_client,
            repository=self._repository,
            prompt_formatter=self._prompt_formatter,
        )
        self._tool_policy = ToolPolicyEngine(
            settings=self._settings,
            web_search_adapter_available=self._web_search_client is not None,
        )
        self._tool_executor = ToolExecutor(
            settings=self._settings,
            web_search_client=self._web_search_client,
            spotify_client=self._spotify_client,
            prompt_formatter=self._prompt_formatter,
            policy_engine=self._tool_policy,
        )

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
        client_binding = self._extract_client_conversation_binding(request)
        memory_context = self._memory_service.prepare_context(
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
            if self._tool_planner.is_web_search_requested(request):
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
                    client_binding=client_binding,
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
                client_binding=client_binding,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            self._memory_service.record_retrieval(
                request_id=request_id,
                public_model=profile.public_id,
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
            client_binding=client_binding,
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
        client_binding = self._extract_client_conversation_binding(request)
        started_at = datetime.now(timezone.utc)
        context = self._repository.prepare_conversation(
            public_model=profile.public_id,
            request_messages=request.messages,
            conversation_id_hint=resolved_conversation_hint,
            client_source=client_binding.source if client_binding is not None else None,
            client_conversation_id=(
                client_binding.conversation_id if client_binding is not None else None
            ),
            created_at=started_at,
        )
        memory_context = self._memory_service.prepare_context(
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
            if self._tool_planner.is_web_search_requested(request):
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
                    client_binding=client_binding,
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
                client_binding=client_binding,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            self._memory_service.record_retrieval(
                request_id=request_id,
                public_model=profile.public_id,
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
            client_binding=client_binding,
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
        client_binding: ClientConversationBinding | None,
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
                    client_binding=client_binding,
                    response_content="".join(content_parts),
                    usage=usage,
                    started_at=started_at,
                    completed_at=completed_at,
                )
                self._memory_service.record_retrieval(
                    request_id=request_id,
                    public_model=profile.public_id,
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
                self._memory_service.store_items(
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
                client_binding=client_binding,
                started_at=started_at,
                completed_at=completed_at,
                error=exc,
            )
            self._memory_service.record_retrieval(
                request_id=request_id,
                public_model=profile.public_id,
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
        client_binding: ClientConversationBinding | None,
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
            client_binding=client_binding,
            response_content=runtime_result.content,
            usage=usage,
            started_at=started_at,
            completed_at=completed_at,
        )
        self._memory_service.record_retrieval(
            request_id=request_id,
            public_model=profile.public_id,
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
        self._memory_service.store_items(
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
        client_binding: ClientConversationBinding | None,
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
            client_binding=client_binding,
            response_content=runtime_result.content,
            usage=usage,
            started_at=started_at,
            completed_at=completed_at,
        )
        self._memory_service.record_retrieval(
            request_id=request_id,
            public_model=profile.public_id,
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
        self._memory_service.store_items(
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
        client_binding: ClientConversationBinding | None,
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
            client_source=client_binding.source if client_binding is not None else None,
            client_conversation_id=(
                client_binding.conversation_id if client_binding is not None else None
            ),
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
        client_binding: ClientConversationBinding | None,
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
                client_source=client_binding.source if client_binding is not None else None,
                client_conversation_id=(
                    client_binding.conversation_id if client_binding is not None else None
                ),
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

    def _prepare_tool_context(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        base_messages: list[ChatMessage],
    ) -> ToolContext:
        if not self._tool_planner.is_web_search_requested(request):
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
        return self._tool_executor.execute(
            request_id=request_id,
            base_messages=base_messages,
            decision=decision,
            annotate_failures=annotate_failures,
            request_source=request_source,
        )

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

    def _build_tool_planning_messages(
        self,
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        return self._tool_planner.build_planning_messages(messages)

    def _maybe_run_tool_planning_pass(
        self,
        *,
        request_id: str,
        request: ChatCompletionRequest,
        profile: RuntimeProfile,
        base_messages: list[ChatMessage],
    ) -> ToolPlanningResult | None:
        if not self._tool_planner.should_attempt_model_driven_tool_use(request):
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
        decision = self._tool_planner.parse_decision(runtime_result.content)
        content_outcome = self._tool_planner.content_outcome(
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
        return self._tool_planner.parse_decision(content)

    def _tool_planning_content_outcome(
        self,
        content: str,
        decision: ToolPlanningDecision | None,
    ) -> str:
        return self._tool_planner.content_outcome(content, decision)

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

    def _latest_user_message(self, messages: list[ChatMessage]) -> str | None:
        for message in reversed(messages):
            content = message.content.strip()
            if message.role == "user" and content:
                return content
        return None

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

        return request.metadata.get("conversation_id") or None

    def _extract_client_conversation_binding(
        self,
        request: ChatCompletionRequest,
    ) -> ClientConversationBinding | None:
        if not request.metadata:
            return None

        source = (request.metadata.get("source") or "").strip()
        client_conversation_id = (
            request.metadata.get("client_conversation_id") or ""
        ).strip()
        if not source or not client_conversation_id:
            return None

        return ClientConversationBinding(
            source=source,
            conversation_id=client_conversation_id,
        )
