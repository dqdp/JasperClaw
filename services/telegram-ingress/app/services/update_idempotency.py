from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Protocol

import psycopg


class TelegramUpdateStorageError(RuntimeError):
    """Raised when durable update state cannot be persisted or loaded."""


@dataclass(frozen=True, slots=True)
class TelegramUpdateClaim:
    update_key: str
    action: str
    status: str
    response_text: str | None = None
    conversation_id: str | None = None


class TelegramUpdateRepository(Protocol):
    def claim_update(
        self,
        *,
        update_key: str,
        update_id: int,
        chat_id: int,
        message_id: int,
        now: datetime,
        locked_until: datetime,
    ) -> TelegramUpdateClaim: ...

    def stage_reply(
        self,
        *,
        update_key: str,
        conversation_id: str,
        response_text: str,
        staged_at: datetime,
        locked_until: datetime,
    ) -> None: ...

    def mark_completed(
        self,
        *,
        update_key: str,
        completed_at: datetime,
    ) -> None: ...

    def abandon_processing(
        self,
        *,
        update_key: str,
    ) -> None: ...

    def release_retry(
        self,
        *,
        update_key: str,
        released_at: datetime,
    ) -> None: ...


class InMemoryTelegramUpdateRepository:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, object]] = {}
        self._lock = Lock()

    def claim_update(
        self,
        *,
        update_key: str,
        update_id: int,
        chat_id: int,
        message_id: int,
        now: datetime,
        locked_until: datetime,
    ) -> TelegramUpdateClaim:
        now_utc = now.astimezone(timezone.utc)
        locked_until_utc = locked_until.astimezone(timezone.utc)
        with self._lock:
            record = self._records.get(update_key)
            if record is None:
                self._records[update_key] = {
                    "update_id": update_id,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "status": "processing",
                    "response_text": None,
                    "conversation_id": None,
                    "locked_until": locked_until_utc,
                    "updated_at": now_utc,
                    "completed_at": None,
                }
                return TelegramUpdateClaim(
                    update_key=update_key,
                    action="claimed",
                    status="processing",
                )
            status = str(record["status"])
            current_locked_until = record.get("locked_until")
            if status == "completed":
                return TelegramUpdateClaim(
                    update_key=update_key,
                    action="duplicate_completed",
                    status="completed",
                    response_text=self._maybe_str(record.get("response_text")),
                    conversation_id=self._maybe_str(record.get("conversation_id")),
                )
            if isinstance(current_locked_until, datetime) and current_locked_until > now_utc:
                return TelegramUpdateClaim(
                    update_key=update_key,
                    action="retry_later",
                    status=status,
                    response_text=self._maybe_str(record.get("response_text")),
                    conversation_id=self._maybe_str(record.get("conversation_id")),
                )
            record["locked_until"] = locked_until_utc
            record["updated_at"] = now_utc
            return TelegramUpdateClaim(
                update_key=update_key,
                action="claimed",
                status=status,
                response_text=self._maybe_str(record.get("response_text")),
                conversation_id=self._maybe_str(record.get("conversation_id")),
            )

    def stage_reply(
        self,
        *,
        update_key: str,
        conversation_id: str,
        response_text: str,
        staged_at: datetime,
        locked_until: datetime,
    ) -> None:
        staged_at_utc = staged_at.astimezone(timezone.utc)
        locked_until_utc = locked_until.astimezone(timezone.utc)
        with self._lock:
            record = self._records.get(update_key)
            if record is None:
                raise TelegramUpdateStorageError("telegram update missing while staging reply")
            record["status"] = "pending_send"
            record["conversation_id"] = conversation_id
            record["response_text"] = response_text
            record["locked_until"] = locked_until_utc
            record["updated_at"] = staged_at_utc

    def mark_completed(
        self,
        *,
        update_key: str,
        completed_at: datetime,
    ) -> None:
        completed_at_utc = completed_at.astimezone(timezone.utc)
        with self._lock:
            record = self._records.get(update_key)
            if record is None:
                raise TelegramUpdateStorageError(
                    "telegram update missing while marking completed"
                )
            record["status"] = "completed"
            record["locked_until"] = None
            record["updated_at"] = completed_at_utc
            record["completed_at"] = completed_at_utc

    def abandon_processing(
        self,
        *,
        update_key: str,
    ) -> None:
        with self._lock:
            record = self._records.get(update_key)
            if record is None:
                return
            if record.get("status") == "processing":
                self._records.pop(update_key, None)

    def release_retry(
        self,
        *,
        update_key: str,
        released_at: datetime,
    ) -> None:
        released_at_utc = released_at.astimezone(timezone.utc)
        with self._lock:
            record = self._records.get(update_key)
            if record is None:
                return
            if record.get("status") in {"processing", "pending_send"}:
                record["locked_until"] = released_at_utc
                record["updated_at"] = released_at_utc

    @staticmethod
    def _maybe_str(value: object) -> str | None:
        return value if isinstance(value, str) else None


class PostgresTelegramUpdateRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def claim_update(
        self,
        *,
        update_key: str,
        update_id: int,
        chat_id: int,
        message_id: int,
        now: datetime,
        locked_until: datetime,
    ) -> TelegramUpdateClaim:
        now_utc = now.astimezone(timezone.utc)
        locked_until_utc = locked_until.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> TelegramUpdateClaim:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO telegram_ingress_updates (
                        update_key,
                        update_id,
                        chat_id,
                        message_id,
                        status,
                        response_text,
                        conversation_id,
                        locked_until,
                        created_at,
                        updated_at,
                        completed_at
                    )
                    VALUES (%s, %s, %s, %s, 'processing', NULL, NULL, %s, %s, %s, NULL)
                    ON CONFLICT (update_key) DO NOTHING
                    """,
                    (
                        update_key,
                        update_id,
                        chat_id,
                        message_id,
                        locked_until_utc,
                        now_utc,
                        now_utc,
                    ),
                )
                if cur.rowcount == 1:
                    return TelegramUpdateClaim(
                        update_key=update_key,
                        action="claimed",
                        status="processing",
                    )
                cur.execute(
                    """
                    SELECT status, response_text, conversation_id, locked_until
                    FROM telegram_ingress_updates
                    WHERE update_key = %s
                    FOR UPDATE
                    """,
                    (update_key,),
                )
                row = cur.fetchone()
                if row is None:
                    raise TelegramUpdateStorageError(
                        "telegram update missing after claim conflict"
                    )
                status, response_text, conversation_id, current_locked_until = row
                if status == "completed":
                    return TelegramUpdateClaim(
                        update_key=update_key,
                        action="duplicate_completed",
                        status="completed",
                        response_text=response_text,
                        conversation_id=conversation_id,
                    )
                if current_locked_until is not None and current_locked_until > now_utc:
                    return TelegramUpdateClaim(
                        update_key=update_key,
                        action="retry_later",
                        status=status,
                        response_text=response_text,
                        conversation_id=conversation_id,
                    )
                cur.execute(
                    """
                    UPDATE telegram_ingress_updates
                    SET locked_until = %s, updated_at = %s
                    WHERE update_key = %s
                    """,
                    (
                        locked_until_utc,
                        now_utc,
                        update_key,
                    ),
                )
                return TelegramUpdateClaim(
                    update_key=update_key,
                    action="claimed",
                    status=status,
                    response_text=response_text,
                    conversation_id=conversation_id,
                )

        return self._execute(write)

    def stage_reply(
        self,
        *,
        update_key: str,
        conversation_id: str,
        response_text: str,
        staged_at: datetime,
        locked_until: datetime,
    ) -> None:
        staged_at_utc = staged_at.astimezone(timezone.utc)
        locked_until_utc = locked_until.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE telegram_ingress_updates
                    SET
                        status = 'pending_send',
                        response_text = %s,
                        conversation_id = %s,
                        locked_until = %s,
                        updated_at = %s
                    WHERE update_key = %s AND status IN ('processing', 'pending_send')
                    """,
                    (
                        response_text,
                        conversation_id,
                        locked_until_utc,
                        staged_at_utc,
                        update_key,
                    ),
                )
                if cur.rowcount != 1:
                    raise TelegramUpdateStorageError(
                        "telegram update missing while staging reply"
                    )

        self._execute(write)

    def mark_completed(
        self,
        *,
        update_key: str,
        completed_at: datetime,
    ) -> None:
        completed_at_utc = completed_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE telegram_ingress_updates
                    SET
                        status = 'completed',
                        locked_until = NULL,
                        updated_at = %s,
                        completed_at = %s
                    WHERE update_key = %s
                    """,
                    (
                        completed_at_utc,
                        completed_at_utc,
                        update_key,
                    ),
                )
                if cur.rowcount != 1:
                    raise TelegramUpdateStorageError(
                        "telegram update missing while marking completed"
                    )

        self._execute(write)

    def abandon_processing(
        self,
        *,
        update_key: str,
    ) -> None:
        def write(conn: psycopg.Connection) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM telegram_ingress_updates
                    WHERE update_key = %s AND status = 'processing'
                    """,
                    (update_key,),
                )

        self._execute(write)

    def release_retry(
        self,
        *,
        update_key: str,
        released_at: datetime,
    ) -> None:
        released_at_utc = released_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE telegram_ingress_updates
                    SET locked_until = %s, updated_at = %s
                    WHERE update_key = %s AND status IN ('processing', 'pending_send')
                    """,
                    (
                        released_at_utc,
                        released_at_utc,
                        update_key,
                    ),
                )

        self._execute(write)

    def _execute(self, operation):
        try:
            with psycopg.connect(self._database_url) as conn:
                with conn.transaction():
                    return operation(conn)
        except psycopg.Error as exc:
            raise TelegramUpdateStorageError(
                "telegram update storage unavailable"
            ) from exc
