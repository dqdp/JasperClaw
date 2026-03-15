from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PersistedMessage:
    message_id: str
    message_index: int
    role: str
    content: str
    source: str


@dataclass(frozen=True, slots=True)
class MemorySearchHit:
    memory_item_id: str
    source_message_id: str
    content: str
    score: float


@dataclass(frozen=True, slots=True)
class MemoryRetrievalRecord:
    query_text: str
    status: str
    top_k: int
    latency_ms: float
    hits: tuple[MemorySearchHit, ...] = ()
    error_type: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryLifecycleTransitionResult:
    memory_item_id: str
    previous_status: str
    current_status: str
    changed: bool


@dataclass(frozen=True, slots=True)
class ToolExecutionRecord:
    invocation_id: str
    tool_name: str
    status: str
    arguments: dict[str, object]
    latency_ms: float
    started_at: datetime
    completed_at: datetime
    output: dict[str, object] | None = None
    adapter_name: str | None = None
    provider: str | None = None
    policy_decision: str | None = None
    error_type: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class PendingToolConfirmationRecord:
    confirmation_id: str
    conversation_id: str
    request_id: str
    source_class: str
    tool_name: str
    status: str
    clarification_count: int
    arguments: dict[str, object]
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChatPersistenceResult:
    conversation_id: str
    assistant_message_id: str | None
    model_run_id: str
    persisted_messages: tuple[PersistedMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class IngressCompletionRecord:
    idempotency_key: str
    source: str
    public_model: str
    conversation_id: str
    content: str
    usage: "ChatCompletionUsage | None"


@dataclass(frozen=True, slots=True)
class TranscriptionPersistenceResult:
    conversation_id: str
    persisted_message: PersistedMessage


@dataclass(frozen=True, slots=True)
class TranscriptMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ConversationContext:
    conversation_id: str
    existing_message_count: int
    matched_request_message_count: int
    conversation_created: bool
