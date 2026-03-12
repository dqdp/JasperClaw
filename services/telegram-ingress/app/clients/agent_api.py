from typing import Any

import httpx


class AgentApiError(RuntimeError):
    """Raised when /v1/chat/completions cannot be called successfully."""


class AgentApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 5.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = http_client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._http_client.aclose()

    async def complete(
        self,
        *,
        model: str,
        text: str,
        conversation_id: str,
        request_id: str,
    ) -> str:
        response = await self._request(
            method="POST",
            url=f"{self._base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": text}],
                "metadata": {
                    "source": "telegram",
                    # Telegram chat IDs are stable client-side session hints, not canonical
                    # backend conversation IDs, until the bridge can supply transcript continuity.
                    "client_conversation_id": conversation_id,
                },
            },
            extra_headers={
                "X-Request-ID": request_id,
            },
        )
        return response["choices"][0]["message"]["content"]

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json: dict[str, Any],
        extra_headers: dict[str, str],
    ) -> dict[str, Any]:
        all_headers = dict(headers)
        all_headers.update(extra_headers)
        try:
            response = await self._http_client.request(
                method=method,
                url=url,
                headers=all_headers,
                json=json,
            )
        except httpx.TimeoutException as exc:
            raise AgentApiError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AgentApiError(str(exc)) from exc

        if response.status_code >= 400:
            raise AgentApiError(f"HTTP {response.status_code}: {response.text}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise AgentApiError("non-json response from agent-api") from exc
        if not isinstance(payload, dict):
            raise AgentApiError("agent-api response must be a JSON object")

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AgentApiError("agent-api response is missing completion choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise AgentApiError("agent-api response message missing")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AgentApiError("agent-api response content missing")
        return payload
