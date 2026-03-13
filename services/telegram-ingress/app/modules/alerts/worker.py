from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.modules.alerts.facade import AlertFacade


class AlertRetryWorker:
    """Lifecycle-facing retry loop for durable alert delivery."""

    def __init__(
        self,
        *,
        alert_facade: AlertFacade,
        poll_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._alert_facade = alert_facade
        self._poll_seconds = max(poll_seconds, 0.1)
        self._sleep = sleep
        self._logger = logging.getLogger(__name__)

    async def run_once(self, *, limit: int = 10) -> int:
        return await self._alert_facade.process_due_once(limit=limit)

    async def run_forever(self, *, limit: int = 10) -> None:
        while True:
            try:
                processed = await self.run_once(limit=limit)
            except Exception:
                self._logger.exception("telegram alert retry loop error")
                await self._sleep(self._poll_seconds)
                continue
            if processed == 0:
                await self._sleep(self._poll_seconds)
            else:
                await self._sleep(0)
