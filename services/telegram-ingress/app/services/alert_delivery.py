from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

import psycopg

from app.clients.telegram import TelegramClient, TelegramSendError
from app.core.logging import log_event
from app.core.metrics import AlertDeliveryMetrics

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
    escalated_at: datetime | None = None
    escalation_reason: str | None = None
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

    def record_target_attempt(
        self,
        *,
        delivery_id: str,
        attempt: AlertTargetAttempt,
        completed_at: datetime,
        retry_backoff_seconds: float,
        max_attempts: int,
    ) -> None: ...

    def finalize_delivery(
        self,
        *,
        delivery_id: str,
        completed_at: datetime,
        retry_backoff_seconds: float,
        max_attempts: int,
    ) -> AlertDeliveryRecord: ...

    def mark_delivery_escalated(
        self,
        *,
        delivery_id: str,
        escalated_at: datetime,
        reason: str,
    ) -> AlertDeliveryRecord | None: ...


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

    def mark_delivery_escalated(
        self,
        *,
        delivery_id: str,
        escalated_at: datetime,
        reason: str,
    ) -> AlertDeliveryRecord | None:
        escalated_at_utc = escalated_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> AlertDeliveryRecord | None:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE telegram_alert_deliveries
                    SET
                        escalated_at = %s,
                        escalation_reason = %s,
                        updated_at = %s
                    WHERE id = %s AND escalated_at IS NULL
                    RETURNING id
                    """,
                    (
                        escalated_at_utc,
                        reason,
                        escalated_at_utc,
                        delivery_id,
                    ),
                )
                row = cursor.fetchone()
            if row is None:
                record = self._get_delivery(conn, delivery_id=delivery_id)
                if record is None:
                    raise AlertDeliveryStorageError(
                        "telegram alert delivery missing during escalation"
                    )
                return None

            escalated = self._get_delivery(conn, delivery_id=delivery_id)
            if escalated is None:
                raise AlertDeliveryStorageError(
                    "telegram alert delivery missing after escalation update"
                )
            return escalated

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
                            AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
                        )
                    ORDER BY next_attempt_at NULLS FIRST, created_at
                    LIMIT %s
                    """,
                    (now_utc, now_utc, now_utc, limit),
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
                        AND (
                            (
                                status = 'pending'
                                AND next_attempt_at IS NOT NULL
                                AND next_attempt_at <= %s
                            )
                            OR (
                                status = 'delivering'
                                AND locked_until IS NOT NULL
                                AND locked_until <= %s
                                AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
                            )
                        )
                    RETURNING id
                    """,
                    (
                        locked_until_utc,
                        now_utc,
                        delivery_id,
                        now_utc,
                        now_utc,
                        now_utc,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
            return self._get_delivery(conn, delivery_id=delivery_id)

        return self._execute(write)

    def record_target_attempt(
        self,
        *,
        delivery_id: str,
        attempt: AlertTargetAttempt,
        completed_at: datetime,
        retry_backoff_seconds: float,
        max_attempts: int,
    ) -> None:
        completed_at_utc = completed_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> None:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE telegram_alert_delivery_targets
                    SET
                        status = CASE
                            WHEN %s = 'pending' AND attempt_count + 1 >= %s THEN 'failed'
                            ELSE %s
                        END,
                        attempt_count = attempt_count + 1,
                        last_error_code = %s,
                        last_error_message = %s,
                        sent_at = CASE
                            WHEN %s = 'sent' THEN COALESCE(sent_at, %s)
                            ELSE sent_at
                        END,
                        updated_at = %s
                    WHERE delivery_id = %s AND chat_id = %s
                    RETURNING status
                    """,
                    (
                        attempt.status,
                        max_attempts,
                        attempt.status,
                        attempt.error_code,
                        attempt.error_message,
                        attempt.status,
                        completed_at_utc,
                        completed_at_utc,
                        delivery_id,
                        attempt.chat_id,
                    ),
                )
                row = cursor.fetchone()
            if row is None:
                raise AlertDeliveryStorageError(
                    "telegram alert delivery target missing during attempt update"
                )

            resulting_status = row[0]
            if resulting_status != "pending":
                return

            retry_delay_seconds = max(
                retry_backoff_seconds,
                attempt.retry_after_seconds or 0.0,
            )
            next_attempt_at = completed_at_utc + timedelta(seconds=retry_delay_seconds)
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE telegram_alert_deliveries
                    SET
                        next_attempt_at = GREATEST(
                            COALESCE(next_attempt_at, '-infinity'::timestamptz),
                            %s
                        ),
                        last_error_code = %s,
                        last_error_message = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        next_attempt_at,
                        attempt.error_code,
                        attempt.error_message,
                        completed_at_utc,
                        delivery_id,
                    ),
                )

        self._execute(write)

    def finalize_delivery(
        self,
        *,
        delivery_id: str,
        completed_at: datetime,
        retry_backoff_seconds: float,
        max_attempts: int,
    ) -> AlertDeliveryRecord:
        completed_at_utc = completed_at.astimezone(timezone.utc)

        def write(conn: psycopg.Connection) -> AlertDeliveryRecord:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE telegram_alert_delivery_targets
                    SET
                        status = 'failed',
                        updated_at = %s
                    WHERE
                        delivery_id = %s
                        AND status = 'pending'
                        AND attempt_count >= %s
                    """,
                    (completed_at_utc, delivery_id, max_attempts),
                )

            record = self._get_delivery(conn, delivery_id=delivery_id)
            if record is None:
                raise AlertDeliveryStorageError(
                    "telegram alert delivery missing during finalize"
                )

            pending_targets = [
                target for target in record.targets if target.status == "pending"
            ]
            failed_targets = [
                target for target in record.targets if target.status == "failed"
            ]
            sent_targets = [
                target for target in record.targets if target.status == "sent"
            ]

            if len(sent_targets) == len(record.targets):
                delivery_status = "completed"
                delivery_next_attempt_at = None
                last_error_code = None
                last_error_message = None
            elif pending_targets:
                delivery_status = "pending"
                delivery_next_attempt_at = record.next_attempt_at or (
                    completed_at_utc + timedelta(seconds=retry_backoff_seconds)
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

            with conn.cursor() as cursor:
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

            finalized = self._get_delivery(conn, delivery_id=delivery_id)
            if finalized is None:
                raise AlertDeliveryStorageError(
                    "telegram alert delivery missing after finalize"
                )
            return finalized

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
                    last_error_message,
                    escalated_at,
                    escalation_reason
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
            escalated_at=row[7],
            escalation_reason=row[8],
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
        metrics: AlertDeliveryMetrics | None = None,
        retry_backoff_seconds: float,
        max_attempts: int,
        claim_ttl_seconds: float,
    ) -> None:
        self._repository = repository
        self._telegram_client = telegram_client
        self._metrics = metrics or AlertDeliveryMetrics()
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
            log_event(
                "telegram_alert_delivery_claim_skipped",
                delivery_id=delivery_id,
                delivery_status=record.status,
                pending_targets=self._count_targets(record, "pending"),
            )
            self._metrics.record_claim_skipped()
            return record

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
                attempt = AlertTargetAttempt(
                    chat_id=target.chat_id,
                    status=self._classified_status(exc),
                    error_code=self._classified_error_code(exc),
                    error_message=str(exc),
                    retry_after_seconds=exc.retry_after_seconds,
                )
            except Exception as exc:
                attempt = AlertTargetAttempt(
                    chat_id=target.chat_id,
                    status="pending",
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                )
            else:
                attempt = AlertTargetAttempt(
                    chat_id=target.chat_id,
                    status="sent",
                )

            try:
                await asyncio.to_thread(
                    self._repository.record_target_attempt,
                    delivery_id=delivery_id,
                    attempt=attempt,
                    completed_at=datetime.now(timezone.utc),
                    retry_backoff_seconds=self._retry_backoff_seconds,
                    max_attempts=self._max_attempts,
                )
            except Exception as exc:
                log_event(
                    "telegram_alert_delivery_target_attempt_persist_failed",
                    delivery_id=delivery_id,
                    chat_id=attempt.chat_id,
                    attempt_status=attempt.status,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                )
                self._metrics.record_target_attempt_persist_failed()
                raise AlertDeliveryStorageError(
                    "telegram alert delivery target update failed"
                ) from exc
            log_event(
                "telegram_alert_delivery_target_attempt_recorded",
                delivery_id=delivery_id,
                chat_id=attempt.chat_id,
                attempt_status=attempt.status,
                error_code=attempt.error_code,
                error_message=attempt.error_message,
                retry_after_seconds=attempt.retry_after_seconds,
            )
            self._metrics.record_target_attempt(
                status=attempt.status,
                error_code=attempt.error_code,
            )

        try:
            finalized = await asyncio.to_thread(
                self._repository.finalize_delivery,
                delivery_id=delivery_id,
                completed_at=datetime.now(timezone.utc),
                retry_backoff_seconds=self._retry_backoff_seconds,
                max_attempts=self._max_attempts,
            )
            log_event(
                "telegram_alert_delivery_finalized",
                delivery_id=delivery_id,
                delivery_status=finalized.status,
                attempt_count=finalized.attempt_count,
                sent_targets=self._count_targets(finalized, "sent"),
                pending_targets=self._count_targets(finalized, "pending"),
                failed_targets=self._count_targets(finalized, "failed"),
                next_attempt_at=finalized.next_attempt_at,
                last_error_code=finalized.last_error_code,
            )
            self._metrics.record_finalize(status=finalized.status)
            escalated = await self._maybe_escalate_delivery(finalized)
            if escalated is not None:
                finalized = escalated
            return finalized
        except Exception as exc:
            log_event(
                "telegram_alert_delivery_finalize_failed",
                delivery_id=delivery_id,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
            self._metrics.record_finalize_failed()
            raise AlertDeliveryStorageError(
                "telegram alert delivery finalize failed"
            ) from exc

    async def _maybe_escalate_delivery(
        self,
        record: AlertDeliveryRecord,
    ) -> AlertDeliveryRecord | None:
        reason = self._escalation_reason(record)
        if reason is None:
            return None

        try:
            escalated = await asyncio.to_thread(
                self._repository.mark_delivery_escalated,
                delivery_id=record.delivery_id,
                escalated_at=datetime.now(timezone.utc),
                reason=reason,
            )
        except Exception as exc:
            raise AlertDeliveryStorageError(
                "telegram alert delivery escalation update failed"
            ) from exc

        if escalated is None:
            return None

        log_event(
            "telegram_alert_delivery_escalated",
            delivery_id=escalated.delivery_id,
            escalation_reason=reason,
            delivery_status=escalated.status,
            attempt_count=escalated.attempt_count,
            failed_targets=self._count_targets(escalated, "failed"),
            last_error_code=escalated.last_error_code,
            escalated_at=escalated.escalated_at,
        )
        self._metrics.record_escalation(reason=reason)
        return escalated

    async def _claim_delivery(
        self,
        delivery_id: str,
    ) -> AlertDeliveryRecord | None:
        prior_record = await self._get_delivery(delivery_id)
        now = datetime.now(timezone.utc)
        try:
            claimed = await asyncio.to_thread(
                self._repository.claim_delivery,
                delivery_id=delivery_id,
                now=now,
                locked_until=now + timedelta(seconds=self._claim_ttl_seconds),
            )
            if claimed is not None:
                claim_origin = (
                    "stale_reclaim"
                    if prior_record is not None and prior_record.status == "delivering"
                    else "pending"
                )
                log_event(
                    "telegram_alert_delivery_claimed",
                    delivery_id=delivery_id,
                    claim_origin=claim_origin,
                    pending_targets=self._count_targets(claimed, "pending"),
                    attempt_count=claimed.attempt_count,
                    next_attempt_at=claimed.next_attempt_at,
                )
                self._metrics.record_claim(origin=claim_origin)
            return claimed
        except Exception as exc:
            log_event(
                "telegram_alert_delivery_claim_failed",
                delivery_id=delivery_id,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
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

    def _count_targets(
        self,
        record: AlertDeliveryRecord,
        status: str,
    ) -> int:
        return sum(1 for target in record.targets if target.status == status)

    def _escalation_reason(self, record: AlertDeliveryRecord) -> str | None:
        if record.status != "failed" or record.escalated_at is not None:
            return None

        failed_targets = [target for target in record.targets if target.status == "failed"]
        if not failed_targets:
            return None
        if any(self._is_terminal_error_code(target.last_error_code) for target in failed_targets):
            return "terminal_target_failure"
        if any(target.attempt_count >= self._max_attempts for target in failed_targets):
            return "retry_exhausted"
        return "delivery_failed"

    def _is_terminal_error_code(self, error_code: str | None) -> bool:
        if error_code is None or not error_code.startswith("http_"):
            return False
        try:
            status_code = int(error_code.removeprefix("http_"))
        except ValueError:
            return False
        return status_code in _TERMINAL_STATUS_CODES
