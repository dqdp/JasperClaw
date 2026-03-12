from typing import Any

import httpx


class TelegramSendError(RuntimeError):
    """Raised when Telegram sendMessage API returns a transport or protocol failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TelegramClient:
    def __init__(
        self,
        *,
        bot_token: str,
        api_base_url: str = "https://api.telegram.org",
        timeout_seconds: float = 5.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._api_base_url = api_base_url.rstrip("/")
        self._http_client = http_client or httpx.AsyncClient(
            timeout=timeout_seconds,
        )
        self._owns_client = http_client is None

    @property
    def base_api_url(self) -> str:
        return f"{self._api_base_url}/bot{self._bot_token}"

    async def close(self) -> None:
        if self._owns_client:
            await self._http_client.aclose()

    async def send_message(self, *, chat_id: int, text: str) -> None:
        response = await self._request(
            "POST",
            f"{self.base_api_url}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        if not response.get("ok"):
            raise TelegramSendError(
                response.get("description", "telegram-send-failed")
            )

    async def set_webhook(
        self,
        *,
        url: str,
        secret_token: str | None = None,
        drop_pending_updates: bool = True,
        max_connections: int | None = None,
        allowed_updates: list[str] | None = None,
    ) -> None:
        payload = {
            "url": url,
            "drop_pending_updates": drop_pending_updates,
        }
        if secret_token:
            payload["secret_token"] = secret_token
        if max_connections is not None:
            payload["max_connections"] = max_connections
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates

        response = await self._request(
            "POST",
            f"{self.base_api_url}/setWebhook",
            json=payload,
        )
        if not response.get("ok"):
            raise TelegramSendError(
                response.get("description", "telegram-setwebhook-failed")
            )

    async def get_updates(
        self,
        *,
        timeout: int = 30,
        offset: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if offset is not None:
            params["offset"] = offset

        response = await self._request(
            "GET",
            f"{self.base_api_url}/getUpdates",
            params=params,
        )
        if not response.get("ok"):
            raise TelegramSendError(response.get("description", "telegram-getupdates-failed"))

        updates = response.get("result")
        if not isinstance(updates, list):
            raise TelegramSendError("telegram getUpdates payload missing result list")

        output: list[dict[str, Any]] = []
        for update in updates:
            if isinstance(update, dict):
                output.append(update)
        return output

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._http_client.request(
                method=method,
                url=url,
                json=json,
                params=params,
            )
        except httpx.TimeoutException as exc:
            raise TelegramSendError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise TelegramSendError(str(exc)) from exc

        if response.status_code >= 400:
            raise TelegramSendError(
                f"HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramSendError("non-json response from telegram") from exc
        if not isinstance(payload, dict):
            raise TelegramSendError("telegram response must be a JSON object")
        return payload
