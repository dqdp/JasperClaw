from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

import psycopg

from app.clients.telegram import TelegramClient, TelegramSendError

_TERMINAL_STATUS_CODES = frozenset({400, 401, 403, 404})


@dataclass(frozen=True, slots=True)
class AlertDeliveryRequest:
    deliveries: tuple[tuple[int, str], ...]
    matched_alerts: int
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class AlertDeliveryTargetRecord:
    chat_id: int
    message_text: str
    status: str
    attempt_count: int
    last_error_code: str | None = None
    last_error_message: str | None = None


@dataclass(frozen=True, slots=True)
class AlertDeliveryRecord:
    delivery_id: str
    status: str
    matched_alerts: int
    attempt_count: int
    targets: tuple[AlertDeliveryTargetRecord, ...]
    next_attempt_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    deduplicated: bool = False


@dataclass(frozen=True, slots=True)
class AlertTargetAttempt:
    chat_id: int
    status: str
    error_code: str | None = None
    error_message: str | None = None
    retry_after_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class AlertSubmissionResult:
    delivery_id: str
    status: str
    recipients: int
    matched_alerts: int
    deduplicated: bool


class AlertDeliveryStorageError(RuntimeError):
    """Raised when durable alert-delivery state cannot be persisted or loaded."""


class AlertDeliveryHandler(Protocol):
    async def submit_delivery(
        self,
        *,
        request: AlertDeliveryRequest,
        request_id: str,
    ) -> AlertSubmissionResult: ...

    async def process_due_deliveries(
        self,
        *,
        limit: int = 10,
    ) -> int: ...

    async def close(self) -> None: ...


class AlertDeliveryRepository(Protocol):
    def enqueue_delivery(
        self,
        *,
        request: AlertDeliveryRequest,
        idempotency_key: str | None,
        created_at: datetime,
    ) -> AlertDeliveryRecord: ...

    def get_delivery(
        self,
        *,
        delivery_id: str,
    ) -> AlertDeliveryRecord | None: ...

    def list_due_delivery_ids(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[str, ...]: ...

    def claim_delivery(
        self,
        *,
        delivery_id: str,
        now: datetime,
        locked_until: datetime,
    ) -> AlertDeliveryRecord | None: ...

    def apply_attempt_results(
        self,
        *,
        delivery_id: str,
        attempts: tuple[AlertTargetAttempt, ...],
        completed_at: datetime,
        retry_backoff_seconds: float,
        max_attempts: int,
    ) -> AlertDeliveryRecord: ...


class PostgresAlertDeliveryRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def enqueue_delivery(
        self,
        *,
        request: AlertDeliveryRequest,
        idempotency_key: str | None,
        created_at: datetime,
    ) -> AlertDeliveryRecord:
        created_at_utc = created_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> AlertDeliveryRecord:
            delivery_id = self._new_id("alert")
            with conn.cursor() as cursor:
                if idempotency_key is not None:
                    cursor.execute(
                        """
                        INSERT INTO telegram_alert_deliveries (
                            id,
                            idempotency_key,
                            status,
                            matched_alerts,
                            attempt_count,
                            next_attempt_at,
                            locked_until,
                            last_error_code,
                            last_error_message,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, 'pending', %s, 0, %s, NULL, NULL, NULL, %s, %s)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING id
                        """,
                        (
                            delivery_id,
                            idempotency_key,
                            request.matched_alerts,
                            created_at_utc,
                            created_at_utc,
                            created_at_utc,
                        ),
                    )
                    inserted_row = cursor.fetchone()
                    if inserted_row is None:
                        existing_delivery_id = self._select_delivery_id_by_idempotency_key(
                            conn,
                            idempotency_key=idempotency_key,
                        )
                        if existing_delivery_id is None:
                            raise AlertDeliveryStorageError(
                                "telegram alert delivery missing after idempotency conflict"
                            )
                        record = self._get_delivery(conn, delivery_id=existing_delivery_id)
                        if record is None:
                            raise AlertDeliveryStorageError(
                                "telegram alert delivery missing after idempotency lookup"
                            )
                        return replace(record, deduplicated=True)
                else:
                    cursor.execute(
                        """
                        INSERT INTO telegram_alert_deliveries (
                            id,
                            idempotency_key,
                            status,
                            matched_alerts,
                            attempt_count,
                            next_attempt_at,
                            locked_until,
                            last_error_code,
                            last_error_message,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, 'pending', %s, 0, %s, NULL, NULL, NULL, %s, %s)
                        """,
                        (
                            delivery_id,
                            idempotency_key,
                            request.matched_alerts,
                            created_at_utc,
                            created_at_utc,
                            created_at_utc,
                        ),
                    )
                for chat_id, message_text in request.deliveries:
                    cursor.execute(
                        """
                        INSERT INTO telegram_alert_delivery_targets (
                            delivery_id,
                            chat_id,
                            message_text,
                            status,
                            attempt_count,
                            last_error_code,
                            last_error_message,
                            sent_at,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, %s, 'pending', 0, NULL, NULL, NULL, %s, %s)
                        """,
                        (
                            delivery_id,
                            chat_id,
                            message_text,
                            created_at_utc,
                            created_at_utc,
                        ),
                    )
            record = self._get_delivery(conn, delivery_id=delivery_id)
            if record is None:
                raise AlertDeliveryStorageError(
                    "telegram alert delivery missing after insert"
                )
            return record

        return self._execute(write)

    def get_delivery(
        self,
        *,
        delivery_id: str,
    ) -> AlertDeliveryRecord | None:
        def read(conn: psycopg.Connection) -> AlertDeliveryRecord | None:
            return self._get_delivery(conn, delivery_id=delivery_id)

        return self._execute(read)

    def list_due_delivery_ids(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[str, ...]:
        now_utc = now.astimezone(timezone.utc)

        def read(conn: psycopg.Connection) -> tuple[str, ...]:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM telegram_alert_deliveries
                    WHERE
                        (
                            status = 'pending'
                            AND next_attempt_at IS NOT NULL
                            AND next_attempt_at <= %s
                        )
                        OR (
                            status = 'delivering'
                            AND locked_until IS NOT NULL
                            AND locked_until <= %s
                        )
                    ORDER BY next_attempt_at NULLS FIRST, created_at
                    LIMIT %s
                    """,
                    (now_utc, now_utc, limit),
                )
                return tuple(row[0] for row in cursor.fetchall())

        return self._execute(read)

    def claim_delivery(
        self,
        *,
        delivery_id: str,
        now: datetime,
        locked_until: datetime,
    ) -> AlertDeliveryRecord | None:
        now_utc = now.astimezone(timezone.utc)
        locked_until_utc = locked_until.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> AlertDeliveryRecord | None:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE telegram_alert_deliveries
                    SET
                        status = 'delivering',
                        locked_until = %s,
                        updated_at = %s
                    WHERE
                        id = %s
                        AND status IN ('pending', 'delivering')
                        AND (locked_until IS NULL OR locked_until <= %s)
                    RETURNING id
                    """,
                    (locked_until_utc, now_utc, delivery_id, now_utc),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
            return self._get_delivery(conn, delivery_id=delivery_id)

        return self._execute(write)

    def apply_attempt_results(
        self,
        *,
        delivery_id: str,
        attempts: tuple[AlertTargetAttempt, ...],
        completed_at: datetime,
        retry_backoff_seconds: float,
        max_attempts: int,
    ) -> AlertDeliveryRecord:
        completed_at_utc = completed_at.astimezone(timezone.utc)
        attempt_map = {attempt.chat_id: attempt for attempt in attempts}

        def write(conn: psycopg.Connection) -> AlertDeliveryRecord:
            with conn.cursor() as cursor:
                for attempt in attempts:
                    sent_at = completed_at_utc if attempt.status == "sent" else None
                    cursor.execute(
                        """
                        UPDATE telegram_alert_delivery_targets
                        SET
                            status = %s,
                            attempt_count = attempt_count + 1,
                            last_error_code = %s,
                            last_error_message = %s,
                            sent_at = COALESCE(%s, sent_at),
                            updated_at = %s
                        WHERE delivery_id = %s AND chat_id = %s
                        """,
                        (
                            attempt.status,
                            attempt.error_code,
                            attempt.error_message,
                            sent_at,
                            completed_at_utc,
                            delivery_id,
                            attempt.chat_id,
                        ),
                    )

                targets = self._get_targets(conn, delivery_id=delivery_id)
                pending_targets = [
                    target for target in targets
                    if target.status == "pending" and target.attempt_count < max_attempts
                ]
                exhausted_targets = [
                    target for target in targets
                    if target.status == "pending" and target.attempt_count >= max_attempts
                ]
                if exhausted_targets:
                    for target in exhausted_targets:
                        cursor.execute(
                            """
                            UPDATE telegram_alert_delivery_targets
                            SET
                                status = 'failed',
                                updated_at = %s
                            WHERE delivery_id = %s AND chat_id = %s
                            """,
                            (completed_at_utc, delivery_id, target.chat_id),
                        )
                    targets = self._get_targets(conn, delivery_id=delivery_id)
                    pending_targets = [
                        target for target in targets if target.status == "pending"
                    ]

                failed_targets = [
                    target for target in targets if target.status == "failed"
                ]
                sent_targets = [
                    target for target in targets if target.status == "sent"
                ]

                if len(sent_targets) == len(targets):
                    delivery_status = "completed"
                    delivery_next_attempt_at = None
                    last_error_code = None
                    last_error_message = None
                elif pending_targets:
                    next_retry_delay_seconds = retry_backoff_seconds
                    for target in pending_targets:
                        attempt = attempt_map.get(target.chat_id)
                        if (
                            attempt is not None
                            and attempt.retry_after_seconds is not None
                        ):
                            next_retry_delay_seconds = max(
                                next_retry_delay_seconds,
                                attempt.retry_after_seconds,
                            )
                    delivery_status = "pending"
                    delivery_next_attempt_at = completed_at_utc + timedelta(
                        seconds=next_retry_delay_seconds
                    )
                    pending_target = pending_targets[0]
                    last_error_code = pending_target.last_error_code
                    last_error_message = pending_target.last_error_message
                else:
                    delivery_status = "failed"
                    delivery_next_attempt_at = None
                    failed_target = failed_targets[0] if failed_targets else None
                    last_error_code = (
                        failed_target.last_error_code if failed_target is not None else None
                    )
                    last_error_message = (
                        failed_target.last_error_message
                        if failed_target is not None
                        else None
                    )

                cursor.execute(
                    """
                    UPDATE telegram_alert_deliveries
                    SET
                        status = %s,
                        attempt_count = attempt_count + 1,
                        next_attempt_at = %s,
                        locked_until = NULL,
                        last_error_code = %s,
                        last_error_message = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        delivery_status,
                        delivery_next_attempt_at,
                        last_error_code,
                        last_error_message,
                        completed_at_utc,
                        delivery_id,
                    ),
                )

            record = self._get_delivery(conn, delivery_id=delivery_id)
            if record is None:
                raise AlertDeliveryStorageError(
                    "telegram alert delivery missing after attempt update"
                )
            return record

        return self._execute(write)

    def _execute(self, callback):
        with psycopg.connect(self._database_url) as conn:
            with conn.transaction():
                return callback(conn)

    def _select_delivery_id_by_idempotency_key(
        self,
        conn: psycopg.Connection,
        *,
        idempotency_key: str,
    ) -> str | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM telegram_alert_deliveries
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            row = cursor.fetchone()
            return row[0] if row is not None else None

    def _get_delivery(
        self,
        conn: psycopg.Connection,
        *,
        delivery_id: str,
    ) -> AlertDeliveryRecord | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    status,
                    matched_alerts,
                    attempt_count,
                    next_attempt_at,
                    last_error_code,
                    last_error_message
                FROM telegram_alert_deliveries
                WHERE id = %s
                """,
                (delivery_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None

        targets = self._get_targets(conn, delivery_id=delivery_id)
        return AlertDeliveryRecord(
            delivery_id=row[0],
            status=row[1],
            matched_alerts=row[2],
            attempt_count=row[3],
            next_attempt_at=row[4],
            last_error_code=row[5],
            last_error_message=row[6],
            targets=targets,
        )

    def _get_targets(
        self,
        conn: psycopg.Connection,
        *,
        delivery_id: str,
    ) -> tuple[AlertDeliveryTargetRecord, ...]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    chat_id,
                    message_text,
                    status,
                    attempt_count,
                    last_error_code,
                    last_error_message
                FROM telegram_alert_delivery_targets
                WHERE delivery_id = %s
                ORDER BY chat_id
                """,
                (delivery_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            AlertDeliveryTargetRecord(
                chat_id=row[0],
                message_text=row[1],
                status=row[2],
                attempt_count=row[3],
                last_error_code=row[4],
                last_error_message=row[5],
            )
            for row in rows
        )

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"


class AlertDeliveryService:
    # This path is operational and low-frequency, so sync repository access is
    # pushed into worker threads rather than introducing a second async DB stack.
    def __init__(
        self,
        *,
        repository: AlertDeliveryRepository,
        telegram_client: TelegramClient,
        retry_backoff_seconds: float,
        max_attempts: int,
        claim_ttl_seconds: float,
    ) -> None:
        self._repository = repository
        self._telegram_client = telegram_client
        self._retry_backoff_seconds = retry_backoff_seconds
        self._max_attempts = max_attempts
        self._claim_ttl_seconds = claim_ttl_seconds

    async def submit_delivery(
        self,
        *,
        request: AlertDeliveryRequest,
        request_id: str,
    ) -> AlertSubmissionResult:
        _ = request_id
        created_at = datetime.now(timezone.utc)
        try:
            record = await asyncio.to_thread(
                self._repository.enqueue_delivery,
                request=request,
                idempotency_key=self._build_idempotency_key(request),
                created_at=created_at,
            )
        except Exception as exc:
            raise AlertDeliveryStorageError("telegram alert delivery enqueue failed") from exc

        final_record = record
        if not record.deduplicated and record.status in {"pending", "delivering"}:
            final_record = await self._process_delivery(record.delivery_id)
        return self._to_submission_result(final_record)

    async def process_due_deliveries(
        self,
        *,
        limit: int = 10,
    ) -> int:
        now = datetime.now(timezone.utc)
        try:
            due_delivery_ids = await asyncio.to_thread(
                self._repository.list_due_delivery_ids,
                now=now,
                limit=limit,
            )
        except Exception as exc:
            raise AlertDeliveryStorageError("telegram alert due-delivery query failed") from exc

        processed = 0
        for delivery_id in due_delivery_ids:
            await self._process_delivery(delivery_id)
            processed += 1
        return processed

    async def close(self) -> None:
        return None

    async def _process_delivery(self, delivery_id: str) -> AlertDeliveryRecord:
        claimed = await self._claim_delivery(delivery_id)
        if claimed is None:
            record = await self._get_delivery(delivery_id)
            if record is None:
                raise AlertDeliveryStorageError("telegram alert delivery disappeared")
            return record

        attempts: list[AlertTargetAttempt] = []
        pending_targets = [
            target for target in claimed.targets if target.status == "pending"
        ]
        for target in pending_targets:
            try:
                await self._telegram_client.send_message(
                    chat_id=target.chat_id,
                    text=target.message_text,
                )
            except TelegramSendError as exc:
                attempts.append(
                    AlertTargetAttempt(
                        chat_id=target.chat_id,
                        status=self._classified_status(exc),
                        error_code=self._classified_error_code(exc),
                        error_message=str(exc),
                        retry_after_seconds=exc.retry_after_seconds,
                    )
                )
            except Exception as exc:
                attempts.append(
                    AlertTargetAttempt(
                        chat_id=target.chat_id,
                        status="pending",
                        error_code=type(exc).__name__,
                        error_message=str(exc),
                    )
                )
            else:
                attempts.append(
                    AlertTargetAttempt(
                        chat_id=target.chat_id,
                        status="sent",
                    )
                )

        try:
            return await asyncio.to_thread(
                self._repository.apply_attempt_results,
                delivery_id=delivery_id,
                attempts=tuple(attempts),
                completed_at=datetime.now(timezone.utc),
                retry_backoff_seconds=self._retry_backoff_seconds,
                max_attempts=self._max_attempts,
            )
        except Exception as exc:
            raise AlertDeliveryStorageError(
                "telegram alert delivery attempt update failed"
            ) from exc

    async def _claim_delivery(
        self,
        delivery_id: str,
    ) -> AlertDeliveryRecord | None:
        now = datetime.now(timezone.utc)
        try:
            return await asyncio.to_thread(
                self._repository.claim_delivery,
                delivery_id=delivery_id,
                now=now,
                locked_until=now + timedelta(seconds=self._claim_ttl_seconds),
            )
        except Exception as exc:
            raise AlertDeliveryStorageError("telegram alert delivery claim failed") from exc

    async def _get_delivery(
        self,
        delivery_id: str,
    ) -> AlertDeliveryRecord | None:
        try:
            return await asyncio.to_thread(
                self._repository.get_delivery,
                delivery_id=delivery_id,
            )
        except Exception as exc:
            raise AlertDeliveryStorageError("telegram alert delivery fetch failed") from exc

    def _build_idempotency_key(
        self,
        request: AlertDeliveryRequest,
    ) -> str | None:
        if request.idempotency_key is None:
            return None
        raw_key = request.idempotency_key.strip()
        if not raw_key:
            return None
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return f"telegram_alert:{digest}"

    def _classified_status(self, error: TelegramSendError) -> str:
        status_code = error.status_code
        if status_code in _TERMINAL_STATUS_CODES:
            return "failed"
        return "pending"

    def _classified_error_code(self, error: TelegramSendError) -> str:
        if error.status_code is not None:
            return f"http_{error.status_code}"
        return "telegram_send_error"

    def _to_submission_result(
        self,
        record: AlertDeliveryRecord,
    ) -> AlertSubmissionResult:
        if record.status == "completed":
            status = "sent"
        elif record.status in {"pending", "delivering"}:
            status = "accepted"
        else:
            status = "failed"
        return AlertSubmissionResult(
            delivery_id=record.delivery_id,
            status=status,
            recipients=len(record.targets),
            matched_alerts=record.matched_alerts,
            deduplicated=record.deduplicated,
        )
