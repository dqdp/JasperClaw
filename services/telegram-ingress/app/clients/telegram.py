from typing import Any

import httpx


class TelegramSendError(RuntimeError):
    """Raised when Telegram sendMessage API returns a transport or protocol failure."""


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

    async def _request(self, method: str, url: str, json: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._http_client.request(method=method, url=url, json=json)
        except httpx.TimeoutException as exc:
            raise TelegramSendError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise TelegramSendError(str(exc)) from exc

        if response.status_code >= 400:
            raise TelegramSendError(f"HTTP {response.status_code}: {response.text}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramSendError("non-json response from telegram") from exc
        if not isinstance(payload, dict):
            raise TelegramSendError("telegram response must be a JSON object")
        return payload
