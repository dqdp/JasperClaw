import httpx

from app.core.errors import APIError


class SttClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        files = {
            "file": (
                filename or "upload.bin",
                audio_bytes,
                content_type or "application/octet-stream",
            )
        }
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(f"{self._base_url}/transcribe", files=files)
        except httpx.TimeoutException as exc:
            raise APIError(
                status_code=504,
                error_type="dependency_unavailable",
                code="dependency_timeout",
                message="Speech-to-text service timed out",
            ) from exc
        except httpx.RequestError as exc:
            raise APIError(
                status_code=503,
                error_type="dependency_unavailable",
                code="transcription_service_unavailable",
                message="Speech-to-text service unavailable",
            ) from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError as exc:
                raise APIError(
                    status_code=502,
                    error_type="upstream_error",
                    code="dependency_bad_response",
                    message="Speech-to-text service returned invalid JSON",
                ) from exc

            error = payload.get("error") if isinstance(payload, dict) else None
            if (
                isinstance(error, dict)
                and isinstance(error.get("type"), str)
                and isinstance(error.get("code"), str)
                and isinstance(error.get("message"), str)
            ):
                raise APIError(
                    status_code=response.status_code,
                    error_type=error["type"],
                    code=error["code"],
                    message=error["message"],
                )

            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Speech-to-text service returned an unexpected payload",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Speech-to-text service returned invalid JSON",
            ) from exc

        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            raise APIError(
                status_code=502,
                error_type="upstream_error",
                code="dependency_bad_response",
                message="Speech-to-text service returned an unexpected payload",
            )
        return text
