from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from app.clients.telegram import TelegramSendError
from app.services.alert_delivery import (
    AlertDeliveryRecord,
    AlertDeliveryRequest,
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
    def __init__(self) -> None:
        self._records: dict[str, _StoredDelivery] = {}
        self._idempotency_index: dict[str, str] = {}
        self._sequence = 0

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
            if record.status == "delivering" and stored.locked_until is not None and stored.locked_until <= now:
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
        if stored.record.status not in {"pending", "delivering"}:
            return None
        if stored.locked_until is not None and stored.locked_until > now:
            return None
        stored.locked_until = locked_until
        stored.record = replace(
            stored.record,
            status="delivering",
        )
        return stored.record

    def apply_attempt_results(
        self,
        *,
        delivery_id: str,
        attempts: tuple[AlertTargetAttempt, ...],
        completed_at: datetime,
        retry_backoff_seconds: float,
        max_attempts: int,
    ) -> AlertDeliveryRecord:
        stored = self._records[delivery_id]
        attempt_map = {attempt.chat_id: attempt for attempt in attempts}
        updated_targets: list[AlertDeliveryTargetRecord] = []
        for target in stored.record.targets:
            attempt = attempt_map.get(target.chat_id)
            if attempt is None:
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
            updated_targets.append(updated_target)

        if all(target.status == "sent" for target in updated_targets):
            status = "completed"
            next_attempt_at = None
            last_error_code = None
            last_error_message = None
        else:
            pending_targets = [target for target in updated_targets if target.status == "pending"]
            if pending_targets:
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
                status = "pending"
                next_attempt_at = completed_at + timedelta(seconds=next_retry_delay_seconds)
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
    retry_backoff_seconds: float = 0.0,
    max_attempts: int = 3,
) -> AlertDeliveryService:
    return AlertDeliveryService(
        repository=repository,
        telegram_client=telegram_client,
        retry_backoff_seconds=retry_backoff_seconds,
        max_attempts=max_attempts,
        claim_ttl_seconds=30.0,
    )


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
