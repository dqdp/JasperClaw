import json
from dataclasses import dataclass
from typing import Iterator

import httpx

from app.core.errors import APIError
from app.schemas.chat import ChatMessage


@dataclass(slots=True)
class OllamaChatResult:
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(slots=True)
class OllamaChatStreamChunk:
    content: str
    done: bool
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class OllamaChatClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def chat(self, model: str, messages: list[ChatMessage]) -> OllamaChatResult:
        payload = self._build_payload(model=model, messages=messages, stream=False)

        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise self._timeout_error() from exc
        except httpx.RequestError as exc:
            raise self._runtime_unavailable_error() from exc

        self._validate_response_status(response.status_code)

        try:
            data = response.json()
        except ValueError as exc:
            raise self._bad_response_error("Model runtime returned invalid JSON") from exc

        return self._parse_chat_result(data)

    def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
    ) -> Iterator[OllamaChatStreamChunk]:
        payload = self._build_payload(model=model, messages=messages, stream=True)

        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                with client.stream(
                    "POST",
                    f"{self._base_url}/api/chat",
                    json=payload,
                ) as response:
                    self._validate_response_status(response.status_code)
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except ValueError as exc:
                            raise self._bad_response_error(
                                "Model runtime returned invalid streaming JSON"
                            ) from exc
                        yield self._parse_stream_chunk(data)
        except httpx.TimeoutException as exc:
            raise self._timeout_error() from exc
        except httpx.RequestError as exc:
            raise self._runtime_unavailable_error() from exc

    def check_ready(self, models: tuple[str, ...]) -> None:
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.get(f"{self._base_url}/api/tags")
        except httpx.TimeoutException as exc:
            raise self._timeout_error() from exc
        except httpx.RequestError as exc:
            raise self._runtime_unavailable_error() from exc

        if response.status_code != 200:
            raise self._runtime_unavailable_error()

        try:
            data = response.json()
        except ValueError as exc:
            raise self._bad_response_error("Model runtime returned invalid JSON") from exc

        model_entries = data.get("models")
        if not isinstance(model_entries, list):
            raise self._bad_response_error("Model runtime returned an unexpected payload")

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

    def _build_payload(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        stream: bool,
    ) -> dict:
        return {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "stream": stream,
        }

    def _validate_response_status(self, status_code: int) -> None:
        if status_code >= 500:
            raise self._bad_response_error("Model runtime returned an invalid response")
        if status_code >= 400:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_protocol_error",
                message="Model runtime rejected the request",
            )

    def _parse_chat_result(self, data: dict) -> OllamaChatResult:
        content, prompt_tokens, completion_tokens, total_tokens = self._parse_payload(data)
        return OllamaChatResult(
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    def _parse_stream_chunk(self, data: dict) -> OllamaChatStreamChunk:
        content, prompt_tokens, completion_tokens, total_tokens = self._parse_payload(data)
        done = data.get("done")
        if not isinstance(done, bool):
            raise self._bad_response_error("Model runtime returned an unexpected payload")
        return OllamaChatStreamChunk(
            content=content,
            done=done,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    def _parse_payload(
        self,
        data: dict,
    ) -> tuple[str, int | None, int | None, int | None]:
        if not isinstance(data, dict):
            raise self._bad_response_error("Model runtime returned an unexpected payload")

        message = data.get("message")
        if not isinstance(message, dict):
            raise self._bad_response_error("Model runtime returned an unexpected payload")

        content = message.get("content")
        if not isinstance(content, str):
            raise self._bad_response_error("Model runtime returned an unexpected payload")

        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        total_tokens = None
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            total_tokens = prompt_tokens + completion_tokens

        return (
            content,
            prompt_tokens if isinstance(prompt_tokens, int) else None,
            completion_tokens if isinstance(completion_tokens, int) else None,
            total_tokens,
        )

    def _timeout_error(self) -> APIError:
        return APIError(
            status_code=504,
            error_type="dependency_unavailable",
            code="dependency_timeout",
            message="Model runtime timed out",
        )

    def _runtime_unavailable_error(self) -> APIError:
        return APIError(
            status_code=503,
            error_type="dependency_unavailable",
            code="runtime_unavailable",
            message="Model runtime unavailable",
        )

    def _bad_response_error(self, message: str) -> APIError:
        return APIError(
            status_code=502,
            error_type="upstream_error",
            code="dependency_bad_response",
            message=message,
        )
