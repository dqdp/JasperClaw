from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.clients.telegram import TelegramSendError
from app.core.metrics import AlertDeliveryMetrics
from app.services.alert_delivery import (
    AlertDeliveryRecord,
    AlertDeliveryRequest,
    AlertDeliveryStorageError,
    AlertDeliveryService,
    AlertDeliveryTargetRecord,
    AlertTargetAttempt,
)


@dataclass
class _StoredDelivery:
    record: AlertDeliveryRecord
    idempotency_key: str | None
    locked_until: datetime | None = None


class _InMemoryAlertDeliveryRepository:
    def __init__(
        self,
        *,
        fail_finalize_delivery_once: bool = False,
    ) -> None:
        self._records: dict[str, _StoredDelivery] = {}
        self._idempotency_index: dict[str, str] = {}
        self._sequence = 0
        self._fail_finalize_delivery_once = fail_finalize_delivery_once

    def enqueue_delivery(
        self,
        *,
        request: AlertDeliveryRequest,
        idempotency_key: str | None,
        created_at: datetime,
    ) -> AlertDeliveryRecord:
        if idempotency_key is not None and idempotency_key in self._idempotency_index:
            delivery_id = self._idempotency_index[idempotency_key]
            return replace(self._records[delivery_id].record, deduplicated=True)

        self._sequence += 1
        delivery_id = f"alert_{self._sequence}"
        record = AlertDeliveryRecord(
            delivery_id=delivery_id,
            status="pending",
            matched_alerts=request.matched_alerts,
            attempt_count=0,
            next_attempt_at=created_at,
            last_error_code=None,
            last_error_message=None,
            targets=tuple(
                AlertDeliveryTargetRecord(
                    chat_id=chat_id,
                    message_text=message_text,
                    status="pending",
                    attempt_count=0,
                )
                for chat_id, message_text in request.deliveries
            ),
        )
        self._records[delivery_id] = _StoredDelivery(
            record=record,
            idempotency_key=idempotency_key,
        )
        if idempotency_key is not None:
            self._idempotency_index[idempotency_key] = delivery_id
        return record

    def get_delivery(
        self,
        *,
        delivery_id: str,
    ) -> AlertDeliveryRecord | None:
        stored = self._records.get(delivery_id)
        if stored is None:
            return None
        return stored.record

    def list_due_delivery_ids(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[str, ...]:
        due: list[str] = []
        for delivery_id, stored in self._records.items():
            record = stored.record
            if record.status == "pending" and record.next_attempt_at is not None and record.next_attempt_at <= now:
                due.append(delivery_id)
                continue
            if (
                record.status == "delivering"
                and stored.locked_until is not None
                and stored.locked_until <= now
                and (record.next_attempt_at is None or record.next_attempt_at <= now)
            ):
                due.append(delivery_id)
        return tuple(sorted(due)[:limit])

    def claim_delivery(
        self,
        *,
        delivery_id: str,
        now: datetime,
        locked_until: datetime,
    ) -> AlertDeliveryRecord | None:
        stored = self._records.get(delivery_id)
        if stored is None:
            return None
        if stored.record.status == "pending":
            if (
                stored.record.next_attempt_at is None
                or stored.record.next_attempt_at > now
            ):
                return None
        elif stored.record.status == "delivering":
            if (
                stored.locked_until is None
                or stored.locked_until > now
                or (
                    stored.record.next_attempt_at is not None
                    and stored.record.next_attempt_at > now
                )
            ):
                return None
        else:
            return None
        stored.locked_until = locked_until
        stored.record = replace(
            stored.record,
            status="delivering",
        )
        return stored.record

    def record_target_attempt(
        self,
        *,
        delivery_id: str,
        attempt: AlertTargetAttempt,
        completed_at: datetime,
        retry_backoff_seconds: float,
        max_attempts: int,
    ) -> None:
        stored = self._records[delivery_id]
        next_attempt_at = stored.record.next_attempt_at
        updated_targets: list[AlertDeliveryTargetRecord] = []
        for target in stored.record.targets:
            if target.chat_id != attempt.chat_id:
                updated_targets.append(target)
                continue
            updated_target = replace(
                target,
                status=attempt.status,
                attempt_count=target.attempt_count + 1,
                last_error_code=attempt.error_code,
                last_error_message=attempt.error_message,
            )
            if updated_target.status == "pending" and updated_target.attempt_count >= max_attempts:
                updated_target = replace(updated_target, status="failed")
            elif updated_target.status == "pending":
                retry_delay_seconds = max(
                    retry_backoff_seconds,
                    attempt.retry_after_seconds or 0.0,
                )
                candidate_next_attempt_at = completed_at + timedelta(
                    seconds=retry_delay_seconds
                )
                if next_attempt_at is None or candidate_next_attempt_at > next_attempt_at:
                    next_attempt_at = candidate_next_attempt_at
            updated_targets.append(updated_target)
        stored.record = replace(
            stored.record,
            next_attempt_at=next_attempt_at,
            targets=tuple(updated_targets),
        )

    def finalize_delivery(
        self,
        *,
        delivery_id: str,
        completed_at: datetime,
        retry_backoff_seconds: float,
        max_attempts: int,
    ) -> AlertDeliveryRecord:
        if self._fail_finalize_delivery_once:
            self._fail_finalize_delivery_once = False
            raise RuntimeError("simulated finalize failure")
        stored = self._records[delivery_id]
        updated_targets: list[AlertDeliveryTargetRecord] = []
        for target in stored.record.targets:
            updated_target = target
            if updated_target.status == "pending" and updated_target.attempt_count >= max_attempts:
                updated_target = replace(updated_target, status="failed")
            updated_targets.append(updated_target)

        if all(target.status == "sent" for target in updated_targets):
            status = "completed"
            next_attempt_at = None
            last_error_code = None
            last_error_message = None
        else:
            pending_targets = [
                target for target in updated_targets if target.status == "pending"
            ]
            if pending_targets:
                status = "pending"
                next_attempt_at = stored.record.next_attempt_at or (
                    completed_at + timedelta(seconds=retry_backoff_seconds)
                )
                last_error_code = pending_targets[0].last_error_code
                last_error_message = pending_targets[0].last_error_message
            else:
                status = "failed"
                next_attempt_at = None
                failed_target = next(
                    target for target in updated_targets if target.status == "failed"
                )
                last_error_code = failed_target.last_error_code
                last_error_message = failed_target.last_error_message

        stored.locked_until = None
        stored.record = replace(
            stored.record,
            status=status,
            attempt_count=stored.record.attempt_count + 1,
            next_attempt_at=next_attempt_at,
            last_error_code=last_error_code,
            last_error_message=last_error_message,
            targets=tuple(updated_targets),
        )
        return stored.record

    def force_due(self, delivery_id: str) -> None:
        stored = self._records[delivery_id]
        stored.record = replace(
            stored.record,
            next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

    def expire_claim(self, delivery_id: str) -> None:
        stored = self._records[delivery_id]
        stored.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)


class _SequencedTelegramClient:
    def __init__(
        self,
        *,
        failures: dict[int, list[Exception]] | None = None,
    ) -> None:
        self.sent_messages: list[tuple[int, str]] = []
        self._failures = {
            chat_id: list(chat_failures)
            for chat_id, chat_failures in (failures or {}).items()
        }

    async def send_message(self, *, chat_id: int, text: str) -> None:
        failures = self._failures.get(chat_id)
        if failures:
            raise failures.pop(0)
        self.sent_messages.append((chat_id, text))


def _service(
    *,
    repository: _InMemoryAlertDeliveryRepository,
    telegram_client: _SequencedTelegramClient,
    metrics: AlertDeliveryMetrics | None = None,
    retry_backoff_seconds: float = 0.0,
    max_attempts: int = 3,
    claim_ttl_seconds: float = 30.0,
) -> AlertDeliveryService:
    return AlertDeliveryService(
        repository=repository,
        telegram_client=telegram_client,
        metrics=metrics or AlertDeliveryMetrics(),
        retry_backoff_seconds=retry_backoff_seconds,
        max_attempts=max_attempts,
        claim_ttl_seconds=claim_ttl_seconds,
    )


def _events(caplog) -> list[dict]:
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "telegram_ingress"
    ]


def test_submit_delivery_deduplicates_same_request_with_explicit_idempotency_key() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient()
    service = _service(repository=repository, telegram_client=telegram_client)
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"), (22, "critical alert")),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    first = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))
    second = asyncio.run(service.submit_delivery(request=request, request_id="req_2"))

    assert first.status == "sent"
    assert second.status == "sent"
    assert second.deduplicated is True
    assert second.delivery_id == first.delivery_id
    assert telegram_client.sent_messages == [
        (11, "critical alert"),
        (22, "critical alert"),
    ]


def test_submit_delivery_does_not_deduplicate_without_explicit_idempotency_key() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient()
    service = _service(repository=repository, telegram_client=telegram_client)
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key=None,
    )

    first = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))
    second = asyncio.run(service.submit_delivery(request=request, request_id="req_2"))

    assert first.delivery_id != second.delivery_id
    assert second.deduplicated is False
    assert telegram_client.sent_messages == [
        (11, "critical alert"),
        (11, "critical alert"),
    ]


def test_submit_delivery_retries_rate_limited_targets_in_background() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient(
        failures={11: [TelegramSendError("rate limited", status_code=429)]}
    )
    service = _service(repository=repository, telegram_client=telegram_client)
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    submission = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))
    repository.force_due(submission.delivery_id)
    processed = asyncio.run(service.process_due_deliveries())
    record = repository.get_delivery(delivery_id=submission.delivery_id)

    assert submission.status == "accepted"
    assert processed == 1
    assert record is not None
    assert record.status == "completed"
    assert record.attempt_count == 2
    assert telegram_client.sent_messages == [(11, "critical alert")]


def test_submit_delivery_uses_retry_after_when_rate_limit_exceeds_default_backoff() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient(
        failures={
            11: [
                TelegramSendError(
                    "rate limited",
                    status_code=429,
                    retry_after_seconds=10.0,
                )
            ]
        }
    )
    service = _service(
        repository=repository,
        telegram_client=telegram_client,
        retry_backoff_seconds=1.0,
    )
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    submission = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))
    record = repository.get_delivery(delivery_id=submission.delivery_id)

    assert submission.status == "accepted"
    assert record is not None
    assert record.status == "pending"
    assert record.next_attempt_at is not None
    remaining_seconds = (record.next_attempt_at - datetime.now(timezone.utc)).total_seconds()
    assert remaining_seconds >= 8.0


def test_submit_delivery_keeps_default_backoff_when_retry_after_is_shorter() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient(
        failures={
            11: [
                TelegramSendError(
                    "rate limited",
                    status_code=429,
                    retry_after_seconds=1.0,
                )
            ]
        }
    )
    service = _service(
        repository=repository,
        telegram_client=telegram_client,
        retry_backoff_seconds=5.0,
    )
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    submission = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))
    record = repository.get_delivery(delivery_id=submission.delivery_id)

    assert submission.status == "accepted"
    assert record is not None
    assert record.status == "pending"
    assert record.next_attempt_at is not None
    remaining_seconds = (record.next_attempt_at - datetime.now(timezone.utc)).total_seconds()
    assert remaining_seconds >= 4.0


def test_submit_delivery_emits_claim_attempt_and_finalize_events(caplog) -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient()
    service = _service(repository=repository, telegram_client=telegram_client)
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    with caplog.at_level(logging.INFO, logger="telegram_ingress"):
        submission = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))

    assert submission.status == "sent"
    events = _events(caplog)
    names = [event["event"] for event in events]
    assert "telegram_alert_delivery_claimed" in names
    assert "telegram_alert_delivery_target_attempt_recorded" in names
    assert "telegram_alert_delivery_finalized" in names

    claim_event = next(
        event for event in events if event["event"] == "telegram_alert_delivery_claimed"
    )
    assert claim_event["claim_origin"] == "pending"
    assert claim_event["delivery_id"] == submission.delivery_id
    assert claim_event["pending_targets"] == 1

    target_event = next(
        event
        for event in events
        if event["event"] == "telegram_alert_delivery_target_attempt_recorded"
    )
    assert target_event["delivery_id"] == submission.delivery_id
    assert target_event["chat_id"] == 11
    assert target_event["attempt_status"] == "sent"
    assert target_event["error_code"] is None

    finalize_event = next(
        event for event in events if event["event"] == "telegram_alert_delivery_finalized"
    )
    assert finalize_event["delivery_id"] == submission.delivery_id
    assert finalize_event["delivery_status"] == "completed"
    assert finalize_event["sent_targets"] == 1
    assert finalize_event["pending_targets"] == 0
    assert finalize_event["failed_targets"] == 0


def test_submit_delivery_emits_retryable_attempt_event_with_retry_after(caplog) -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient(
        failures={
            11: [
                TelegramSendError(
                    "rate limited",
                    status_code=429,
                    retry_after_seconds=10.0,
                )
            ]
        }
    )
    service = _service(
        repository=repository,
        telegram_client=telegram_client,
        retry_backoff_seconds=1.0,
    )
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    with caplog.at_level(logging.INFO, logger="telegram_ingress"):
        submission = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))

    assert submission.status == "accepted"
    events = _events(caplog)

    target_event = next(
        event
        for event in events
        if event["event"] == "telegram_alert_delivery_target_attempt_recorded"
    )
    assert target_event["attempt_status"] == "pending"
    assert target_event["error_code"] == "http_429"
    assert target_event["retry_after_seconds"] == 10.0

    finalize_event = next(
        event for event in events if event["event"] == "telegram_alert_delivery_finalized"
    )
    assert finalize_event["delivery_status"] == "pending"
    assert finalize_event["pending_targets"] == 1


def test_finalize_failure_emits_finalize_failed_event(caplog) -> None:
    repository = _InMemoryAlertDeliveryRepository(
        fail_finalize_delivery_once=True,
    )
    telegram_client = _SequencedTelegramClient()
    service = _service(repository=repository, telegram_client=telegram_client)
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    with caplog.at_level(logging.INFO, logger="telegram_ingress"):
        with pytest.raises(AlertDeliveryStorageError):
            asyncio.run(service.submit_delivery(request=request, request_id="req_1"))

    events = _events(caplog)
    failure_event = next(
        event for event in events if event["event"] == "telegram_alert_delivery_finalize_failed"
    )
    assert failure_event["delivery_id"] == "alert_1"
    assert failure_event["error_code"] == "RuntimeError"
    assert failure_event["error_message"] == "simulated finalize failure"


def test_process_due_delivery_emits_stale_reclaim_claim_origin(caplog) -> None:
    repository = _InMemoryAlertDeliveryRepository(
        fail_finalize_delivery_once=True,
    )
    telegram_client = _SequencedTelegramClient()
    service = _service(
        repository=repository,
        telegram_client=telegram_client,
        claim_ttl_seconds=0.0,
    )
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    with pytest.raises(AlertDeliveryStorageError):
        asyncio.run(service.submit_delivery(request=request, request_id="req_1"))

    repository.expire_claim("alert_1")

    with caplog.at_level(logging.INFO, logger="telegram_ingress"):
        processed = asyncio.run(service.process_due_deliveries())

    assert processed == 1
    events = _events(caplog)
    claim_event = next(
        event
        for event in events
        if event["event"] == "telegram_alert_delivery_claimed"
        and event["claim_origin"] == "stale_reclaim"
    )
    assert claim_event["delivery_id"] == "alert_1"
    assert claim_event["claim_origin"] == "stale_reclaim"


def test_submit_delivery_updates_metrics_for_successful_lifecycle() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient()
    metrics = AlertDeliveryMetrics()
    service = _service(
        repository=repository,
        telegram_client=telegram_client,
        metrics=metrics,
    )
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    submission = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))
    exported = metrics.render_prometheus()

    assert submission.status == "sent"
    assert 'telegram_alert_delivery_claim_total{origin="pending"} 1' in exported
    assert (
        'telegram_alert_delivery_target_attempt_total{error_class="none",status="sent"} 1'
        in exported
    )
    assert 'telegram_alert_delivery_finalize_total{status="completed"} 1' in exported


def test_submit_delivery_updates_metrics_for_retryable_attempt() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient(
        failures={
            11: [
                TelegramSendError(
                    "rate limited",
                    status_code=429,
                    retry_after_seconds=10.0,
                )
            ]
        }
    )
    metrics = AlertDeliveryMetrics()
    service = _service(
        repository=repository,
        telegram_client=telegram_client,
        metrics=metrics,
        retry_backoff_seconds=1.0,
    )
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    submission = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))
    exported = metrics.render_prometheus()

    assert submission.status == "accepted"
    assert (
        'telegram_alert_delivery_target_attempt_total{error_class="http_429",status="pending"} 1'
        in exported
    )
    assert 'telegram_alert_delivery_finalize_total{status="pending"} 1' in exported


def test_finalize_failure_updates_metrics() -> None:
    repository = _InMemoryAlertDeliveryRepository(
        fail_finalize_delivery_once=True,
    )
    telegram_client = _SequencedTelegramClient()
    metrics = AlertDeliveryMetrics()
    service = _service(
        repository=repository,
        telegram_client=telegram_client,
        metrics=metrics,
    )
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    with pytest.raises(AlertDeliveryStorageError):
        asyncio.run(service.submit_delivery(request=request, request_id="req_1"))

    exported = metrics.render_prometheus()
    assert "telegram_alert_delivery_finalize_failed_total 1" in exported


def test_claim_delivery_rechecks_next_attempt_at_before_stale_reclaim() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    created_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    record = repository.enqueue_delivery(
        request=AlertDeliveryRequest(
            deliveries=((11, "critical alert"),),
            matched_alerts=1,
            idempotency_key="critical-alert-v1",
        ),
        idempotency_key="telegram_alert:critical-alert-v1",
        created_at=created_at,
    )
    due_ids = repository.list_due_delivery_ids(
        now=datetime.now(timezone.utc),
        limit=10,
    )
    assert due_ids == (record.delivery_id,)

    claimed = repository.claim_delivery(
        delivery_id=record.delivery_id,
        now=datetime.now(timezone.utc),
        locked_until=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    assert claimed is not None

    repository.record_target_attempt(
        delivery_id=record.delivery_id,
        attempt=AlertTargetAttempt(
            chat_id=11,
            status="pending",
            error_code="http_429",
            error_message="rate limited",
            retry_after_seconds=10.0,
        ),
        completed_at=datetime.now(timezone.utc),
        retry_backoff_seconds=5.0,
        max_attempts=3,
    )
    updated = repository.finalize_delivery(
        delivery_id=record.delivery_id,
        completed_at=datetime.now(timezone.utc),
        retry_backoff_seconds=5.0,
        max_attempts=3,
    )
    assert updated.status == "pending"
    assert updated.next_attempt_at is not None
    assert updated.next_attempt_at > datetime.now(timezone.utc)

    stale_reclaim = repository.claim_delivery(
        delivery_id=record.delivery_id,
        now=datetime.now(timezone.utc),
        locked_until=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    assert stale_reclaim is None


def test_duplicate_pending_delivery_does_not_bypass_retry_backoff() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient(
        failures={11: [TelegramSendError("temporary", status_code=503)]}
    )
    service = _service(repository=repository, telegram_client=telegram_client)
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    first = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))
    second = asyncio.run(service.submit_delivery(request=request, request_id="req_2"))

    assert first.status == "accepted"
    assert second.status == "accepted"
    assert second.deduplicated is True
    assert telegram_client.sent_messages == []


def test_submit_delivery_marks_terminal_failure_without_retry_loop() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient(
        failures={11: [TelegramSendError("invalid chat", status_code=400)]}
    )
    service = _service(repository=repository, telegram_client=telegram_client)
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    submission = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))
    processed = asyncio.run(service.process_due_deliveries())
    record = repository.get_delivery(delivery_id=submission.delivery_id)

    assert submission.status == "failed"
    assert processed == 0
    assert record is not None
    assert record.status == "failed"
    assert record.last_error_code == "http_400"
    assert telegram_client.sent_messages == []


def test_partial_target_failure_retries_only_unsent_targets() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    telegram_client = _SequencedTelegramClient(
        failures={22: [TelegramSendError("temporary", status_code=503)]}
    )
    service = _service(repository=repository, telegram_client=telegram_client)
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"), (22, "critical alert")),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    submission = asyncio.run(service.submit_delivery(request=request, request_id="req_1"))
    repository.force_due(submission.delivery_id)
    asyncio.run(service.process_due_deliveries())
    record = repository.get_delivery(delivery_id=submission.delivery_id)

    assert submission.status == "accepted"
    assert record is not None
    assert record.status == "completed"
    assert telegram_client.sent_messages == [
        (11, "critical alert"),
        (22, "critical alert"),
    ]


def test_pending_delivery_survives_service_restart() -> None:
    repository = _InMemoryAlertDeliveryRepository()
    failing_client = _SequencedTelegramClient(
        failures={11: [TelegramSendError("temporary", status_code=503)]}
    )
    first_service = _service(repository=repository, telegram_client=failing_client)
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    submission = asyncio.run(first_service.submit_delivery(request=request, request_id="req_1"))
    repository.force_due(submission.delivery_id)

    recovery_client = _SequencedTelegramClient()
    second_service = _service(repository=repository, telegram_client=recovery_client)
    processed = asyncio.run(second_service.process_due_deliveries())
    record = repository.get_delivery(delivery_id=submission.delivery_id)

    assert submission.status == "accepted"
    assert processed == 1
    assert record is not None
    assert record.status == "completed"
    assert recovery_client.sent_messages == [(11, "critical alert")]


def test_finalize_failure_does_not_resend_already_persisted_targets() -> None:
    repository = _InMemoryAlertDeliveryRepository(
        fail_finalize_delivery_once=True,
    )
    telegram_client = _SequencedTelegramClient()
    service = _service(
        repository=repository,
        telegram_client=telegram_client,
        claim_ttl_seconds=0.0,
    )
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"), (22, "critical alert")),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    with pytest.raises(AlertDeliveryStorageError):
        asyncio.run(service.submit_delivery(request=request, request_id="req_1"))

    repository.expire_claim("alert_1")
    recovery_service = _service(
        repository=repository,
        telegram_client=telegram_client,
        claim_ttl_seconds=0.0,
    )
    processed = asyncio.run(recovery_service.process_due_deliveries())
    record = repository.get_delivery(delivery_id="alert_1")

    assert processed == 1
    assert record is not None
    assert record.status == "completed"
    assert telegram_client.sent_messages == [
        (11, "critical alert"),
        (22, "critical alert"),
    ]


def test_finalize_failure_preserves_pending_backoff() -> None:
    repository = _InMemoryAlertDeliveryRepository(
        fail_finalize_delivery_once=True,
    )
    telegram_client = _SequencedTelegramClient(
        failures={
            11: [
                TelegramSendError(
                    "rate limited",
                    status_code=429,
                    retry_after_seconds=10.0,
                )
            ]
        }
    )
    service = _service(
        repository=repository,
        telegram_client=telegram_client,
        retry_backoff_seconds=1.0,
        claim_ttl_seconds=0.0,
    )
    request = AlertDeliveryRequest(
        deliveries=((11, "critical alert"),),
        matched_alerts=1,
        idempotency_key="critical-alert-v1",
    )

    with pytest.raises(AlertDeliveryStorageError):
        asyncio.run(service.submit_delivery(request=request, request_id="req_1"))

    repository.expire_claim("alert_1")
    processed = asyncio.run(service.process_due_deliveries())
    record = repository.get_delivery(delivery_id="alert_1")

    assert processed == 0
    assert record is not None
    assert record.status == "delivering"
    assert record.next_attempt_at is not None
    assert telegram_client.sent_messages == []
