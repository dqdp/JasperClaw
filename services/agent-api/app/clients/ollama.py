from dataclasses import dataclass

import httpx

from app.core.errors import APIError
from app.schemas.chat import ChatMessage


@dataclass(slots=True)
class OllamaChatResult:
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class OllamaChatClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def chat(self, model: str, messages: list[ChatMessage]) -> OllamaChatResult:
        payload = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "stream": False,
        }

        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise APIError(
                status_code=504,
                error_type="dependency_unavailable",
                code="dependency_timeout",
                message="Model runtime timed out",
            ) from exc
        except httpx.RequestError as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_unavailable",
                message="Model runtime unavailable",
            ) from exc

        if response.status_code >= 500:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned an invalid response",
            )
        if response.status_code >= 400:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_protocol_error",
                message="Model runtime rejected the request",
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned invalid JSON",
            ) from exc

        message = data.get("message")
        if not isinstance(message, dict):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned an unexpected payload",
            )

        content = message.get("content")
        if not isinstance(content, str):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned an unexpected payload",
            )

        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        total_tokens = None
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            total_tokens = prompt_tokens + completion_tokens

        return OllamaChatResult(
            content=content,
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            completion_tokens=completion_tokens
            if isinstance(completion_tokens, int)
            else None,
            total_tokens=total_tokens,
        )

    def check_ready(self, models: tuple[str, ...]) -> None:
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.get(f"{self._base_url}/api/tags")
        except httpx.TimeoutException as exc:
            raise APIError(
                status_code=504,
                error_type="dependency_unavailable",
                code="dependency_timeout",
                message="Model runtime timed out",
            ) from exc
        except httpx.RequestError as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_unavailable",
                message="Model runtime unavailable",
            ) from exc

        if response.status_code != 200:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_unavailable",
                message="Model runtime unavailable",
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned invalid JSON",
            ) from exc

        model_entries = data.get("models")
        if not isinstance(model_entries, list):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Model runtime returned an unexpected payload",
            )

        available_models = {
            entry.get("name")
            for entry in model_entries
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        }
        expected_models = {model for model in models if model}
        if not expected_models.issubset(available_models):
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="runtime_model_unavailable",
                message="Model runtime missing required model",
            )
