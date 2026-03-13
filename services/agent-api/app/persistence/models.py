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
class ChatPersistenceResult:
    conversation_id: str
    assistant_message_id: str | None
    model_run_id: str
    persisted_messages: tuple[PersistedMessage, ...] = ()


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
