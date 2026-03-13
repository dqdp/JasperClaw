import asyncio

import pytest

from app.modules.alerts.worker import AlertRetryWorker


class _FakeAlertFacade:
    def __init__(self, results: list[int | Exception]) -> None:
        self.results = list(results)
        self.calls: list[int] = []

    async def process_due_once(self, *, limit: int = 10) -> int:
        self.calls.append(limit)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.anyio
async def test_alert_retry_worker_run_once_delegates_limit() -> None:
    facade = _FakeAlertFacade([3])
    worker = AlertRetryWorker(alert_facade=facade, poll_seconds=5.0)

    processed = await worker.run_once(limit=7)

    assert processed == 3
    assert facade.calls == [7]


@pytest.mark.anyio
async def test_alert_retry_worker_sleeps_poll_interval_when_idle() -> None:
    facade = _FakeAlertFacade([0])
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError()

    worker = AlertRetryWorker(
        alert_facade=facade,
        poll_seconds=0.5,
        sleep=_sleep,
    )

    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever(limit=11)

    assert facade.calls == [11]
    assert sleeps == [0.5]


@pytest.mark.anyio
async def test_alert_retry_worker_yields_immediately_after_work() -> None:
    facade = _FakeAlertFacade([2])
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError()

    worker = AlertRetryWorker(
        alert_facade=facade,
        poll_seconds=1.5,
        sleep=_sleep,
    )

    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever()

    assert sleeps == [0]


@pytest.mark.anyio
async def test_alert_retry_worker_backs_off_after_error() -> None:
    facade = _FakeAlertFacade([RuntimeError("db unavailable")])
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError()

    worker = AlertRetryWorker(
        alert_facade=facade,
        poll_seconds=2.0,
        sleep=_sleep,
    )

    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever(limit=5)

    assert facade.calls == [5]
    assert sleeps == [2.0]
