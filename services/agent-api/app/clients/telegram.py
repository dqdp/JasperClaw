from __future__ import annotations

from typing import Any

import httpx

from app.core.errors import APIError


class TelegramClient:
    """Minimal synchronous Telegram Bot API adapter for agent-api tool execution."""

    def __init__(
        self,
        *,
        bot_token: str,
        api_base_url: str = "https://api.telegram.org",
        timeout_seconds: float = 5.0,
    ) -> None:
        self._bot_token = bot_token
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def base_api_url(self) -> str:
        return f"{self._api_base_url}/bot{self._bot_token}"

    def send_message(self, *, chat_id: int, text: str) -> None:
        payload = self._request(
            "POST",
            f"{self.base_api_url}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        if not payload.get("ok"):
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="telegram_send_failed",
                message=payload.get("description", "Telegram send failed"),
            )

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.request(method=method, url=url, json=json)
        except httpx.TimeoutException as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="telegram_unavailable",
                message="Telegram Bot API timed out",
            ) from exc
        except httpx.HTTPError as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="telegram_unavailable",
                message="Telegram Bot API unavailable",
            ) from exc

        if response.status_code >= 400:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="telegram_send_failed",
                message=f"Telegram Bot API returned HTTP {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Telegram Bot API returned invalid JSON",
            ) from exc

        if not isinstance(payload, dict):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Telegram Bot API returned an unexpected payload",
            )
        return payload
