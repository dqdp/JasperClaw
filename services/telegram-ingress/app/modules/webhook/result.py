from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WebhookResult:
    status: str
    update_id: int | None = None
    chat_id: int | None = None
    message_id: int | None = None
    conversation_id: str | None = None
    reason: str | None = None

    @classmethod
    def ok(
        cls,
        *,
        update_id: int,
        chat_id: int,
        message_id: int,
        conversation_id: str,
        status: str,
    ) -> "WebhookResult":
        return cls(
            status=status,
            update_id=update_id,
            chat_id=chat_id,
            message_id=message_id,
            conversation_id=conversation_id,
        )

    @classmethod
    def ignored(cls, *, reason: str) -> "WebhookResult":
        return cls(status="ignored", reason=reason)

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}
